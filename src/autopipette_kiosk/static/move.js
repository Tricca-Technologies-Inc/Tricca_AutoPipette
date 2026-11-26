// Move page (issue #86): D-pad jog, absolute-coordinate move, and
// named-location move -- three thin adapters over the daemon's
// movement.move/move_loc/move_rel RPCs (via /move, /move_loc, /move_rel),
// a plate drawer jog column beside Z (issue #215: /plate_move with --rel,
// /plates_in, /plates; hidden with no plates configured),
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
  // From GET /plates: [{name, letter, homed, position, stop, ...}].
  let plates = [];
  let selectedPlate = null;
  // Remembered across reloads; guarded, since storage can be unavailable.
  const PLATE_KEY = 'move.plate';
  function rememberedPlate() {
    try { return localStorage.getItem(PLATE_KEY); } catch (e) { return null; }
  }

  // ── homed-axes check: mirrors daemon/moonraker_state.py's
  // REQUIRED_HOMED_AXES (x/y/z all reported homed) -- client-side only for
  // display; the daemon's own require_homed decorator is still the real
  // gate, this banner is just so an operator sees it before tapping Go and
  // getting a 409 back. ──────────────────────────────────────────────────
  function isHomed(homedAxes) {
    return !!homedAxes && ['x', 'y', 'z'].every(axis => homedAxes.includes(axis));
  }

  // A config change (pipette/gantry/system swap) also makes tapd refuse
  // moves until a full home, though Klipper still reports xyz homed.
  function renderNotHomedBanner(homedAxes, homingInvalidated) {
    document.getElementById('moveNotHomedBanner').classList.toggle(
      'active', homingInvalidated || !isHomed(homedAxes));
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
    renderNotHomedBanner(toolhead.homed_axes, !!data.homing_invalidated);
    renderLivePosition(toolhead.position);
    renderPlateLive(data.plate_axes);
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
      return res.ok;
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
    // jog: the gantry's slower jog speeds, not the protocol speeds.
    const body = { x: 0, y: 0, z: 0, jog: true };
    body[axis] = offset;
    postMove('/move_rel', body, document.getElementById('moveJogFeedback'));
  });

  // ── plate drawer jog (issue #215) ──────────────────────────────────────
  // 0 is "in": the top arrow jogs in (a negative offset), the bottom out.
  function selected() {
    return plates.find(p => p.name === selectedPlate);
  }

  function renderPlateReadout(position, homed) {
    const plate = selected();
    document.getElementById('platePosLive').textContent =
      typeof position === 'number' ? position.toFixed(2) : '--';
    document.getElementById('plateHomedLive').textContent =
      homed === undefined ? '' : (homed ? 'Homed' : 'Not homed');
    document.getElementById('plateStopLive').textContent = (plate && plate.stop) || '';
  }

  // Live position/homed from the /ws/status push (gcode_move/_PLATE_STATE).
  function renderPlateLive(axes) {
    const plate = selected();
    if (!plate || !axes) return;
    const position = (axes.positions || {})[plate.letter];
    const homed = (axes.homed || {})[plate.name];
    if (position === undefined && homed === undefined) return;
    renderPlateReadout(
      position === undefined ? plate.position : position,
      homed === undefined ? plate.homed : homed);
  }

  function renderPlateSelector() {
    const selector = document.getElementById('plateSelector');
    selector.replaceChildren(...plates.map(p => {
      const btn = document.createElement('button');
      btn.className = 'plate-sel-btn';
      btn.classList.toggle('active', p.name === selectedPlate);
      btn.dataset.plate = p.name;
      btn.textContent = p.name;
      return btn;
    }));
    const plate = selected();
    if (plate) renderPlateReadout(plate.position, plate.homed);
  }

  async function loadPlates() {
    const col = document.getElementById('movePlateCol');
    try {
      const res = await fetch('/plates');
      const result = await res.json();
      plates = (res.ok && result.ok && result.data && result.data.plates) || [];
    } catch (e) {
      plates = [];
    }
    col.hidden = plates.length === 0;
    if (!plates.some(p => p.name === selectedPlate)) {
      const saved = rememberedPlate();
      selectedPlate = plates.some(p => p.name === saved) ? saved
        : (plates.length ? plates[0].name : null);
    }
    renderPlateSelector();
  }

  document.getElementById('plateSelector').addEventListener('click', e => {
    const btn = e.target.closest('.plate-sel-btn');
    if (!btn) return;
    selectedPlate = btn.dataset.plate;
    try { localStorage.setItem(PLATE_KEY, selectedPlate); } catch (err) { /* no storage */ }
    renderPlateSelector();
  });

  document.querySelectorAll('.plate-jog-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (running || !selectedPlate) return;
      const offset = parseFloat(btn.dataset.dir) * stepSize;
      // No speed: the daemon uses the gantry's plate_jog_speed.
      const body = { plate: selectedPlate, target: String(offset), rel: true };
      await postMove('/plate_move', body, document.getElementById('moveJogFeedback'));
      loadPlates();
    });
  });

  document.getElementById('platesInBtn').addEventListener('click', async () => {
    if (running) return;
    await postMove('/plates_in', {}, document.getElementById('moveJogFeedback'));
    loadPlates();
  });

  // ── absolute move ───────────────────────────────────────────────────────
  document.getElementById('moveAbsGoBtn').addEventListener('click', () => {
    if (running) return;
    const feedbackEl = document.getElementById('moveAbsFeedback');
    const x = parseFloat(document.getElementById('moveXInput').value);
    const y = parseFloat(document.getElementById('moveYInput').value);
    const z = parseFloat(document.getElementById('moveZInput').value);
    // A blank or non-numeric field must never silently become 0 -- this
    // fires an immediate, unconfirmed move on a live machine, so treating
    // "didn't finish typing" the same as "meant 0" risks a real mis-move.
    if (![x, y, z].every(Number.isFinite)) {
      feedbackEl.classList.add('error');
      feedbackEl.textContent = 'Enter a number for X, Y, and Z before moving.';
      setTimeout(() => { feedbackEl.textContent = ''; }, 6000);
      return;
    }
    postMove('/move', { x, y, z }, feedbackEl);
  });

  // ── named-location move ─────────────────────────────────────────────────
  async function loadLocations() {
    const select = document.getElementById('moveLocSelect');
    try {
      const res = await fetch('/locations');
      const result = await res.json();
      if (!res.ok || !result.ok) {
        select.replaceChildren(new Option(result.message || result.detail || 'Failed to load locations', ''));
        return;
      }
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

  App.registerPage('move', { onShow: () => { loadLocations(); loadPlates(); } });
})();
