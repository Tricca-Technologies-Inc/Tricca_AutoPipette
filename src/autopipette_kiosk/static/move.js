// Move page (issue #86): D-pad jog, absolute-coordinate move, and
// named-location move -- three thin adapters over the daemon's
// movement.move/move_loc/move_rel RPCs (via /move, /move_loc, /move_rel),
// plus the live position/homed banner relayed over the shared /ws/status
// stream app.js already owns (App.onStatus).
//
// All three sections act immediately on tap -- no confirmation dialogs
// (jog/goto aren't destructive; a stray tap is correctable with another
// tap, see CLAUDE.md/issue #86).
(() => {
  let stepSize = 1;
  let running = false;
  // {name -> {type, x, y, z, details}}, loaded once per onShow -- the
  // dropdown doesn't need to react to the deck changing live.
  let locationsByName = {};

  // ── homed-axes check: mirrors daemon/moonraker_state.py's
  // REQUIRED_HOMED_AXES (x/y/z all reported homed) -- client-side only for
  // display; the daemon's own require_homed decorator is still the real
  // gate, this banner is just so an operator sees it before tapping Go and
  // getting a 409 back. ──────────────────────────────────────────────────
  function isHomed(homedAxes) {
    return !!homedAxes && ['x', 'y', 'z'].every(axis => homedAxes.includes(axis));
  }

  function renderNotHomedBanner(homedAxes) {
    document.getElementById('moveNotHomedBanner').classList.toggle('active', !isHomed(homedAxes));
  }

  // ── live position: skip overwriting a field the operator is actively
  // editing, so an incoming push doesn't clobber an in-progress edit. ────
  function renderLivePosition(position) {
    const axes = [
      ['moveXInput', 'moveXLive'],
      ['moveYInput', 'moveYLive'],
      ['moveZInput', 'moveZLive'],
    ];
    axes.forEach(([inputId, liveId], i) => {
      const value = position ? position[i] : null;
      const text = value === null || value === undefined ? '--' : value.toFixed(3);
      document.getElementById(liveId).textContent = text;
      const input = document.getElementById(inputId);
      if (document.activeElement !== input && value !== null && value !== undefined) {
        input.value = value.toFixed(3);
      }
    });
  }

  // ── run-active graying (mirrors tips.js's applyRunningState) ──────────
  function applyRunningState() {
    document.querySelectorAll('.move-panel').forEach(panel => {
      panel.classList.toggle('disabled', running);
    });
  }

  App.onStatus(data => {
    running = data.status === 'running';
    applyRunningState();
    const toolhead = data.toolhead || {};
    renderNotHomedBanner(toolhead.homed_axes);
    renderLivePosition(toolhead.position);
  });

  // ── shared POST-and-report helper (mirrors app.js's home()) ───────────
  async function postMove(url, body, feedbackEl) {
    feedbackEl.classList.remove('error');
    feedbackEl.textContent = 'Moving…';
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        feedbackEl.classList.add('error');
        feedbackEl.textContent = data.detail || 'Move failed';
      } else {
        feedbackEl.textContent = data.message || 'Done';
      }
    } catch (e) {
      feedbackEl.classList.add('error');
      feedbackEl.textContent = e.message;
    } finally {
      setTimeout(() => { feedbackEl.textContent = ''; }, 6000);
    }
  }

  // ── step-size selector ─────────────────────────────────────────────────
  document.getElementById('stepSelector').addEventListener('click', e => {
    const btn = e.target.closest('.step-btn');
    if (!btn) return;
    document.querySelectorAll('.step-btn').forEach(b => b.classList.toggle('active', b === btn));
    stepSize = parseFloat(btn.dataset.step);
    document.getElementById('dpadStepLabel').textContent = `${btn.dataset.step} mm`;
  });

  // ── D-pad (move_rel) ────────────────────────────────────────────────────
  document.querySelector('.dpad').addEventListener('click', e => {
    const btn = e.target.closest('.dpad-btn');
    if (!btn || running) return;
    const axis = btn.dataset.axis;
    const offset = parseFloat(btn.dataset.dir) * stepSize;
    const body = { x: 0, y: 0, z: 0 };
    body[axis] = offset;
    postMove('/move_rel', body, document.getElementById('moveJogFeedback'));
  });

  // ── absolute move ───────────────────────────────────────────────────────
  document.getElementById('moveAbsGoBtn').addEventListener('click', () => {
    if (running) return;
    const body = {
      x: parseFloat(document.getElementById('moveXInput').value) || 0,
      y: parseFloat(document.getElementById('moveYInput').value) || 0,
      z: parseFloat(document.getElementById('moveZInput').value) || 0,
    };
    postMove('/move', body, document.getElementById('moveAbsFeedback'));
  });

  // ── named-location move ─────────────────────────────────────────────────
  async function loadLocations() {
    const select = document.getElementById('moveLocSelect');
    try {
      const res = await fetch('/locations');
      const result = await res.json();
      const locations = (result.data && result.data.locations) || [];
      locationsByName = {};
      locations.forEach(loc => { locationsByName[loc.name] = loc; });
      select.innerHTML = '<option value="">Select a location…</option>' +
        locations.map(loc => `<option value="${loc.name}">${loc.name}</option>`).join('');
    } catch (e) {
      select.innerHTML = '<option value="">Failed to load locations</option>';
    }
  }

  document.getElementById('moveLocSelect').addEventListener('change', e => {
    const loc = locationsByName[e.target.value];
    const rowCol = document.getElementById('moveLocRowCol');
    // A plain named coordinate has no row/col to pick -- only a plate
    // location does (issue #86).
    rowCol.classList.toggle('visible', !!loc && loc.type !== 'Coordinate');
  });

  document.getElementById('moveLocGoBtn').addEventListener('click', () => {
    if (running) return;
    const name = document.getElementById('moveLocSelect').value;
    if (!name) return;
    const loc = locationsByName[name];
    const body = { name_loc: name, row: null, col: null };
    if (loc && loc.type !== 'Coordinate') {
      body.row = parseInt(document.getElementById('moveLocRow').value, 10) || 0;
      body.col = parseInt(document.getElementById('moveLocCol').value, 10) || 0;
    }
    postMove('/move_loc', body, document.getElementById('moveLocFeedback'));
  });

  App.registerPage('move', { onShow: loadLocations });
})();
