import { api, decodeBinsB64 } from './api.js';
import { applyTranslations, getLang, setLang, t } from './i18n.js';
import { SpectrumCanvas } from './spectrum.js';
import { SweepCanvas } from './sweep.js';
import { WaterfallCanvas } from './waterfall.js';

const TABS = ['live', 'sweep', 'events'];
const THEME_MODES = ['auto', 'claro', 'noche'];
const FREQ_MIN_MHZ = 24;
const FREQ_MAX_MHZ = 1766;

const el = (id) => document.getElementById(id);

/** Build a DOM element; children are strings (as text, never HTML) or nodes. */
function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(props).forEach(([key, value]) => {
    if (value === null || value === undefined || value === false) return;
    if (key === 'class') node.className = value;
    else if (key === 'onclick') node.addEventListener('click', value);
    else node.setAttribute(key, value === true ? '' : String(value));
  });
  children.flat().forEach((child) => {
    if (child === null || child === undefined || child === false) return;
    node.append(child instanceof Node ? child : String(child));
  });
  return node;
}

const state = {
  current: null,
  themeIdx: (() => {
    try {
      return Math.max(0, THEME_MODES.indexOf(localStorage.getItem('ams-tema') || 'auto'));
    } catch {
      return 0;
    }
  })(),
  supportedGains: [0, 8.7, 14.4, 20.7, 29.7, 36.4, 42.1, 49.6],
  activeTab: 'live',
  wheelTargetMhz: null,
  wheelTimer: null,
  toastTimer: null,
  recentEvents: [],
  recordings: [],
  replay: null,
  seeking: false,
  inUseKey: null,
  lastLivePeaksRender: 0,
  lastEventsRefresh: 0,
  lastShownError: null,
  wsConnected: false,
  wsEverConnected: false,
  wsRetryMs: 1000,
};

// ---------------------------------------------------------------------------
// Feedback helpers
// ---------------------------------------------------------------------------

function showToast(message, level = 'info') {
  const toast = el('studio-toast');
  if (!message) return;
  toast.textContent = message;
  toast.classList.toggle('error', level === 'error');
  toast.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, level === 'error' ? 4500 : 2400);
}

/**
 * In-app confirmation pop-up (replaces window.confirm). Resolves true on confirm,
 * false on cancel, Escape or backdrop click. Focus starts on Cancel.
 */
function confirmDialog({ title, message, confirmLabel, danger = false }) {
  const dlg = el('confirm-dialog');
  el('confirm-title').textContent = title || t('confirm_title');
  el('confirm-message').textContent = message || '';
  el('confirm-cancel').textContent = t('confirm_cancel');
  const ok = el('confirm-ok');
  ok.textContent = confirmLabel || 'OK';
  ok.classList.toggle('is-danger', danger);
  ok.classList.toggle('ams-btn--principal', !danger);
  dlg.returnValue = '';
  return new Promise((resolve) => {
    dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok'), { once: true });
    dlg.showModal();
    el('confirm-cancel').focus();
  });
}

/** Run an API call that returns engine status; apply it or roll the controls back. */
async function applyCall(promise) {
  try {
    const st = await promise;
    applyStateToControls(st);
    return st;
  } catch (err) {
    showToast(err.message || 'Request failed', 'error');
    if (state.current) applyStateToControls(state.current);
    return null;
  }
}

function paintSliderProgress(input) {
  const min = parseFloat(input.min) || 0;
  const max = parseFloat(input.max) || 100;
  const val = parseFloat(input.value) || 0;
  const pct = max > min ? ((val - min) / (max - min)) * 100 : 0;
  input.style.setProperty('--v', `${pct}%`);
}

function setUnlessFocused(input, value) {
  if (input && document.activeElement !== input) input.value = String(value);
}

// ---------------------------------------------------------------------------
// Canvases
// ---------------------------------------------------------------------------

const waterfall = new WaterfallCanvas(el('waterfall-canvas'), el('waterfall-cursor'), {
  onHoverXChange: (x) => spectrum.setHoverX(x),
  onTuneFreqMhz: (freqMhz) => tuneFrequencyMhz(freqMhz),
  onWheelStep: (deltaMhz) => stepFrequencyMhz(deltaMhz),
});

const spectrum = new SpectrumCanvas(el('spectrum-canvas'), el('scope-hover'), el('scope-pan-badge'), {
  onTuneFreqMhz: (freqMhz) => tuneFrequencyMhz(freqMhz),
  onThresholdInput: (db) => {
    const slider = el('range-power-thresh');
    slider.value = String(db);
    paintSliderProgress(slider);
    el('val-power-thresh').textContent = `${Math.round(db)} dB`;
  },
  onThresholdCommit: (db) => applyCall(api.patchDetector({ power_threshold: db })),
  onHoverXChange: (x) => waterfall.setHoverX(x),
  onWheelStep: (deltaMhz) => stepFrequencyMhz(deltaMhz),
});

const sweepView = new SweepCanvas(el('sweep-canvas'), el('sweep-hover'), (freqMhz) => {
  switchTab('live');
  tuneFrequencyMhz(freqMhz);
});

// ---------------------------------------------------------------------------
// Theme & tabs
// ---------------------------------------------------------------------------

function updateThemeButton() {
  const mode = THEME_MODES[state.themeIdx];
  el('theme-icon').textContent = mode === 'claro' ? '☀' : mode === 'noche' ? '☾' : '◐';
}

function cycleTheme() {
  state.themeIdx = (state.themeIdx + 1) % THEME_MODES.length;
  const mode = THEME_MODES[state.themeIdx];
  if (mode === 'auto') delete document.documentElement.dataset.tema;
  else document.documentElement.dataset.tema = mode;
  try {
    localStorage.setItem('ams-tema', mode);
  } catch {
    // storage unavailable (private mode); theme still applies for this session
  }
  updateThemeButton();
}

function switchTab(tabName) {
  const tab = TABS.includes(tabName) ? tabName : 'live';
  state.activeTab = tab;
  document.querySelectorAll('.tab-link').forEach((a) => {
    if (a.dataset.tab === tab) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  TABS.forEach((name) => {
    el(`panel-${name}`).hidden = name !== tab;
  });
  if (location.hash !== `#${tab}`) history.replaceState(null, '', `#${tab}`);
  if (tab === 'live') {
    spectrum.resize();
    waterfall.resize();
  } else if (tab === 'sweep') {
    sweepView.resize();
  } else {
    refreshEventsTab();
  }
}

// ---------------------------------------------------------------------------
// Tuning
// ---------------------------------------------------------------------------

const clampFreqMhz = (mhz) => Math.min(FREQ_MAX_MHZ, Math.max(FREQ_MIN_MHZ, Number(mhz)));

function currentFreqMhz() {
  if (state.wheelTargetMhz !== null) return state.wheelTargetMhz;
  const rxFreq = state.current?.receiver?.frequency;
  return rxFreq ? rxFreq / 1e6 : 98.0;
}

function showFrequency(mhz) {
  setUnlessFocused(el('input-freq-mhz'), mhz.toFixed(3));
  document.querySelectorAll('.preset-btn').forEach((btn) => {
    btn.classList.toggle('active', Math.abs(parseFloat(btn.dataset.freq) - mhz) < 0.05);
  });
}

/** Step the frequency; rapid steps (wheel, arrows) are coalesced into one retune. */
function stepFrequencyMhz(deltaMhz) {
  if (state.current?.source_type === 'file') return;
  state.wheelTargetMhz = Number(clampFreqMhz(currentFreqMhz() + deltaMhz).toFixed(4));
  showFrequency(state.wheelTargetMhz);
  clearTimeout(state.wheelTimer);
  state.wheelTimer = setTimeout(() => {
    const target = state.wheelTargetMhz;
    state.wheelTargetMhz = null;
    if (target !== null) tuneFrequencyMhz(target);
  }, 90);
}

async function tuneFrequencyMhz(freqMhz) {
  if (!Number.isFinite(freqMhz) || freqMhz <= 0) return;
  const mhz = clampFreqMhz(freqMhz);
  state.wheelTargetMhz = null;
  clearTimeout(state.wheelTimer);
  showFrequency(mhz);
  if (await applyCall(api.patchReceiver({ frequency: Math.round(mhz * 1e6) }))) {
    waterfall.clear();
  }
}

function parseFreqInput(value) {
  return parseFloat(String(value).replace(',', '.'));
}

function nearestGain(val) {
  return state.supportedGains.reduce(
    (best, g) => (Math.abs(g - val) < Math.abs(best - val) ? g : best),
    state.supportedGains[0] ?? val,
  );
}

// ---------------------------------------------------------------------------
// State → controls
// ---------------------------------------------------------------------------

function sourceLabel(st) {
  const dev = st.device || {};
  if (st.source_type === 'usb') return `USB · ${dev.tuner && dev.tuner !== 'UNKNOWN' ? dev.tuner : 'RTL-SDR'}`;
  if (st.source_type === 'rtl_tcp') return `RTL-TCP · ${st.rtl_tcp?.host || '127.0.0.1'}`;
  if (st.source_type === 'simulated') return 'Demo RF';
  if (st.source_type === 'file') return `${t('rec_replaying')} · ${st.replay_file || t('src_file')}`;
  return st.source_type || 'RF';
}

function renderConnectionStatus() {
  const st = state.current || {};
  const engineState = st.state || 'idle';
  const chipDot = el('source-dot');
  const liveDot = el('live-dot');
  const badge = el('live-badge');
  chipDot.className = 'status-dot';
  liveDot.className = 'ams-punto';

  if (!state.wsConnected) {
    chipDot.classList.add('error');
    badge.textContent = t(state.wsEverConnected ? 'ws_offline' : 'ws_connecting');
    return;
  }
  if (engineState === 'running') {
    chipDot.classList.add(st.source_type === 'simulated' ? 'simulated' : 'running');
    liveDot.classList.add('ams-punto--directo');
  } else if (engineState === 'sweeping') {
    chipDot.classList.add('sweeping');
  } else if (engineState === 'error' || engineState === 'disconnected') {
    chipDot.classList.add('error');
  }
  const labels = {
    running: 'live_running',
    paused: 'live_paused',
    sweeping: 'live_sweeping',
    error: 'live_error',
    disconnected: 'live_error',
  };
  badge.textContent = t(labels[engineState] || 'live_waiting');
}

function applyStateToControls(st) {
  if (!st) return;
  state.current = st;
  const rx = st.receiver || {};
  const dsp = st.dsp || {};
  const det = st.detector || {};
  const dev = st.device || {};

  const gainSlider = el('range-gain');
  if (Array.isArray(dev.supported_gains) && dev.supported_gains.length > 0) {
    state.supportedGains = dev.supported_gains;
    gainSlider.min = String(state.supportedGains[0]);
    gainSlider.max = String(state.supportedGains[state.supportedGains.length - 1]);
  }

  renderConnectionStatus();
  el('source-label').textContent = sourceLabel(st);

  if (st.last_error && st.last_error !== state.lastShownError) {
    showToast(st.error_hint ? `${st.last_error} — ${st.error_hint}` : st.last_error, 'error');
  }
  state.lastShownError = st.last_error || null;

  const paused = st.state === 'paused';
  el('btn-pause').classList.toggle('active', paused);
  el('btn-pause').setAttribute('aria-pressed', String(paused));
  el('pause-label').textContent = t(paused ? 'btn_resume' : 'btn_pause');

  const replaying = st.source_type === 'file';
  document.querySelector('.first-section').classList.toggle('tune-locked', replaying);
  el('replay-note').hidden = !replaying;
  if (replaying) el('replay-note').textContent = t('replay_locked', { name: st.replay_file || '' });
  document.querySelectorAll('#seg-sample-rate input').forEach((inp) => {
    inp.disabled = replaying;
  });
  el('btn-sweep-start').title = replaying ? t('sweep_replay_blocked') : '';

  if (state.wheelTargetMhz === null) showFrequency((rx.frequency || 98e6) / 1e6);
  el('span-pill').textContent = `±${((rx.sample_rate || 2.048e6) / 2e6).toFixed(2)} MHz`;

  document.querySelectorAll('#seg-sample-rate input').forEach((inp) => {
    inp.checked = Math.abs(parseFloat(inp.value) - (rx.sample_rate || 0)) < 100;
  });
  document.querySelectorAll('#seg-fft-size input').forEach((inp) => {
    inp.checked = parseInt(inp.value, 10) === rx.fft_size;
  });

  const autoGain = rx.gain === null || rx.gain === undefined;
  el('chk-auto-gain').checked = autoGain;
  gainSlider.disabled = autoGain;
  if (!autoGain) gainSlider.value = String(rx.gain);
  el('val-gain').textContent = autoGain ? t('lbl_auto_gain') : `${Number(rx.gain).toFixed(1)} dB`;
  paintSliderProgress(gainSlider);

  if (dsp.averaging) el('select-averaging').value = String(dsp.averaging);
  if (dsp.window) el('select-window').value = dsp.window;
  el('chk-remove-dc').checked = dsp.remove_dc !== false;
  setUnlessFocused(el('input-ppm'), rx.ppm ?? 0);

  el('chk-detector-enabled').checked = det.enabled !== false;
  const pwrSlider = el('range-power-thresh');
  pwrSlider.value = String(det.power_threshold ?? -55);
  el('val-power-thresh').textContent = `${Math.round(Number(pwrSlider.value))} dB`;
  paintSliderProgress(pwrSlider);
  spectrum.setThreshold(Number(pwrSlider.value));

  const snrSlider = el('range-snr-thresh');
  snrSlider.value = String(det.snr_threshold ?? 10);
  el('val-snr-thresh').textContent = `${Math.round(Number(snrSlider.value))} dB`;
  paintSliderProgress(snrSlider);

  setUnlessFocused(el('input-bw-khz'), Math.round((det.bandwidth_threshold ?? 5000) / 1000));
  setUnlessFocused(el('input-min-dur'), det.min_duration ?? 0.2);
  setUnlessFocused(el('input-holdover'), det.holdover_seconds ?? 0.5);
  setUnlessFocused(el('input-cooldown'), det.cooldown_seconds ?? 2.0);

  updateRecordingUI(st.recording);
  if (Array.isArray(st.recordings)) setRecordings(st.recordings);
  syncRecordingsUsage();
  updateReplayBar(replaying ? st.replay : null, paused);
}

/**
 * Re-render recording rows whenever the file "in use" changes (recording or replay),
 * so delete buttons unlock as soon as a capture stops or the source changes.
 * A finished capture also refreshes the list to pick up its final size and metadata.
 */
function syncRecordingsUsage() {
  const st = state.current || {};
  const recording = st.recording?.filename || '';
  const replay = st.source_type === 'file' ? st.replay_file || '' : '';
  const key = `${recording}|${replay}`;
  if (key === state.inUseKey) return;
  const wasRecording = state.inUseKey?.split('|')[0];
  state.inUseKey = key;
  if (wasRecording && !recording) {
    refreshRecordings();
  } else {
    renderRecordingsList(state.recordings);
    if (el('source-dialog').open) renderDialogRecordings(state.recordings);
  }
}

// ---------------------------------------------------------------------------
// Recording
// ---------------------------------------------------------------------------

let lastFpsText = '0.0 fps';

function updateRecordingUI(recording) {
  const line = el('rec-status-line');
  el('btn-record').classList.toggle('recording', Boolean(recording));
  el('btn-record').setAttribute('aria-pressed', String(Boolean(recording)));
  el('rec-label').textContent = t(recording ? 'btn_stop_record' : 'btn_record');
  line.classList.toggle('recording-active', Boolean(recording));
  line.textContent = recording
    ? `REC · ${recording.filename} · ${Number(recording.duration_s || 0).toFixed(1)}s`
    : lastFpsText;
}

function formatBytes(bytes) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

const recordingUrl = (name) => `/api/recordings/${encodeURIComponent(name)}`;

function recordingInUse(name) {
  const st = state.current || {};
  return st.recording?.filename === name || (st.source_type === 'file' && st.replay_file === name);
}

function recordingMeta(rec) {
  const parts = [];
  if (rec.center_freq_hz) parts.push(`${(rec.center_freq_hz / 1e6).toFixed(3)} MHz`);
  if (rec.sample_rate_hz) parts.push(`${(rec.sample_rate_hz / 1e6).toFixed(3)} MSPS`);
  if (rec.duration_s != null) parts.push(`${rec.duration_s.toFixed(1)} s`);
  parts.push(formatBytes(rec.size_bytes));
  return parts.join(' · ');
}

function iconButton(symbol, label, onclick, extraClass = '') {
  return h('button', { type: 'button', class: `icon-btn ${extraClass}`, title: label, 'aria-label': label, onclick }, symbol);
}

function setRecordings(recordings) {
  state.recordings = recordings;
  renderRecordingsList(recordings);
  if (el('source-dialog').open) renderDialogRecordings(recordings);
}

async function refreshRecordings() {
  try {
    setRecordings((await api.listRecordings()).recordings || []);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function playRecording(name, button) {
  await switchSource({ mode: 'file', recording: name }, button);
  refreshRecordings();
}

async function deleteRecording(rec) {
  if (recordingInUse(rec.filename)) {
    showToast(t('rec_in_use'), 'error');
    return;
  }
  const confirmed = await confirmDialog({
    title: t('confirm_delete_title'),
    message: t('confirm_delete_msg', { name: rec.filename, size: formatBytes(rec.size_bytes) }),
    confirmLabel: t('confirm_delete_ok'),
    danger: true,
  });
  if (!confirmed) return;
  try {
    const res = await api.deleteRecording(rec.filename);
    setRecordings(res.recordings || []);
    showToast(`${t('rec_deleted')}: ${rec.filename}`);
  } catch (err) {
    showToast(err.message, 'error');
    refreshRecordings(); // file may have been moved or removed outside the app
  }
}

function renderRecordingsList(recordings) {
  el('recordings-box').hidden = recordings.length === 0;
  el('recordings-list').replaceChildren(
    ...recordings.slice(0, 3).map((rec) => {
      const inUse = recordingInUse(rec.filename);
      const del = iconButton('✕', t('rec_delete'), () => deleteRecording(rec), 'icon-btn--danger');
      del.disabled = inUse;
      return h(
        'div',
        { class: 'rec-row' },
        h(
          'a',
          { class: 'rec-link ams-mono', href: recordingUrl(rec.filename), download: rec.filename, title: `${t('rec_download')} · ${rec.filename}` },
          h('span', {}, rec.filename),
          h('span', {}, formatBytes(rec.size_bytes)),
        ),
        iconButton('▶', t('rec_play'), (e) => playRecording(rec.filename, e.currentTarget)),
        del,
      );
    }),
  );
}

function renderDialogRecordings(recordings) {
  const list = el('dialog-recordings-list');
  if (!recordings.length) {
    list.replaceChildren(h('p', { class: 'ams-gris small-note' }, t('rec_none')));
    return;
  }
  list.replaceChildren(
    ...recordings.map((rec) => {
      const st = state.current || {};
      const playing = st.source_type === 'file' && st.replay_file === rec.filename;
      const play = h('button', { type: 'button', class: 'ams-btn ams-btn--peq ams-btn--principal' }, t(playing ? 'rec_playing' : 'rec_play'));
      play.disabled = playing;
      play.addEventListener('click', () => playRecording(rec.filename, play));
      const del = iconButton('✕', t('rec_delete'), () => deleteRecording(rec), 'icon-btn--danger');
      del.disabled = recordingInUse(rec.filename);
      return h(
        'div',
        { class: `usb-item${playing ? ' is-active' : ''}` },
        h(
          'div',
          { class: 'rec-item-main' },
          h('strong', { title: rec.filename }, rec.filename),
          h('div', { class: 'ams-mono small-note ams-gris' }, recordingMeta(rec)),
        ),
        h(
          'div',
          { class: 'rec-item-actions' },
          play,
          h('a', { class: 'icon-btn', href: recordingUrl(rec.filename), download: rec.filename, title: t('rec_download'), 'aria-label': t('rec_download') }, '↓'),
          del,
        ),
      );
    }),
  );
}

async function toggleRecording() {
  const wasRecording = Boolean(state.current?.recording);
  try {
    const res = wasRecording ? await api.stopRecording() : await api.startRecording('raw');
    if (wasRecording && res?.recording) {
      showToast(`${t('rec_saved')}: ${res.recording.filename} (${formatBytes(res.recording.bytes)})`);
    } else if (!wasRecording) {
      showToast(t('rec_started'));
    }
    applyStateToControls(await api.getState());
  } catch (err) {
    showToast(err.message || 'Recording failed', 'error');
  }
}

// ---------------------------------------------------------------------------
// Replay transport
// ---------------------------------------------------------------------------

function fmtClock(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(1).padStart(4, '0')}`;
}

function updateReplayBar(replay, paused) {
  const bar = el('replay-bar');
  bar.hidden = !replay;
  if (!replay) return;
  state.replay = replay;
  el('replay-icon-pause').hidden = paused;
  el('replay-icon-play').hidden = !paused;
  const speed = el('replay-speed');
  if (document.activeElement !== speed) speed.value = String(replay.speed);
  if (state.seeking) return;
  const seek = el('replay-seek');
  const frac = replay.duration_s > 0 ? replay.position_s / replay.duration_s : 0;
  seek.value = String(Math.round(frac * 1000));
  paintSliderProgress(seek);
  el('replay-time').textContent = `${fmtClock(replay.position_s)} / ${fmtClock(replay.duration_s)}`;
  // Frames are shown 1-based; the API uses 0-based indices.
  setUnlessFocused(el('replay-frame'), replay.frame + 1);
  el('replay-frame').max = String(replay.frame_count);
  el('replay-frame-total').textContent = `/ ${replay.frame_count}`;
}

function goToFrame(oneBased) {
  if (state.current?.source_type !== 'file' || !state.replay) return;
  const count = state.replay.frame_count;
  const target = Math.min(count, Math.max(1, Math.round(Number(oneBased) || 1)));
  el('replay-frame').value = String(target);
  applyCall(api.patchReplay({ frame: target - 1 }));
}

function seekTargetSeconds() {
  const dur = state.replay?.duration_s || 0;
  return (Number(el('replay-seek').value) / 1000) * dur;
}

function stepReplay(direction) {
  if (state.current?.source_type !== 'file') return;
  applyCall(api.stepFrame(direction));
}

function restartReplay() {
  if (state.current?.source_type !== 'file') return;
  applyCall(api.patchReplay({ position_s: 0 }));
  waterfall.clear();
}

function bindReplayControls() {
  el('btn-replay-play').addEventListener('click', () => el('btn-pause').click());
  el('btn-replay-prev').addEventListener('click', () => stepReplay(-1));
  el('btn-replay-next').addEventListener('click', () => stepReplay(1));
  el('btn-replay-restart').addEventListener('click', restartReplay);

  const seek = el('replay-seek');
  seek.addEventListener('input', () => {
    state.seeking = true;
    paintSliderProgress(seek);
    el('replay-time').textContent = `${fmtClock(seekTargetSeconds())} / ${fmtClock(state.replay?.duration_s)}`;
  });
  seek.addEventListener('change', async () => {
    await applyCall(api.patchReplay({ position_s: seekTargetSeconds() }));
    state.seeking = false;
    waterfall.clear();
  });
  onChange('replay-speed', (sel) => applyCall(api.patchReplay({ speed: parseFloat(sel.value) })));

  const frameInput = el('replay-frame');
  frameInput.addEventListener('focus', () => frameInput.select());
  frameInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      goToFrame(frameInput.value);
      frameInput.blur();
    } else if (e.key === 'Escape') {
      frameInput.value = String((state.replay?.frame ?? 0) + 1);
      frameInput.blur();
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault();
      const delta = (e.key === 'ArrowUp' ? 1 : -1) * (e.shiftKey ? 10 : 1);
      goToFrame(Number(frameInput.value) + delta);
    }
  });
  frameInput.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault();
      goToFrame(Number(frameInput.value) + (e.deltaY < 0 ? 1 : -1));
    },
    { passive: false },
  );
}

// ---------------------------------------------------------------------------
// Signals / events
// ---------------------------------------------------------------------------

const fmtTime = (ts) => String(ts || '').slice(11, 19);

function renderSignalsList(items, isLivePeaks) {
  el('signals-heading').textContent = t(isLivePeaks ? 'sec_live_peaks' : 'sec_recent');
  const list = el('recent-events-list');
  if (!items || items.length === 0) {
    list.replaceChildren(h('p', { class: 'ams-gris small-empty' }, t('empty_events')));
    return;
  }
  list.replaceChildren(
    ...items.slice(0, 5).map((item) => {
      const freq = Number(item.frequency_mhz ?? item.frequency);
      const pwr = Number(item.power_db ?? item.power);
      const snr = Number(item.snr_db ?? item.snr ?? 0);
      const meta = isLivePeaks
        ? `${pwr.toFixed(1)} dBFS · +${snr.toFixed(0)} dB`
        : `${pwr.toFixed(1)} dB · ${fmtTime(item.timestamp)}`;
      return h(
        'button',
        { type: 'button', class: 'mini-event-row', onclick: () => tuneFrequencyMhz(freq) },
        h('span', { class: 'ams-mono' }, h('strong', {}, `${freq.toFixed(3)} MHz`)),
        h('span', { class: 'ams-mono ams-gris' }, meta),
      );
    }),
  );
}

function tuneRow(freqMhz, ...cells) {
  const row = h('tr', { class: 'clickable-row', tabindex: 0 }, ...cells);
  const go = () => {
    switchTab('live');
    tuneFrequencyMhz(freqMhz);
  };
  row.addEventListener('click', go);
  row.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') go();
  });
  return row;
}

function emptyRow(colspan, key) {
  return h('tr', {}, h('td', { colspan, class: 'ams-gris' }, t(key)));
}

function setEventsCount(n) {
  el('nav-events-count').textContent = String(n);
}

async function refreshEventsTab() {
  state.lastEventsRefresh = performance.now();
  try {
    const [evRes, stats] = await Promise.all([api.getEvents(100), api.getStats()]);
    const events = evRes.events || [];
    const live = stats.live || {};
    setEventsCount(stats.total_events ?? events.length);
    el('ev-stat-total').textContent = String(stats.total_events ?? events.length);
    el('ev-stat-frames').textContent = Number(live.total_frames ?? 0).toLocaleString();
    el('ev-stat-rate').textContent = `${((live.detection_rate || 0) * 100).toFixed(1)}%`;
    el('ev-stat-peak').textContent =
      Number.isFinite(live.peak_power) && live.peak_power > -200
        ? `${Number(live.peak_power).toFixed(1)} dBFS`
        : '—';

    const top = stats.top_frequencies || [];
    el('top-freqs-tbody').replaceChildren(
      ...(top.length === 0
        ? [emptyRow(4, 'empty_history')]
        : top.map((row) =>
            tuneRow(
              Number(row.frequency_mhz),
              h('td', { class: 'ams-mono' }, h('strong', {}, Number(row.frequency_mhz).toFixed(3))),
              h('td', { class: 'ams-num' }, row.count),
              h('td', { class: 'ams-num' }, Number(row.avg_power).toFixed(1)),
              h('td', { class: 'ams-num' }, Number(row.max_power).toFixed(1)),
            ),
          )),
    );

    el('events-tbody').replaceChildren(
      ...(events.length === 0
        ? [emptyRow(6, 'empty_history')]
        : events.map((e) =>
            tuneRow(
              Number(e.frequency_mhz),
              h('td', { class: 'ams-mono' }, fmtTime(e.timestamp)),
              h('td', { class: 'ams-mono' }, h('strong', {}, Number(e.frequency_mhz).toFixed(3))),
              h('td', { class: 'ams-num' }, Number(e.power_db).toFixed(1)),
              h('td', { class: 'ams-num' }, e.snr == null ? '—' : Number(e.snr).toFixed(1)),
              h('td', { class: 'ams-num' }, (Number(e.bandwidth_hz) / 1000).toFixed(1)),
              h('td', { class: 'ams-num' }, `${Number(e.duration_s).toFixed(2)}s`),
            ),
          )),
    );
  } catch (err) {
    showToast(err.message || 'Failed loading events', 'error');
  }
}

function onLiveEvent(ev) {
  state.recentEvents.unshift(ev);
  state.recentEvents.length = Math.min(state.recentEvents.length, 5);
  renderSignalsList(state.recentEvents, false);
  setEventsCount((parseInt(el('nav-events-count').textContent, 10) || 0) + 1);
  if (state.activeTab === 'events' && performance.now() - state.lastEventsRefresh > 1000) {
    refreshEventsTab();
  }
}

// ---------------------------------------------------------------------------
// Sweep
// ---------------------------------------------------------------------------

function setSweepRunning(running) {
  el('btn-sweep-start').disabled = running;
  el('btn-sweep-cancel').hidden = !running;
  el('sweep-progress-wrap').hidden = !running;
}

function showSweepError(message) {
  setSweepRunning(false);
  el('sweep-error-text').textContent = message;
  el('sweep-error-banner').hidden = false;
}

function updateSweepProgress(prog) {
  if (!prog) return;
  setSweepRunning(prog.running !== false);
  el('sweep-progress-fill').style.width = `${prog.percent || 0}%`;
  el('sweep-progress-text').textContent =
    `${prog.step_index}/${prog.total_steps} · ${Number(prog.current_freq_mhz).toFixed(2)} MHz · ${prog.peaks_found} ${t('peaks_unit')}`;
}

function renderSweepResult(res) {
  setSweepRunning(false);
  el('sweep-error-banner').hidden = true;
  sweepView.setResult(res);
  if (!res) return;

  const suffix = res.cancelled ? ` · ${t('sweep_cancelled')}` : '';
  el('sweep-summary-pill').textContent =
    `${res.start_freq_mhz.toFixed(1)}–${res.end_freq_mhz.toFixed(1)} MHz · ${res.peaks.length} ${t('peaks_unit')} · ${res.duration_s}s${suffix}`;

  el('sweep-peaks-tbody').replaceChildren(
    ...(res.peaks.length === 0
      ? [emptyRow(3, 'sweep_no_peaks')]
      : res.peaks.map((pk) =>
          tuneRow(
            pk.frequency_mhz,
            h('td', { class: 'ams-mono' }, h('strong', {}, pk.frequency_mhz.toFixed(3))),
            h('td', { class: 'ams-num' }, pk.power_db.toFixed(1)),
            h('td', { class: 'ams-num' }, `+${pk.snr_db.toFixed(1)}`),
          ),
        )),
  );
}

function applySweepStatus(sw) {
  if (!sw) return;
  if (sw.running) updateSweepProgress(sw.progress);
  else if (sw.error) showSweepError(sw.error);
  else if (sw.result) renderSweepResult(sw.result);
  else setSweepRunning(false);
}

async function startSweep() {
  const startMhz = parseFreqInput(el('sweep-start-mhz').value);
  const endMhz = parseFreqInput(el('sweep-end-mhz').value);
  const dwell = parseFloat(el('sweep-dwell').value) || 0.3;
  el('sweep-error-banner').hidden = true;
  if (state.current?.source_type === 'file') {
    showSweepError(t('sweep_replay_blocked'));
    return;
  }
  if (!Number.isFinite(startMhz) || !Number.isFinite(endMhz) || endMhz <= startMhz) {
    showSweepError(t('sweep_invalid'));
    return;
  }
  setSweepRunning(true);
  el('sweep-progress-fill').style.width = '0%';
  try {
    const res = await api.startSweep({
      start_freq_hz: startMhz * 1e6,
      end_freq_hz: endMhz * 1e6,
      dwell_seconds: dwell,
    });
    updateSweepProgress(res.progress);
  } catch (err) {
    showSweepError(err.message);
  }
}

// ---------------------------------------------------------------------------
// Source dialog
// ---------------------------------------------------------------------------

function sourceDialogError(message) {
  const box = el('source-dialog-error');
  box.textContent = message || '';
  box.hidden = !message;
}

async function switchSource(body, button) {
  sourceDialogError(null);
  if (button) button.disabled = true;
  try {
    applyStateToControls(await api.switchSource(body));
    waterfall.clear();
    el('source-dialog').close();
  } catch (err) {
    sourceDialogError(err.message);
  } finally {
    if (button) button.disabled = false;
  }
}

async function scanUsbDevices() {
  const list = el('usb-devices-list');
  list.replaceChildren(h('p', { class: 'ams-gris small-note' }, t('usb_scanning')));
  try {
    const diag = await api.getDevices();
    if (!diag.devices || diag.devices.length === 0) {
      const msg = diag.library_found ? t('usb_none') : diag.message || t('usb_none');
      list.replaceChildren(h('p', { class: 'ams-gris small-note' }, msg));
      return;
    }
    list.replaceChildren(
      ...diag.devices.map((dev) => {
        const meta = [`#${dev.index}`];
        if (dev.tuner && dev.tuner !== 'UNKNOWN') meta.push(dev.tuner);
        if (dev.manufacturer) meta.push(dev.manufacturer);
        if (dev.serial) meta.push(dev.serial);
        const button = h('button', { type: 'button', class: 'ams-btn ams-btn--peq ams-btn--principal' }, t('use_device'));
        button.addEventListener('click', () => switchSource({ mode: 'usb', device_index: dev.index }, button));
        return h(
          'div',
          { class: 'usb-item' },
          h(
            'div',
            {},
            h('strong', {}, dev.name),
            ' ',
            dev.connected
              ? h('span', { class: 'ams-etiqueta ams-etiqueta--ok' }, h('span', { class: 'ams-punto ams-punto--ok' }), t('live_running'))
              : null,
            h('div', { class: 'ams-mono small-note ams-gris' }, meta.join(' · ')),
          ),
          button,
        );
      }),
    );
  } catch (err) {
    list.replaceChildren(h('p', { class: 'ams-mal small-note' }, err.message));
  }
}

// ---------------------------------------------------------------------------
// WebSocket stream
// ---------------------------------------------------------------------------

function handleFrame(data) {
  const bins = decodeBinsB64(data.bins_b64);
  spectrum.updateFrame(data, bins);
  waterfall.setAxis(data.freqs_start_mhz, data.freqs_step_mhz, bins.length);
  waterfall.pushRow(bins, spectrum.minDb, spectrum.maxDb);

  el('tel-peak-freq').textContent = `${Number(data.peak_freq_mhz).toFixed(3)} MHz`;
  el('tel-peak-power').textContent = `${Number(data.peak_power_db).toFixed(1)} dBFS`;
  el('tel-noise').textContent = `${Number(data.noise_floor_db).toFixed(1)} dBFS`;
  el('tel-snr').textContent = `+${Number(data.peak_snr_db).toFixed(1)} dB`;

  lastFpsText = `${Number(data.fps).toFixed(1)} fps`;
  if (state.current) state.current.recording = data.recording;
  updateRecordingUI(data.recording);
  syncRecordingsUsage();
  if (data.replay) updateReplayBar(data.replay, state.current?.state === 'paused');

  if (data.event) {
    onLiveEvent(data.event);
  } else if (state.recentEvents.length === 0 && Array.isArray(data.peaks)) {
    const now = performance.now();
    if (now - state.lastLivePeaksRender > 420) {
      state.lastLivePeaksRender = now;
      renderSignalsList(data.peaks, true);
    }
  }
}

const WS_HANDLERS = {
  status: (d) => applyStateToControls(d.status),
  frame: handleFrame,
  sweep_progress: (d) => updateSweepProgress(d.progress),
  sweep_result: (d) => renderSweepResult(d.result),
  sweep_error: (d) => showSweepError(d.error || 'Sweep failed'),
};

function connectWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/spectrum`);

  ws.onopen = () => {
    state.wsConnected = true;
    state.wsEverConnected = true;
    state.wsRetryMs = 1000;
    renderConnectionStatus();
    // Catch up on anything missed while disconnected (e.g. a sweep that finished).
    api.getSweep().then(applySweepStatus).catch(() => {});
  };

  ws.onmessage = (msg) => {
    let data;
    try {
      data = JSON.parse(msg.data);
    } catch {
      return;
    }
    WS_HANDLERS[data.type]?.(data);
  };

  ws.onclose = () => {
    if (state.wsConnected) {
      state.wsConnected = false;
      renderConnectionStatus();
    }
    setTimeout(connectWebSocket, state.wsRetryMs);
    state.wsRetryMs = Math.min(state.wsRetryMs * 2, 8000);
  };
}

// ---------------------------------------------------------------------------
// UI bindings
// ---------------------------------------------------------------------------

function onChange(id, handler) {
  el(id).addEventListener('change', (e) => handler(e.target));
}

function bindNumberToDetector(id, field, scale = 1) {
  onChange(id, (input) => {
    const value = Math.max(0, parseFloat(input.value) || 0);
    applyCall(api.patchDetector({ [field]: value * scale }));
  });
}

function bindUIEvents() {
  document.querySelectorAll('.tab-link').forEach((link) => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      switchTab(link.dataset.tab);
    });
  });
  el('brand-home').addEventListener('click', (e) => {
    e.preventDefault();
    switchTab('live');
  });
  el('btn-view-all-events').addEventListener('click', () => switchTab('events'));
  window.addEventListener('hashchange', () => switchTab(location.hash.slice(1)));

  el('btn-lang').addEventListener('click', () => {
    setLang(getLang() === 'en' ? 'es' : 'en');
    if (state.current) applyStateToControls(state.current);
    renderSignalsList(state.recentEvents, false);
    if (state.activeTab === 'events') refreshEventsTab();
  });
  el('btn-theme').addEventListener('click', cycleTheme);

  // Scope actions
  el('btn-pause').addEventListener('click', () => {
    const paused = state.current?.state === 'paused';
    applyCall((paused ? api.resumeStream() : api.pauseStream()).then(() => api.getState()));
  });
  el('btn-peak-hold').addEventListener('click', () => {
    const next = !spectrum.peakHold;
    spectrum.setPeakHold(next);
    el('btn-peak-hold').setAttribute('aria-pressed', String(next));
    el('btn-reset-peak').hidden = !next;
  });
  el('btn-reset-peak').addEventListener('click', () => spectrum.resetPeak());
  el('btn-autorange').addEventListener('click', () => spectrum.triggerAutoScale());
  el('btn-record').addEventListener('click', toggleRecording);

  // Tuning
  const freqInput = el('input-freq-mhz');
  freqInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') freqInput.blur();
    else if (e.key === 'Escape') {
      freqInput.value = currentFreqMhz().toFixed(3);
      freqInput.blur();
    }
  });
  freqInput.addEventListener('focus', () => freqInput.select());
  freqInput.addEventListener('blur', () => {
    const parsed = parseFreqInput(freqInput.value);
    if (Number.isFinite(parsed) && Math.abs(parsed - currentFreqMhz()) > 0.0005) tuneFrequencyMhz(parsed);
    else freqInput.value = currentFreqMhz().toFixed(3);
  });
  freqInput.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault();
      const step = e.shiftKey ? 1.0 : e.altKey ? 0.01 : 0.1;
      stepFrequencyMhz((e.deltaY < 0 ? 1 : -1) * step);
    },
    { passive: false },
  );
  [
    ['btn-freq-down-big', -1.0],
    ['btn-freq-down', -0.1],
    ['btn-freq-up', 0.1],
    ['btn-freq-up-big', 1.0],
  ].forEach(([id, delta]) => el(id).addEventListener('click', () => stepFrequencyMhz(delta)));
  document.querySelectorAll('.preset-btn').forEach((btn) => {
    btn.addEventListener('click', () => tuneFrequencyMhz(parseFloat(btn.dataset.freq)));
  });

  // Receiver
  document.querySelectorAll('#seg-sample-rate input').forEach((inp) => {
    inp.addEventListener('change', async () => {
      if (await applyCall(api.patchReceiver({ sample_rate: parseFloat(inp.value) }))) waterfall.clear();
    });
  });
  document.querySelectorAll('#seg-fft-size input').forEach((inp) => {
    inp.addEventListener('change', async () => {
      if (await applyCall(api.patchReceiver({ fft_size: parseInt(inp.value, 10) }))) waterfall.clear();
    });
  });
  onChange('chk-auto-gain', (chk) => {
    const gain = chk.checked ? null : nearestGain(parseFloat(el('range-gain').value));
    applyCall(api.patchReceiver({ gain }));
  });
  el('range-gain').addEventListener('input', (e) => {
    el('val-gain').textContent = `${nearestGain(parseFloat(e.target.value)).toFixed(1)} dB`;
    paintSliderProgress(e.target);
  });
  onChange('range-gain', (input) => applyCall(api.patchReceiver({ gain: nearestGain(parseFloat(input.value)) })));
  onChange('input-ppm', (input) => {
    const ppm = Math.max(-500, Math.min(500, parseInt(input.value, 10) || 0));
    applyCall(api.patchReceiver({ ppm }));
  });

  // Detector
  onChange('chk-detector-enabled', (chk) => applyCall(api.patchDetector({ enabled: chk.checked })));
  el('range-power-thresh').addEventListener('input', (e) => {
    const val = parseFloat(e.target.value);
    el('val-power-thresh').textContent = `${Math.round(val)} dB`;
    paintSliderProgress(e.target);
    spectrum.setThreshold(val);
  });
  onChange('range-power-thresh', (input) =>
    applyCall(api.patchDetector({ power_threshold: parseFloat(input.value) })),
  );
  el('range-snr-thresh').addEventListener('input', (e) => {
    el('val-snr-thresh').textContent = `${Math.round(parseFloat(e.target.value))} dB`;
    paintSliderProgress(e.target);
  });
  onChange('range-snr-thresh', (input) =>
    applyCall(api.patchDetector({ snr_threshold: parseFloat(input.value) })),
  );
  bindNumberToDetector('input-bw-khz', 'bandwidth_threshold', 1000);
  bindNumberToDetector('input-min-dur', 'min_duration');
  bindNumberToDetector('input-holdover', 'holdover_seconds');
  bindNumberToDetector('input-cooldown', 'cooldown_seconds');

  // Settings dialog (DSP)
  el('btn-open-settings').addEventListener('click', () => el('settings-dialog').showModal());
  el('btn-close-settings').addEventListener('click', () => el('settings-dialog').close());
  onChange('select-averaging', (s) => applyCall(api.patchDsp({ averaging: parseInt(s.value, 10) })));
  onChange('select-window', (s) => applyCall(api.patchDsp({ window: s.value })));
  onChange('chk-remove-dc', (chk) => applyCall(api.patchDsp({ remove_dc: chk.checked })));
  onChange('select-colormap', (s) => {
    waterfall.setColormap(s.value);
    try {
      localStorage.setItem('ams-colormap', s.value);
    } catch {
      // non-persistent preference is fine
    }
  });

  // Close dialogs when clicking the backdrop
  document.querySelectorAll('dialog').forEach((dlg) => {
    dlg.addEventListener('click', (e) => {
      if (e.target !== dlg) return;
      const r = dlg.getBoundingClientRect();
      const inside = e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
      if (!inside) dlg.close();
    });
  });

  // Source dialog
  el('btn-open-source').addEventListener('click', () => {
    sourceDialogError(null);
    el('source-dialog').showModal();
    scanUsbDevices();
    renderDialogRecordings(state.recordings || []);
    refreshRecordings();
  });
  el('btn-close-source').addEventListener('click', () => el('source-dialog').close());
  el('btn-scan-usb').addEventListener('click', scanUsbDevices);
  el('btn-connect-tcp').addEventListener('click', (e) => {
    const host = el('input-tcp-host').value.trim() || '127.0.0.1';
    const port = parseInt(el('input-tcp-port').value, 10) || 1234;
    switchSource({ mode: 'rtl_tcp', tcp_host: host, tcp_port: port }, e.currentTarget);
  });
  el('btn-connect-sim').addEventListener('click', (e) => switchSource({ mode: 'simulated' }, e.currentTarget));

  // Sweep
  document.querySelectorAll('.sweep-preset').forEach((btn) => {
    btn.addEventListener('click', () => {
      el('sweep-start-mhz').value = btn.dataset.start;
      el('sweep-end-mhz').value = btn.dataset.end;
    });
  });
  el('btn-sweep-error-close').addEventListener('click', () => {
    el('sweep-error-banner').hidden = true;
  });
  el('btn-sweep-start').addEventListener('click', startSweep);
  ['sweep-start-mhz', 'sweep-end-mhz', 'sweep-dwell'].forEach((id) => {
    el(id).addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !el('btn-sweep-start').disabled) startSweep();
    });
  });
  el('btn-sweep-cancel').addEventListener('click', () => api.cancelSweep().catch(() => {}));

  // Events
  el('btn-clear-events').addEventListener('click', async () => {
    const confirmed = await confirmDialog({
      title: t('confirm_clear_title'),
      message: t('confirm_clear'),
      confirmLabel: t('confirm_clear_ok'),
      danger: true,
    });
    if (!confirmed) return;
    try {
      await api.clearEvents();
      state.recentEvents = [];
      renderSignalsList([], false);
      refreshEventsTab();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  // Keyboard shortcuts (ignored while typing or with a dialog open)
  window.addEventListener('keydown', (e) => {
    const tag = e.target?.tagName || '';
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(tag) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (document.querySelector('dialog[open]')) return;
    const key = e.key.toLowerCase();
    if (e.code === 'Space') {
      e.preventDefault();
      el('btn-pause').click();
    } else if (key === 'p') el('btn-peak-hold').click();
    else if (key === 'r') el('btn-record').click();
    else if (key === 'a') spectrum.triggerAutoScale();
    else if (e.key === ',') stepReplay(-1);
    else if (e.key === '.') stepReplay(1);
    else if (e.key === 'Home') restartReplay();
    else if (['1', '2', '3'].includes(key)) switchTab(TABS[Number(key) - 1]);
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      const dir = e.key === 'ArrowRight' ? 1 : -1;
      stepFrequencyMhz(dir * (e.shiftKey ? 1.0 : 0.1));
    }
  });
}

async function init() {
  applyTranslations();
  updateThemeButton();
  try {
    const savedMap = localStorage.getItem('ams-colormap');
    if (savedMap) {
      el('select-colormap').value = savedMap;
      waterfall.setColormap(savedMap);
    }
  } catch {
    // ignore
  }
  bindUIEvents();
  bindReplayControls();
  switchTab(location.hash.slice(1) || 'live');

  try {
    const [st, ev] = await Promise.all([api.getState(), api.getEvents(5)]);
    applyStateToControls(st);
    if (ev.events?.length) {
      state.recentEvents = ev.events.slice(0, 5);
      renderSignalsList(state.recentEvents, false);
    }
    api.getStats().then((s) => setEventsCount(s.total_events ?? 0)).catch(() => {});
  } catch (err) {
    showToast(err.message || 'Failed loading state', 'error');
  }
  connectWebSocket();
}

init();
