// Kiosk shell: owns the single `/ws/status` WebSocket connection, the
// shared run-status/breakpoint state, the global header chrome (connection
// indicator, Home button, compact status pill, breakpoint banner), and the
// tab switcher (issue #25).
//
// Page modules (run.js, tips.js) register themselves via `App.registerPage`
// and read run-status/breakpoint updates via `App.onStatus` instead of
// touching the WebSocket directly -- the shell is the one thing guaranteed
// to be alive regardless of which tab is active, so it's the one thing that
// owns the connection. Client-side view switching only (never a full page
// navigation): a real navigation would drop and re-establish this socket
// mid-run, which is unacceptable (see CLAUDE.md).
const App = (() => {
  let ws = null;
  let status = { status: 'idle', message: '', breakpoint: null };
  const statusListeners = [];

  // ── shared run-status/breakpoint state ──────────────────────────────────
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

  // ── WebSocket connection ────────────────────────────────────────────────
  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/status`);

    ws.onopen = () => {
      document.getElementById('connDot').classList.add('live');
      document.getElementById('connLabel').textContent = 'live';
    };

    ws.onmessage = e => setStatus(JSON.parse(e.data));

    ws.onclose = () => {
      document.getElementById('connDot').classList.remove('live');
      document.getElementById('connLabel').textContent = 'reconnecting';
      setTimeout(connectWS, 2000);
    };
  }

  // ── compact global status pill ──────────────────────────────────────────
  function renderStatusPill() {
    const pill  = document.getElementById('statusPill');
    const label = document.getElementById('statusPillLabel');
    const s = status.status || 'idle';
    pill.className = `status-pill ${s}`;
    label.textContent = s.charAt(0).toUpperCase() + s.slice(1);
  }

  // ── global breakpoint banner ────────────────────────────────────────────
  function renderBreakpointBanner() {
    const banner = document.getElementById('breakpointBanner');
    const msg = document.getElementById('breakpointMsg');
    const bp = status.breakpoint;
    banner.classList.toggle('active', !!bp);
    if (bp) {
      msg.textContent = bp.filename ? `Protocol: ${bp.filename}` : '';
    }
  }

  async function respondToBreakpoint(proceed) {
    document.getElementById('bpContinueBtn').disabled = true;
    document.getElementById('bpAbortBtn').disabled = true;
    try {
      await fetch('/breakpoint/respond', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ proceed }),
      });
    } finally {
      document.getElementById('bpContinueBtn').disabled = false;
      document.getElementById('bpAbortBtn').disabled = false;
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
    document.getElementById('bpContinueBtn').addEventListener('click', () => respondToBreakpoint(true));
    document.getElementById('bpAbortBtn').addEventListener('click', () => respondToBreakpoint(false));
    initTabBar();
    connectWS();
  }

  document.addEventListener('DOMContentLoaded', init);

  return { onStatus, getStatus, registerPage, switchTo };
})();
