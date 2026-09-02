/* Typer frontend. Talks to Python through window.pywebview.api and receives events via window.typer.emit. */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // ------------------------------------------------------------------ state
  const defaultPlan = () => ({
    text: '',
    settings: {
      char_delay_ms: 30, jitter_pct: 25, newline_mode: 'enter', word_pause_ms: 0, punct_pause_ms: 0,
      newline_pause_ms: 0, input_method: 'unicode', instant: false, final_key: '', typo_pct: 0,
    },
    split: 'whole',
    repeat_count: 1,
    repeat_interval_ms: 500,
    use_csv_rows: false,
    countdown_s: 3,
  });

  const state = {
    version: '',
    settings: { language: 'pl', theme: 'system', hotkeys: {}, hotkey_labels: {}, escape_stops: true },
    hotkeyErrors: {},
    plan: defaultPlan(),
    presets: [],
    macros: [],
    csv: null,
    csvRow: 0,
    target: null,                       // last external window (live)
    targetChoice: { mode: 'auto', hwnd: 0 },
    chosenWindow: null,
    session: { state: 'idle', kind: '' },
    position: { last: -1, total: 0 },   // playhead: index of the last typed item
    items: 0,                           // number of items the current plan expands to
    recording: false,
    macroDraft: null,
    macroDirty: false,
    dataDir: '',
    initialized: false,
  };

  // ------------------------------------------------------------------ i18n
  const t = (key, params) => {
    const table = window.TYPER_I18N || {};
    let text = (table[state.settings.language] || {})[key] ?? (table.pl || {})[key] ?? key;
    if (params) for (const [name, value] of Object.entries(params)) text = text.split(`{${name}}`).join(String(value));
    return text;
  };

  function applyLanguage() {
    document.documentElement.lang = state.settings.language;
    $$('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    $$('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    $$('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); });
    $('#about-text').textContent = t('settings.about_text', { version: state.version });
  }

  const KEY_LABELS = {
    pageup: 'Page Up', pagedown: 'Page Down', printscreen: 'Print Screen', capslock: 'Caps Lock',
    numlock: 'Num Lock', scrolllock: 'Scroll Lock', escape: 'Esc', apps: 'Menu',
    ctrl: 'Ctrl', alt: 'Alt', shift: 'Shift', win: 'Win',
  };
  // Mirrors format_combo() in engine/keys.py for instant feedback in the UI.
  function formatCombo(spec) {
    if (!spec) return '';
    let mods, key;
    if (spec === '+') { mods = []; key = '+'; }
    else if (spec.endsWith('++')) { mods = spec.slice(0, -2).split('+').filter(Boolean); key = '+'; }
    else { const parts = spec.split('+'); key = parts.pop(); mods = parts; }
    const order = ['ctrl', 'alt', 'shift', 'win'];
    const labels = order.filter(m => mods.includes(m)).map(m => KEY_LABELS[m]);
    let label;
    if (key.length === 1) label = key.toUpperCase();
    else if (KEY_LABELS[key]) label = KEY_LABELS[key];
    else if (/^f\d+$/.test(key)) label = key.toUpperCase();
    else if (/^num\d$/.test(key)) label = 'Num ' + key.slice(3);
    else label = key.charAt(0).toUpperCase() + key.slice(1);
    labels.push(label);
    return labels.join('+');
  }

  function keyNameFromEvent(e) {
    const k = e.key;
    if (['Control', 'Shift', 'Alt', 'Meta', 'AltGraph', 'CapsLock', 'NumLock', 'ScrollLock', 'Dead', 'Unidentified'].includes(k)) return '';
    const map = {
      Enter: 'enter', Tab: 'tab', ' ': 'space', Escape: 'escape', Backspace: 'backspace', Delete: 'delete',
      Insert: 'insert', Home: 'home', End: 'end', PageUp: 'pageup', PageDown: 'pagedown', ArrowUp: 'up',
      ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Pause: 'pause', PrintScreen: 'printscreen',
      ContextMenu: 'apps',
    };
    if (map[k]) return map[k];
    if (/^F\d{1,2}$/.test(k)) return k.toLowerCase();
    if (/^Numpad\d$/.test(e.code)) return 'num' + e.code.slice(-1);
    if (/^Key[A-Z]$/.test(e.code)) return e.code.slice(3).toLowerCase();
    if (/^Digit\d$/.test(e.code)) return e.code.slice(5);
    if (k.length === 1) return k.toLowerCase();
    return '';
  }

  function comboFromEvent(e) {
    const key = keyNameFromEvent(e);
    if (!key) return null;
    const mods = [];
    if (e.ctrlKey) mods.push('ctrl');
    if (e.altKey) mods.push('alt');
    if (e.shiftKey) mods.push('shift');
    if (e.metaKey) mods.push('win');
    return [...mods, key].join('+');
  }

  function bindHotkeyInput(el, onChange, { allowPlain = true } = {}) {
    el.addEventListener('keydown', e => {
      e.preventDefault();
      e.stopPropagation();
      if (e.key === 'Backspace' || e.key === 'Delete') { onChange(''); return; }
      const combo = comboFromEvent(e);
      if (!combo) return;
      if (!allowPlain && !/(ctrl|alt|win)\+/.test(combo) && !/^f\d+$/.test(combo)) return;
      onChange(combo);
    });
  }

  function fmtDuration(seconds) {
    const s = Math.max(0, Math.round(seconds));
    if (s < 60) return t('time.seconds', { s });
    if (s < 3600) return t('time.minutes', { m: Math.floor(s / 60), s: s % 60 });
    return t('time.hours', { h: Math.floor(s / 3600), m: Math.floor((s % 3600) / 60) });
  }

  const debounce = (fn, ms) => { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); }; };

  // ------------------------------------------------------------------ bridge
  async function call(name, ...args) {
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api[name] !== 'function') return { ok: false, error: 'no_bridge' };
    try {
      const result = await api[name](...args);
      return result || { ok: true };
    } catch (err) {
      console.error(name, err);
      toast('error', t('toast.error', { message: String(err && err.message || err) }));
      return { ok: false, error: 'exception', message: String(err) };
    }
  }

  function noticeText(code, message) {
    const key = 'notice.' + code;
    const text = t(key, { message: message || '' });
    return text === key ? (message || code) : text;
  }

  function reportFailure(result) {
    if (!result || result.ok || result.error === 'cancelled') return;
    toast(result.error === 'busy' || result.error === 'empty_text' ? 'warn' : 'error', noticeText(result.error, result.message));
  }

  // ------------------------------------------------------------------ toasts
  const ICONS = { success: '#i-check', error: '#i-alert', warn: '#i-alert', info: '#i-info' };
  const toasts = [];
  function layoutToasts() {
    let bottom = 20;
    for (let i = toasts.length - 1; i >= 0; i--) {
      toasts[i].style.bottom = bottom + 'px';
      bottom += toasts[i].offsetHeight + 10;
    }
  }
  function toast(kind, message, timeout = 3600) {
    const el = document.createElement('div');
    el.className = 'toast ' + kind;
    el.setAttribute('popover', 'manual');
    el.innerHTML = `<svg><use href="${ICONS[kind] || ICONS.info}"/></svg><span></span><button class="icon-btn small toast-close"><svg><use href="#i-x"/></svg></button>`;
    el.querySelector('span').textContent = message;
    document.body.appendChild(el);
    toasts.push(el);
    const close = () => {
      const idx = toasts.indexOf(el);
      if (idx >= 0) toasts.splice(idx, 1);
      try { el.hidePopover(); } catch (_) { /* already closed */ }
      setTimeout(() => el.remove(), 250);
      layoutToasts();
    };
    el.querySelector('.toast-close').addEventListener('click', close);
    el.showPopover();
    layoutToasts();
    setTimeout(close, timeout);
  }

  // ------------------------------------------------------------------ dialogs
  function openDialog({ title, message = '', input = null, okLabel, danger = false }) {
    return new Promise(resolve => {
      const dialog = $('#dialog');
      const field = $('#dialog-input');
      const ok = $('#dialog-ok');
      $('#dialog-title').textContent = title;
      $('#dialog-message').textContent = message;
      field.hidden = input === null;
      if (input !== null) { field.value = input.value || ''; field.placeholder = input.placeholder || ''; }
      ok.textContent = okLabel || t('dialog.ok');
      ok.classList.toggle('danger', danger);
      ok.classList.toggle('primary', !danger);
      const finish = value => { dialog.close(); cleanup(); resolve(value); };
      const onSubmit = e => { e.preventDefault(); if (input !== null && !field.value.trim()) { field.focus(); return; } finish(input !== null ? field.value.trim() : true); };
      const onCancel = () => finish(null);
      const cleanup = () => { dialog.querySelector('form').removeEventListener('submit', onSubmit); $('#dialog-cancel').removeEventListener('click', onCancel); dialog.removeEventListener('cancel', onCancel); };
      dialog.querySelector('form').addEventListener('submit', onSubmit);
      $('#dialog-cancel').addEventListener('click', onCancel);
      dialog.addEventListener('cancel', onCancel);
      dialog.showModal();
      if (input !== null) { field.focus(); field.select(); }
      else ok.focus();
    });
  }
  const promptDialog = (title, options = {}) => openDialog({ title, input: options, okLabel: options.okLabel });
  const confirmDialog = (title, message = '', danger = false) => openDialog({ title, message, okLabel: danger ? t('dialog.delete') : t('dialog.ok'), danger });

  // ------------------------------------------------------------------ theme
  const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
  function effectiveTheme() {
    const theme = state.settings.theme;
    return theme === 'light' || theme === 'dark' ? theme : (darkQuery.matches ? 'dark' : 'light');
  }
  function applyTheme() {
    const theme = state.settings.theme;
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    $('meta[name="color-scheme"]').content = theme === 'light' || theme === 'dark' ? theme : 'light dark';
    $('#theme-toggle use').setAttribute('href', effectiveTheme() === 'dark' ? '#i-sun' : '#i-moon');
    $$('input[name="theme"]').forEach(r => { r.checked = r.value === theme; });
  }
  darkQuery.addEventListener('change', applyTheme);

  async function saveSettings(patch) {
    Object.assign(state.settings, patch);
    applyTheme();
    const result = await call('save_settings', {
      language: state.settings.language, theme: state.settings.theme,
      hotkeys: state.settings.hotkeys, escape_stops: state.settings.escape_stops,
    });
    if (result.ok) {
      state.settings = Object.assign(state.settings, result.settings);
      state.hotkeyErrors = result.hotkey_errors || {};
      renderHotkeys();
      renderHotkeyHints();
      reportHotkeyErrors();
    } else reportFailure(result);
  }

  // ------------------------------------------------------------------ views
  function showView(name) {
    $$('.rail-item').forEach(b => b.classList.toggle('is-active', b.dataset.view === name));
    $$('.view').forEach(v => v.classList.toggle('is-active', v.id === 'view-' + name));
  }

  // ------------------------------------------------------------------ plan binding
  const getPath = (obj, path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
  const setPath = (obj, path, value) => { const keys = path.split('.'); const last = keys.pop(); let o = obj; for (const k of keys) o = o[k]; o[last] = value; };

  function readInput(el) {
    if (el.type === 'checkbox') return el.dataset.on ? (el.checked ? el.dataset.on : el.dataset.off) : el.checked;
    if (el.type === 'range' || el.type === 'number') {
      const n = Number(el.value);
      if (!Number.isFinite(n)) return Number(el.min || 0);
      const min = el.min !== '' ? Number(el.min) : -Infinity;
      const max = el.max !== '' ? Number(el.max) : Infinity;
      return Math.min(max, Math.max(min, n));
    }
    return el.value;
  }
  function writeInput(el, value) {
    if (el.type === 'checkbox') el.checked = el.dataset.on ? value === el.dataset.on : !!value;
    else if (el.type === 'radio') el.checked = el.value === String(value);
    else el.value = value ?? '';
    if (el.type === 'range') updateRange(el);
  }
  function updateRange(el) {
    const min = Number(el.min || 0), max = Number(el.max || 100);
    el.style.setProperty('--p', ((Number(el.value) - min) / (max - min) * 100) + '%');
  }

  function bindPlanInputs() {
    $$('[data-plan]').forEach(el => {
      el.addEventListener('input', () => {
        setPath(state.plan, el.dataset.plan, readInput(el));
        if (el.type === 'range') updateRange(el);
        onPlanChanged();
      });
      if (el.type === 'number') el.addEventListener('change', () => { writeInput(el, getPath(state.plan, el.dataset.plan)); });
    });
    $('#text').addEventListener('input', () => { state.plan.text = $('#text').value; onPlanChanged(); });
    $('#text').addEventListener('keydown', e => {
      if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); startTyping(); }
      if (e.key === 'Tab') { e.preventDefault(); insertAtCaret('\t'); }
    });
  }

  function applyPlan() {
    $$('[data-plan]').forEach(el => writeInput(el, getPath(state.plan, el.dataset.plan)));
    $('#text').value = state.plan.text;
    updateOutputs();
    scheduleEstimate();
  }

  function updateOutputs() {
    const s = state.plan.settings;
    $('#out-delay').textContent = `${Math.round(s.char_delay_ms)} ${t('units.ms')}`;
    $('#out-jitter').textContent = `±${s.jitter_pct}${t('units.pct')}`;
    $('#out-typos').textContent = s.typo_pct > 0 ? `${s.typo_pct}${t('units.pct')}` : t('tempo.off');
    const text = state.plan.text;
    $('#meta-chars').textContent = t('editor.chars', { count: text.length });
  }

  const saveDraft = debounce(() => { call('save_draft', planForStorage()); }, 700);
  function planForStorage() {
    const { text, settings, split, repeat_count, repeat_interval_ms, use_csv_rows, countdown_s } = state.plan;
    return { text, settings: { ...settings }, split, repeat_count, repeat_interval_ms, use_csv_rows, countdown_s };
  }
  function onPlanChanged() {
    updateOutputs();
    scheduleEstimate();
    saveDraft();
  }

  const scheduleEstimate = debounce(async () => {
    const result = await call('estimate', planForStorage());
    if (!result.ok) return;
    $('#meta-estimate').textContent = t('editor.estimate', { time: fmtDuration(result.seconds) });
    state.items = result.items || 0;
    renderChips(result.placeholders);
    renderPosition();
  }, 220);

  function renderPosition() {
    const total = state.items || state.position.total || 0;
    const next = total ? (((state.position.last + 1) % total) + total) % total : 0;
    $('#position').textContent = total ? `${next + 1} / ${total}` : '';
    const busy = state.session.state !== 'idle';
    const stepping = state.session.kind === 'macro' || (busy && state.session.state === 'countdown');
    $('#btn-prev').disabled = !total || stepping;
    $('#btn-next').disabled = !total || stepping;
    $('#btn-stop').disabled = !busy && state.position.last < 0;
  }

  function renderChips(placeholders) {
    const box = $('#chips');
    box.innerHTML = '';
    for (const p of placeholders) {
      const chip = document.createElement('span');
      chip.className = 'chip ' + p.kind;
      chip.innerHTML = `{${escapeHtml(p.name)}} <small>${t('chip.' + p.kind)}</small>`;
      box.appendChild(chip);
    }
  }

  function insertAtCaret(snippet) {
    const area = $('#text');
    const start = area.selectionStart, end = area.selectionEnd;
    area.setRangeText(snippet, start, end, 'end');
    area.focus();
    state.plan.text = area.value;
    onPlanChanged();
  }

  const escapeHtml = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ------------------------------------------------------------------ target
  function renderTarget() {
    const dot = $('#target-dot'), title = $('#target-title'), sub = $('#target-sub');
    dot.className = 'target-dot';
    if (state.targetChoice.mode === 'window' && state.chosenWindow) {
      dot.classList.add('is-fixed');
      title.textContent = state.chosenWindow.title;
      sub.textContent = `${state.chosenWindow.process} · ${t('target.chosen_hint')}`;
    } else if (state.target) {
      dot.classList.add('is-live');
      title.textContent = state.target.title;
      sub.textContent = `${state.target.process} · ${t('target.auto_hint')}`;
    } else {
      title.textContent = t('target.none');
      sub.textContent = t('target.none_hint');
    }
  }

  async function refreshWindowList() {
    const list = $('#target-list');
    const result = await call('list_windows');
    list.innerHTML = '';
    const auto = document.createElement('button');
    auto.className = 'pop-item' + (state.targetChoice.mode === 'auto' ? ' is-selected' : '');
    auto.innerHTML = `<svg><use href="#i-crosshair"/></svg><span class="pi-text"><strong></strong><small></small></span>`;
    auto.querySelector('strong').textContent = t('target.auto');
    auto.querySelector('small').textContent = state.target ? `${state.target.title}` : t('target.none');
    auto.addEventListener('click', () => { state.targetChoice = { mode: 'auto', hwnd: 0 }; state.chosenWindow = null; renderTarget(); $('#target-pop').hidePopover(); });
    list.appendChild(auto);
    const windows = result.ok ? result.windows : [];
    if (!windows.length) {
      const empty = document.createElement('div');
      empty.className = 'pop-empty';
      empty.textContent = t('target.no_windows');
      list.appendChild(empty);
    }
    for (const w of windows) {
      const item = document.createElement('button');
      item.className = 'pop-item' + (state.targetChoice.mode === 'window' && state.targetChoice.hwnd === w.hwnd ? ' is-selected' : '');
      item.innerHTML = `<svg><use href="#i-window"/></svg><span class="pi-text"><strong></strong><small></small></span>`;
      item.querySelector('strong').textContent = w.title;
      item.querySelector('small').textContent = w.process;
      item.addEventListener('click', () => { state.targetChoice = { mode: 'window', hwnd: w.hwnd }; state.chosenWindow = w; renderTarget(); $('#target-pop').hidePopover(); });
      list.appendChild(item);
    }
  }

  function renderHotkeyHints() {
    const labels = state.settings.hotkey_labels || {};
    const box = $('#hotkey-hints');
    box.innerHTML = '';
    for (const name of ['start_pause', 'stop_reset', 'prev', 'next']) {
      if (!labels[name]) continue;
      const span = document.createElement('span');
      span.innerHTML = `<kbd></kbd>`;
      span.querySelector('kbd').textContent = labels[name];
      span.append(t('hints.' + name));
      box.appendChild(span);
    }
    for (const [id, name] of [['#kbd-start', 'start_pause'], ['#kbd-stop', 'stop_reset'], ['#kbd-prev', 'prev'], ['#kbd-next', 'next']]) {
      $(id).textContent = labels[name] || '';
      $(id).hidden = !labels[name];
    }
  }

  // ------------------------------------------------------------------ csv
  function renderCsv() {
    const csv = state.csv;
    $('#csv-empty').hidden = !!csv;
    $('#csv-loaded').hidden = !csv;
    if (!csv) { state.plan.use_csv_rows = false; $('#csv-preview').hidden = true; return; }
    $('#csv-name').textContent = csv.name;
    $('#csv-count').textContent = t('csv.rows', { count: csv.count });
    const cols = $('#csv-columns');
    cols.innerHTML = '';
    for (const column of csv.columns) {
      const chip = document.createElement('button');
      chip.className = 'chip csv clickable';
      chip.type = 'button';
      chip.textContent = `{${column}}`;
      chip.addEventListener('click', () => insertAtCaret(`{${column}}`));
      cols.appendChild(chip);
    }
    if (!$('#csv-preview').hidden) renderCsvPreview();
  }

  async function renderCsvPreview() {
    if (!state.csv) return;
    state.csvRow = Math.max(0, Math.min(state.csv.count - 1, state.csvRow));
    const result = await call('preview', state.plan.text, state.csvRow);
    if (!result.ok) return;
    $('#csv-row-label').textContent = t('csv.row', { n: result.row + 1, total: result.total });
    $('#csv-preview-text').textContent = result.text;
    $('#csv-prev').disabled = state.csvRow <= 0;
    $('#csv-next').disabled = state.csvRow >= state.csv.count - 1;
  }

  async function loadCsv() {
    const result = await call('load_csv');
    if (!result.ok) { reportFailure(result); return; }
    state.csv = result.csv;
    state.csvRow = 0;
    state.plan.use_csv_rows = true;
    writeInput($('[data-plan="use_csv_rows"]'), true);
    renderCsv();
    onPlanChanged();
    toast('success', t('toast.csv_loaded', { count: result.csv.count, name: result.csv.name }));
  }

  async function clearCsv() {
    await call('clear_csv');
    state.csv = null;
    renderCsv();
    onPlanChanged();
    toast('info', t('toast.csv_cleared'));
  }

  // ------------------------------------------------------------------ session
  function buildPlan() {
    return { ...planForStorage(), text: $('#text').value, target: state.targetChoice };
  }

  async function startTyping() {
    if (state.session.state !== 'idle') return;
    if (!$('#text').value.trim()) { toast('warn', t('notice.empty_text')); $('#text').focus(); return; }
    const result = await call('start', buildPlan());
    if (!result.ok) reportFailure(result);
  }

  async function step(direction) {
    if (state.session.state === 'idle' && !$('#text').value.trim()) { toast('warn', t('notice.empty_text')); $('#text').focus(); return; }
    const result = await call('step', buildPlan(), direction);
    if (!result.ok) reportFailure(result);
  }

  function applySessionState() {
    const st = state.session.state;
    const busy = st !== 'idle';
    document.body.classList.toggle('is-running', st === 'running' || st === 'countdown');
    document.body.classList.toggle('is-paused', st === 'paused');
    $('#btn-start').disabled = busy;
    $('#btn-pause').disabled = !(st === 'running' || st === 'paused');
    $('#btn-stop').disabled = !busy;
    $('#btn-pause-label').textContent = st === 'paused' ? t('action.resume') : t('action.pause');
    $('#btn-pause use').setAttribute('href', st === 'paused' ? '#i-play' : '#i-pause');
    $('#macro-run').disabled = busy;
    renderPosition();
    if (st === 'idle') {
      $('#status-text').textContent = t('status.ready');
      $('#status-sub').textContent = '';
      $('#progress-bar').style.width = '0%';
      hideCountdown();
    } else if (st === 'paused') {
      $('#status-text').textContent = t('status.paused');
    } else if (st === 'running') {
      $('#status-text').textContent = state.session.kind === 'macro' ? t('status.running_macro') : t('status.running');
      hideCountdown();
    }
  }

  function updateProgress(p) {
    $('#progress-bar').style.width = p.percent + '%';
    if (state.session.state === 'running') {
      const label = state.session.kind === 'macro' ? t('status.running_macro') : t('status.running');
      $('#status-text').textContent = `${label} ${Math.round(p.percent)}%`;
    }
    const iterations = p.iterations > 1 ? t('status.iteration', { i: p.iteration, n: p.iterations }) : '';
    const steps = state.session.kind === 'macro' ? t('status.step', { i: Math.min(p.total, p.done + 1), n: p.total }) : '';
    $('#status-sub').textContent = [iterations, steps].filter(Boolean).join(' · ');
  }

  function showCountdown(seconds) {
    const overlay = $('#countdown');
    overlay.hidden = false;
    const num = $('#countdown-num');
    num.textContent = seconds;
    num.classList.remove('tick');
    void num.offsetWidth;
    num.classList.add('tick');
    let target = t('countdown.foreground');
    if (state.targetChoice.mode === 'window' && state.chosenWindow) target = state.chosenWindow.title;
    else if (state.targetChoice.mode === 'auto' && state.target) target = state.target.title;
    $('#countdown-target').textContent = target;
    $('#status-text').textContent = t('status.countdown', { s: seconds });
  }
  function hideCountdown() { $('#countdown').hidden = true; }

  const eventHandlers = {
    state(p) { state.session = p; applySessionState(); },
    countdown(p) { if (p.seconds > 0) showCountdown(p.seconds); else hideCountdown(); },
    progress(p) { updateProgress(p); },
    finished(p) {
      hideCountdown();
      if (p.reason === 'done') toast('success', t(p.kind === 'macro' ? 'toast.macro_done' : 'toast.done'));
      else if (p.reason === 'cancelled') toast('info', t('toast.cancelled'));
      else if (p.reason === 'error') toast('error', t('toast.error', { message: p.message }));
    },
    notice(p) { toast(p.level === 'error' ? 'error' : 'warn', noticeText(p.code, p.message)); },
    target(p) { state.target = p; renderTarget(); },
    position(p) { state.position = p; renderPosition(); },
    recording(p) {
      state.recording = !!p.active;
      renderRecording();
      if (!p.active && Array.isArray(p.steps)) {
        if (p.steps.length && state.macroDraft) {
          state.macroDraft.steps.push(...p.steps);
          markMacroDirty();
          renderSteps();
          toast('success', t('toast.recorded', { count: p.steps.length }));
        } else if (!p.steps.length) toast('info', t('toast.recorded_none'));
      }
    },
  };

  window.typer = {
    emit(name, payload) {
      const handler = eventHandlers[name];
      if (handler) { try { handler(payload || {}); } catch (err) { console.error('event', name, err); } }
    },
    getPlan: buildPlan,
  };

  // ------------------------------------------------------------------ presets
  function renderPresets() {
    const grid = $('#preset-grid');
    grid.innerHTML = '';
    $('#preset-empty').hidden = state.presets.length > 0;
    for (const preset of state.presets) {
      const card = document.createElement('div');
      card.className = 'card preset';
      const settings = (preset.plan && preset.plan.settings) || {};
      const mode = settings.instant ? t('presets.mode.instant') : t('presets.mode.delay', { ms: Math.round(settings.char_delay_ms ?? 30) });
      const newline = { enter: 'Enter', shift_enter: 'Shift+Enter', ctrl_enter: 'Ctrl+Enter', none: '' }[settings.newline_mode] || '';
      card.innerHTML = `
        <div class="preset-head"><svg><use href="#i-bookmark"/></svg><strong></strong></div>
        <div class="preset-snippet"></div>
        <div class="preset-meta"><span class="badge"></span><span class="badge"></span><span class="badge nl" hidden></span></div>
        <div class="preset-actions">
          <button class="btn small primary act-load"><svg><use href="#i-download"/></svg><span>${t('presets.load')}</span></button>
          <span class="grow"></span>
          <button class="btn small danger-ghost act-delete"><svg><use href="#i-trash"/></svg></button>
        </div>`;
      card.querySelector('strong').textContent = preset.name;
      card.querySelector('.preset-snippet').textContent = (preset.text || '').slice(0, 160);
      const badges = card.querySelectorAll('.badge');
      badges[0].textContent = t('presets.chars', { count: (preset.text || '').length });
      badges[1].textContent = mode;
      if (newline) { badges[2].textContent = newline; badges[2].hidden = false; }
      card.querySelector('.act-load').addEventListener('click', () => loadPreset(preset));
      card.querySelector('.act-delete').addEventListener('click', async () => {
        if (!(await confirmDialog(t('presets.confirm_delete', { name: preset.name }), '', true))) return;
        const result = await call('delete_preset', preset.id);
        if (result.ok) { state.presets = result.presets; renderPresets(); toast('info', t('toast.preset_deleted')); }
      });
      grid.appendChild(card);
    }
  }

  function loadPreset(preset) {
    const fresh = defaultPlan();
    const plan = preset.plan || {};
    state.plan = {
      ...fresh, ...plan,
      settings: { ...fresh.settings, ...(plan.settings || {}) },
      text: preset.text || '',
    };
    applyPlan();
    saveDraft();
    showView('typer');
    toast('success', t('toast.preset_loaded', { name: preset.name }));
  }

  async function savePresetFromCurrent() {
    const name = await promptDialog(t('presets.name_prompt'), { placeholder: t('presets.name_prompt'), okLabel: t('dialog.save') });
    if (!name) return;
    const result = await call('save_preset', { name, text: $('#text').value, plan: planForStorage() });
    if (!result.ok) { reportFailure(result); return; }
    state.presets = result.presets;
    renderPresets();
    toast('success', t('toast.preset_saved', { name }));
  }

  // ------------------------------------------------------------------ macros
  const STEP_ICONS = { text: '#i-type', key: '#i-key', wait: '#i-clock', mouse_move: '#i-pointer', mouse_click: '#i-pointer', mouse_down: '#i-hand', mouse_up: '#i-hand', mouse_scroll: '#i-scroll', focus: '#i-window' };

  function newStep(kind) {
    const step = { kind };
    if (kind === 'text') step.text = '';
    if (kind === 'key') step.key = '';
    if (kind === 'wait') step.ms = 500;
    if (kind.startsWith('mouse')) { step.x = null; step.y = null; }
    if (kind === 'mouse_click' || kind === 'mouse_down' || kind === 'mouse_up') step.button = 'left';
    if (kind === 'mouse_click') step.count = 1;
    if (kind === 'mouse_scroll') { step.dx = 0; step.dy = -3; }
    if (kind === 'focus') step.title = '';
    return step;
  }

  function renderMacroList() {
    const list = $('#macro-list');
    list.innerHTML = '';
    if (!state.macros.length) {
      const empty = document.createElement('div');
      empty.className = 'pop-empty';
      empty.textContent = t('macros.none');
      list.appendChild(empty);
    }
    for (const macro of state.macros) {
      const item = document.createElement('button');
      item.className = 'macro-item' + (state.macroDraft && state.macroDraft.id === macro.id ? ' is-selected' : '');
      item.innerHTML = `<svg><use href="#i-zap"/></svg><span class="mi-text"><strong></strong><small></small></span><span class="badge hotkey" hidden></span>`;
      item.querySelector('strong').textContent = macro.name;
      item.querySelector('small').textContent = t('macros.steps_count', { count: macro.steps.length });
      if (macro.hotkey) { const b = item.querySelector('.badge'); b.textContent = formatCombo(macro.hotkey); b.hidden = false; }
      item.addEventListener('click', () => selectMacro(macro));
      list.appendChild(item);
    }
  }

  function selectMacro(macro) {
    state.macroDraft = JSON.parse(JSON.stringify(macro));
    state.macroDirty = false;
    renderMacroList();
    renderMacroEditor();
  }

  function newMacro() {
    state.macroDraft = { id: null, name: '', hotkey: '', repeat: 1, interval_ms: 0, steps: [] };
    state.macroDirty = true;
    renderMacroList();
    renderMacroEditor();
    $('#macro-name').focus();
  }

  function markMacroDirty() { state.macroDirty = true; $('#macro-status').hidden = false; }

  function renderMacroEditor() {
    const draft = state.macroDraft;
    $('#macro-empty').hidden = !!draft;
    $('#macro-form').hidden = !draft;
    if (!draft) return;
    $('#macro-name').value = draft.name;
    $('#macro-hotkey').value = formatCombo(draft.hotkey);
    $('#macro-repeat').value = draft.repeat;
    $('#macro-interval').value = draft.interval_ms;
    $('#macro-status').hidden = !state.macroDirty;
    $('#macro-delete').hidden = !draft.id;
    renderSteps();
    renderRecording();
  }

  function renderRecording() {
    const active = state.recording;
    $('#recording-banner').hidden = !active;
    $('#macro-record').classList.toggle('recording', active);
    $('#macro-record-label').textContent = active ? t('macros.record_stop') : t('macros.record');
    $('#recording-hint').textContent = t('macros.recording_hint', { combo: state.settings.hotkey_labels?.record || '' });
  }

  function stepField(step, field, cls, extra = '') {
    return `<input class="input ${cls}" data-field="${field}" ${extra} value="${escapeHtml(step[field] ?? '')}">`;
  }

  function renderSteps() {
    const list = $('#steps');
    list.innerHTML = '';
    const steps = state.macroDraft ? state.macroDraft.steps : [];
    if (!steps.length) {
      const empty = document.createElement('li');
      empty.className = 'empty';
      empty.textContent = t('macros.no_steps');
      list.appendChild(empty);
      return;
    }
    steps.forEach((step, index) => {
      const li = document.createElement('li');
      li.className = 'step';
      li.dataset.index = index;
      let fields = '';
      const num = (f, extra = '') => stepField(step, f, 'num', `type="number" ${extra}`);
      const point = () => `<span class="hint">x</span>${num('x')}<span class="hint">y</span>${num('y')}<button class="btn small act-pick" type="button"><svg><use href="#i-crosshair"/></svg></button>`;
      const buttonSelect = () => `<select class="input" data-field="button">${['left', 'right', 'middle'].map(b => `<option value="${b}" ${step.button === b ? 'selected' : ''}>${t('step.button.' + b)}</option>`).join('')}</select>`;
      switch (step.kind) {
        case 'text': fields = `<textarea class="input" data-field="text" rows="1" placeholder="${escapeHtml(t('step.text_placeholder'))}">${escapeHtml(step.text || '')}</textarea>`; break;
        case 'key': fields = `<input class="input hotkey-input" data-field="key" readonly placeholder="${escapeHtml(t('step.key_placeholder'))}" value="${escapeHtml(formatCombo(step.key))}">`; break;
        case 'wait': fields = `${num('ms', 'min="0" step="50"')}<span class="hint">${t('units.ms')}</span>`; break;
        case 'mouse_move': fields = point(); break;
        case 'mouse_click': fields = `${point()}${buttonSelect()}<select class="input" data-field="count">${[1, 2, 3].map(c => `<option value="${c}" ${step.count === c ? 'selected' : ''}>${t('step.count.' + c)}</option>`).join('')}</select>`; break;
        case 'mouse_down': case 'mouse_up': fields = `${point()}${buttonSelect()}`; break;
        case 'mouse_scroll': fields = `${point()}<span class="hint">dy</span>${num('dy', 'min="-100" max="100"')}<span class="hint">dx</span>${num('dx', 'min="-100" max="100"')}<span class="hint">${t('step.scroll_hint')}</span>`; break;
        case 'focus': fields = `<input class="input" data-field="title" placeholder="${escapeHtml(t('step.title_placeholder'))}" value="${escapeHtml(step.title || '')}">`; break;
      }
      li.innerHTML = `
        <span class="step-num">${index + 1}</span>
        <span class="step-kind"><svg><use href="${STEP_ICONS[step.kind]}"/></svg><span>${t('step.' + step.kind)}</span></span>
        <div class="step-fields">${fields}</div>
        <div class="step-actions">
          <button class="icon-btn small act-up" title="${t('step.up')}" ${index === 0 ? 'disabled' : ''}><svg><use href="#i-up"/></svg></button>
          <button class="icon-btn small act-down" title="${t('step.down')}" ${index === steps.length - 1 ? 'disabled' : ''}><svg><use href="#i-down"/></svg></button>
          <button class="icon-btn small act-remove" title="${t('step.remove')}"><svg><use href="#i-x"/></svg></button>
        </div>`;
      const keyInput = li.querySelector('.hotkey-input');
      if (keyInput) bindHotkeyInput(keyInput, combo => { step.key = combo; keyInput.value = formatCombo(combo); markMacroDirty(); });
      const textArea = li.querySelector('textarea');
      if (textArea) { const grow = () => { textArea.style.height = 'auto'; textArea.style.height = Math.min(120, textArea.scrollHeight + 2) + 'px'; }; textArea.addEventListener('input', grow); requestAnimationFrame(grow); }
      list.appendChild(li);
    });
  }

  function bindStepEvents() {
    const list = $('#steps');
    list.addEventListener('input', e => {
      const field = e.target.dataset.field;
      if (!field || field === 'key') return;
      const step = state.macroDraft.steps[Number(e.target.closest('.step').dataset.index)];
      if (e.target.type === 'number') { const v = e.target.value === '' ? null : Number(e.target.value); step[field] = Number.isFinite(v) ? v : null; }
      else if (field === 'count') step[field] = Number(e.target.value);
      else step[field] = e.target.value;
      markMacroDirty();
    });
    list.addEventListener('click', async e => {
      const btn = e.target.closest('button');
      if (!btn) return;
      const li = btn.closest('.step');
      const index = Number(li.dataset.index);
      const steps = state.macroDraft.steps;
      if (btn.classList.contains('act-remove')) { steps.splice(index, 1); markMacroDirty(); renderSteps(); }
      else if (btn.classList.contains('act-up') && index > 0) { [steps[index - 1], steps[index]] = [steps[index], steps[index - 1]]; markMacroDirty(); renderSteps(); }
      else if (btn.classList.contains('act-down') && index < steps.length - 1) { [steps[index + 1], steps[index]] = [steps[index], steps[index + 1]]; markMacroDirty(); renderSteps(); }
      else if (btn.classList.contains('act-pick')) {
        btn.disabled = true;
        const label = btn.querySelector('svg');
        for (let s = 3; s > 0; s--) { btn.textContent = String(s); await new Promise(r => setTimeout(r, 1000)); }
        btn.textContent = '';
        btn.appendChild(label);
        const result = await call('pick_point', 0);
        btn.disabled = false;
        if (!result.ok) return;
        steps[index].x = result.x; steps[index].y = result.y;
        li.querySelector('[data-field="x"]').value = result.x;
        li.querySelector('[data-field="y"]').value = result.y;
        markMacroDirty();
        toast('success', t('toast.point_picked', { x: result.x, y: result.y }));
      }
    });
  }

  function readMacroForm() {
    const draft = state.macroDraft;
    draft.name = $('#macro-name').value.trim();
    draft.repeat = Math.max(1, Number($('#macro-repeat').value) || 1);
    draft.interval_ms = Math.max(0, Number($('#macro-interval').value) || 0);
    return draft;
  }

  async function saveMacro() {
    const draft = readMacroForm();
    if (!draft.name) { toast('warn', t('macros.name_required')); $('#macro-name').focus(); return; }
    const result = await call('save_macro', draft);
    if (!result.ok) { reportFailure(result); return; }
    state.macros = result.macros;
    state.hotkeyErrors = result.hotkey_errors || {};
    state.macroDraft = JSON.parse(JSON.stringify(result.macro));
    state.macroDirty = false;
    renderMacroList();
    renderMacroEditor();
    reportHotkeyErrors();
    toast('success', t('toast.macro_saved', { name: draft.name }));
  }

  async function deleteMacro() {
    const draft = state.macroDraft;
    if (!draft || !draft.id) return;
    if (!(await confirmDialog(t('macros.confirm_delete', { name: draft.name }), '', true))) return;
    const result = await call('delete_macro', draft.id);
    if (!result.ok) return;
    state.macros = result.macros;
    state.macroDraft = null;
    renderMacroList();
    renderMacroEditor();
    toast('info', t('toast.macro_deleted'));
  }

  async function runMacro() {
    const draft = readMacroForm();
    if (!draft.steps.length) { toast('warn', t('notice.empty_macro')); return; }
    const result = await call('run_macro', draft, state.plan.settings, state.targetChoice, state.plan.countdown_s);
    if (!result.ok) reportFailure(result);
  }

  async function toggleRecording() {
    if (state.recording) { await call('record_stop'); return; }
    const btn = $('#macro-record');
    btn.disabled = true;
    const label = $('#macro-record-label');
    for (let s = 3; s > 0; s--) { label.textContent = `${s}…`; await new Promise(r => setTimeout(r, 1000)); }
    btn.disabled = false;
    const result = await call('record_start');
    if (!result.ok) { reportFailure(result); renderRecording(); }
  }

  // ------------------------------------------------------------------ settings view
  const HOTKEY_NAMES = ['start_pause', 'stop_reset', 'prev', 'next', 'record'];

  function renderHotkeys() {
    for (const name of HOTKEY_NAMES) {
      const input = $(`.hotkey-input[data-hotkey="${name}"]`);
      input.value = formatCombo(state.settings.hotkeys[name] || '');
      const status = $(`.hotkey-status[data-hotkey="${name}"]`);
      status.textContent = state.hotkeyErrors[name] ? t('hotkey.conflict') : '';
    }
    $$('input[name="language"]').forEach(r => { r.checked = r.value === state.settings.language; });
    $('#escape-stops').checked = !!state.settings.escape_stops;
    $('#data-dir').textContent = state.dataDir;
  }

  function reportHotkeyErrors() {
    for (const [name, message] of Object.entries(state.hotkeyErrors || {})) {
      let label = name;
      let combo = state.settings.hotkeys[name] || '';
      if (name.startsWith('macro:')) {
        const macro = state.macros.find(m => m.id === name.slice(6));
        label = macro ? macro.name : name;
        combo = macro ? macro.hotkey : '';
      } else label = t('hotkey.' + name);
      toast('warn', t('toast.hotkey_conflict', { combo: formatCombo(combo), name: label }) + (message ? '' : ''), 6000);
    }
  }

  // ------------------------------------------------------------------ init
  function bindUi() {
    $$('.rail-item').forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));
    $('#theme-toggle').addEventListener('click', () => saveSettings({ theme: effectiveTheme() === 'dark' ? 'light' : 'dark' }));
    $$('input[name="theme"]').forEach(r => r.addEventListener('change', () => saveSettings({ theme: r.value })));
    $$('input[name="language"]').forEach(r => r.addEventListener('change', async () => { await saveSettings({ language: r.value }); applyLanguage(); renderAll(); }));
    $('#escape-stops').addEventListener('change', e => saveSettings({ escape_stops: e.target.checked }));
    $('#open-folder').addEventListener('click', () => call('open_data_folder'));
    for (const name of HOTKEY_NAMES) {
      bindHotkeyInput($(`.hotkey-input[data-hotkey="${name}"]`), combo => {
        saveSettings({ hotkeys: { ...state.settings.hotkeys, [name]: combo } });
      }, { allowPlain: false });
    }

    bindPlanInputs();
    $('#btn-clear').addEventListener('click', () => { $('#text').value = ''; state.plan.text = ''; onPlanChanged(); $('#text').focus(); });
    $('#btn-start').addEventListener('click', startTyping);
    $('#btn-pause').addEventListener('click', () => call('toggle_pause'));
    $('#btn-stop').addEventListener('click', () => call('stop'));
    $('#btn-prev').addEventListener('click', () => step('prev'));
    $('#btn-next').addEventListener('click', () => step('next'));
    $('#countdown-stop').addEventListener('click', () => call('stop'));
    $('#btn-save-preset').addEventListener('click', savePresetFromCurrent);
    $('#target-pop').addEventListener('toggle', e => { if (e.newState === 'open') refreshWindowList(); });
    $('#target-refresh').addEventListener('click', refreshWindowList);

    $('#csv-load').addEventListener('click', loadCsv);
    $('#csv-remove').addEventListener('click', clearCsv);
    $('#csv-preview-toggle').addEventListener('click', () => { const box = $('#csv-preview'); box.hidden = !box.hidden; if (!box.hidden) renderCsvPreview(); });
    $('#csv-prev').addEventListener('click', () => { state.csvRow--; renderCsvPreview(); });
    $('#csv-next').addEventListener('click', () => { state.csvRow++; renderCsvPreview(); });
    $('#text').addEventListener('input', debounce(() => { if (!$('#csv-preview').hidden) renderCsvPreview(); }, 400));

    $('#preset-save').addEventListener('click', savePresetFromCurrent);
    $('#preset-export').addEventListener('click', async () => { const r = await call('export_presets'); if (r.ok) toast('success', t('toast.presets_exported')); else reportFailure(r); });
    $('#preset-import').addEventListener('click', async () => { const r = await call('import_presets'); if (r.ok) { state.presets = r.presets; renderPresets(); toast('success', t('toast.presets_imported', { count: r.imported })); } else reportFailure(r); });

    $('#macro-new').addEventListener('click', newMacro);
    $('#macro-name').addEventListener('input', markMacroDirty);
    $('#macro-repeat').addEventListener('input', markMacroDirty);
    $('#macro-interval').addEventListener('input', markMacroDirty);
    bindHotkeyInput($('#macro-hotkey'), combo => { state.macroDraft.hotkey = combo; $('#macro-hotkey').value = formatCombo(combo); markMacroDirty(); }, { allowPlain: false });
    $$('#step-menu button').forEach(b => b.addEventListener('click', () => {
      $('#step-menu').hidePopover();
      state.macroDraft.steps.push(newStep(b.dataset.kind));
      markMacroDirty();
      renderSteps();
      const last = $('#steps .step:last-child input, #steps .step:last-child textarea');
      if (last) last.focus();
    }));
    $('#macro-record').addEventListener('click', toggleRecording);
    $('#recording-stop').addEventListener('click', () => call('record_stop'));
    $('#macro-run').addEventListener('click', runMacro);
    $('#macro-save').addEventListener('click', saveMacro);
    $('#macro-delete').addEventListener('click', deleteMacro);
    bindStepEvents();

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && state.session.state !== 'idle') call('stop');
    });
  }

  function renderAll() {
    renderTarget();
    renderHotkeyHints();
    renderCsv();
    renderPresets();
    renderMacroList();
    renderMacroEditor();
    renderHotkeys();
    applySessionState();
    updateOutputs();
    scheduleEstimate();
  }

  async function init() {
    if (state.initialized) return;
    state.initialized = true;
    const result = await call('init');
    if (!result.ok) { state.initialized = false; return; }
    state.version = result.version;
    state.settings = Object.assign(state.settings, result.settings);
    state.hotkeyErrors = result.hotkey_errors || {};
    state.presets = result.presets || [];
    state.macros = result.macros || [];
    state.csv = result.csv;
    state.target = result.target;
    state.session = result.session || state.session;
    state.position = result.position || state.position;
    state.recording = !!result.recording;
    state.dataDir = result.data_dir || '';
    const draft = result.settings && result.settings.draft;
    if (draft && typeof draft === 'object') {
      const fresh = defaultPlan();
      state.plan = { ...fresh, ...draft, settings: { ...fresh.settings, ...(draft.settings || {}) }, text: String(draft.text || '') };
    }
    $('#version').textContent = 'v' + state.version;
    applyTheme();
    applyLanguage();
    applyPlan();
    renderAll();
    reportHotkeyErrors();
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindUi();
    applyLanguage();
    applyTheme();
    applyPlan();
    renderAll();
    if (window.pywebview && window.pywebview.api) init();
    else window.addEventListener('pywebviewready', init);
  });
})();
