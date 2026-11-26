// Kiosk shell: owns the single `/ws/status` WebSocket connection, the
// shared run-status state, the global header chrome (connection
// indicator, Home button, compact status pill, paused-run banner), and the
// tab switcher (issue #25).
//
// Page modules (run.js, tips.js) register themselves via `App.registerPage`
// and read run-status updates via `App.onStatus` instead of
// touching the WebSocket directly -- the shell is the one thing guaranteed
// to be alive regardless of which tab is active, so it's the one thing that
// owns the connection. Client-side view switching only (never a full page
// navigation): a real navigation would drop and re-establish this socket
// mid-run, which is unacceptable (see CLAUDE.md).
const App = (() => {
  let ws = null;
  let status = { status: 'idle', message: '', paused: false };
  const statusListeners = [];

  // ── shared run-status state ──────────────────────────────────────────────
  function onStatus(fn) {
    statusListeners.push(fn);
    fn(status); // deliver the current snapshot immediately to late subscribers
  }

  function setStatus(data) {
    status = data;
    statusListeners.forEach(fn => fn(status));
    renderStatusPill();
    renderBreakpointBanner();
  }

  function getStatus() {
    return status;
  }

  // Shared label/icon for a run-status value -- the one place both the
  // compact pill (below) and run.js's detailed card derive their text from,
  // instead of each keeping its own capitalize expression / icon map.
  const STATUS_LABELS = { idle: 'Idle', running: 'Running', done: 'Done', error: 'Error' };
  const STATUS_ICONS = { idle: '○', running: '◌', done: '✓', error: '✕' };

  function describeStatus(s) {
    return {
      label: STATUS_LABELS[s] || 'Unknown',
      icon: STATUS_ICONS[s] || '○',
    };
  }

  // Shared "is a run currently active" predicate -- the boolean counterpart
  // to describeStatus above, replacing raw `=== 'running'` comparisons
  // scattered across run.js/tips.js (issue #83).
  function isRunActive(s) {
    return s === 'running';
  }

  // ── WebSocket connection ────────────────────────────────────────────────
  // Pure: given the socket lifecycle event, the connection indicator's
  // label and whether it counts as "live" -- the one thing onopen/onclose
  // (below) agree on, instead of each writing the DOM its own way.
  function wsState(eventType) {
    return eventType === 'open'
      ? { label: 'live', live: true }
      : { label: 'reconnecting', live: false };
  }

  function renderConnIndicator(eventType) {
    const state = wsState(eventType);
    document.getElementById('connDot').classList.toggle('live', state.live);
    document.getElementById('connLabel').textContent = state.label;
  }

  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/status`);

    ws.onopen = () => renderConnIndicator('open');

    ws.onmessage = e => setStatus(JSON.parse(e.data));

    ws.onclose = () => {
      renderConnIndicator('close');
      setTimeout(connectWS, 2000);
    };
  }

  // ── compact global status pill ──────────────────────────────────────────
  // Outside a run it also shows a failed immediate job (e.g. a Home that
  // Klipper cancelled), with Klipper's message (issue #187).
  function renderStatusPill() {
    const pill  = document.getElementById('statusPill');
    const label = document.getElementById('statusPillLabel');
    const s = status.status || 'idle';
    const job = status.last_job;
    const failed = !isRunActive(s) && job && job.state !== 'completed';
    pill.className = `status-pill ${failed ? 'error' : s}`;
    label.textContent = failed
      ? (job.message || `Job ${job.state}`)
      : describeStatus(s).label;
    pill.title = failed ? `${job.filename} ${job.state}: ${job.message}` : '';
  }

  // ── global paused-run banner ────────────────────────────────────────────
  // Klipper has the print paused (a `break` line, or an empty tipbox); the
  // message is the reason. Beeps once per new pause so an operator across
  // the room notices (Scott's c5e549e).
  let lastPause = null;

  function renderBreakpointBanner() {
    const banner = document.getElementById('breakpointBanner');
    const paused = status.status === 'running' && !!status.paused;
    banner.classList.toggle('active', paused);
    if (!paused) {
      lastPause = null;
      return;
    }
    document.getElementById('breakpointMsg').textContent = status.message || '';
    if (status.message !== lastPause) {
      lastPause = status.message;
      beep();
    }
  }

  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.25, 0.5].forEach((offset) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = 880;
        const t = ctx.currentTime + offset;
        gain.gain.setValueAtTime(0.4, t);
        gain.gain.exponentialRampToValueAtTime(0.001, t + 0.18);
        osc.start(t);
        osc.stop(t + 0.18);
      });
    } catch (e) {
      // No audio on this device: the banner alone has to do.
    }
  }

  async function runControl(path) {
    const buttons = ['pauseResumeBtn', 'pauseCancelBtn'].map((id) => document.getElementById(id));
    buttons.forEach((b) => { b.disabled = true; });
    try {
      await fetch(path, { method: 'POST' });
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
    }
  }

  // ── home button (global: relevant regardless of active tab) ────────────
  async function home() {
    const btn = document.getElementById('homeBtn');
    const feedback = document.getElementById('homeFeedback');
    btn.disabled = true;
    feedback.classList.remove('error');
    feedback.textContent = 'Homing…';
    try {
      const res = await fetch('/home', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) {
        feedback.classList.add('error');
        feedback.textContent = data.detail || 'Homing failed';
      } else {
        feedback.textContent = data.message || 'Homing dispatched';
      }
    } catch (e) {
      feedback.classList.add('error');
      feedback.textContent = e.message;
    } finally {
      btn.disabled = false;
      setTimeout(() => { feedback.textContent = ''; }, 6000);
    }
  }

  // ── tab switcher: a small data-driven registry, not hardcoded branches,
  // so a future page (Move/Deck/Verify) is an addition here, not a rewrite
  // of the switcher itself (issue #25). Page modules opt into lifecycle
  // hooks by calling registerPage; a page with no hooks (e.g. Run, which
  // only ever needs the shared status stream) just never registers one. ──
  const pages = {}; // id -> { onShow, onHide }
  let activePage = null;

  function registerPage(id, hooks) {
    pages[id] = hooks || {};
  }

  function switchTo(id) {
    if (id === activePage) return;
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.page === id);
    });
    document.querySelectorAll('.page').forEach(page => {
      page.classList.toggle('active', page.id === `page-${id}`);
    });
    const prev = activePage;
    activePage = id;
    if (prev && pages[prev] && pages[prev].onHide) pages[prev].onHide();
    if (pages[id] && pages[id].onShow) pages[id].onShow();
  }

  function initTabBar() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => switchTo(btn.dataset.page));
    });
    // Whichever page's markup already carries `active` (always "run" -- a
    // full reload intentionally always lands on Run, never a persisted
    // tab, per issue #25) is the starting page; fire its onShow too.
    const initial = document.querySelector('.tab-btn.active');
    activePage = initial ? initial.dataset.page : null;
    if (activePage && pages[activePage] && pages[activePage].onShow) {
      pages[activePage].onShow();
    }
  }

  // ── init ─────────────────────────────────────────────────────────────
  function init() {
    document.getElementById('homeBtn').addEventListener('click', home);
    document.getElementById('pauseResumeBtn').addEventListener('click', () => runControl('/run/resume'));
    document.getElementById('pauseCancelBtn').addEventListener('click', () => runControl('/run/cancel'));
    initTabBar();
    connectWS();
  }

  document.addEventListener('DOMContentLoaded', init);

  return { onStatus, getStatus, registerPage, switchTo, describeStatus, isRunActive };
})();
