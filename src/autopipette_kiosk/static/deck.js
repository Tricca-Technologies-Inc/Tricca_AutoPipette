// Deck page (issue #87): a read-only spatial map of the configured deck, for
// verifying the physical setup (plate/tipbox/waste-container positions, tip
// occupancy) against config before a run.
//
// Two data sources, both already exposed elsewhere -- no new deck logic
// lives in daemon/service.py, matching the Client parity rule:
//   - GET /locations (new, issue #87): a thin proxy over config.list_locations,
//     the same data cli/report_tables.py's build_locations_table renders as
//     an ASCII table for `tap`'s `ls locs`. This is a second, spatial
//     renderer of that data, not a second implementation.
//   - GET /tips (issue #17, already used by tips.js): TipBoxManager.describe's
//     per-box payload, reused here as a second, smaller, non-interactive
//     renderer (no tap-to-toggle -- the Tips page owns editing).
(() => {
  // The physical deck is roughly centered inside a 40cm x 40cm square, with
  // the machine's coordinate origin (0,0) at the square's top-right corner
  // (operator-provided sketch, issue #87). X increases and Y increases
  // moving away from that corner -- so a location's real mm coordinates
  // map onto the square as straight-line distance from the top-right,
  // increasing X moving left and increasing Y moving down. Confirmed
  // against the shared repo's own config/locations/examples_deck.json
  // (real x values 20-150, all of which must land inside 0-100%); a
  // previous X-decreases-away guess, extrapolated from core/plates.py's
  // PlateArray._gen_wells (which describes wells *within* one plate's own
  // local frame, not a plate's placement relative to the deck origin),
  // put every one of those real positions off the square's right edge.
  const SQUARE_MM = 400;

  // ── coordinate transform (pure) ─────────────────────────────────────────
  function toPercent(xMm, yMm) {
    return {
      leftPct: 100 - (xMm / SQUARE_MM) * 100,
      topPct: (yMm / SQUARE_MM) * 100,
    };
  }

  // ── data loading ─────────────────────────────────────────────────────────
  async function loadDeck() {
    const [locationsResult, tipsByName] = await Promise.all([
      loadLocations(),
      loadTipsByName(),
    ]);

    const container = document.getElementById('deckTiles');
    if (!locationsResult.ok) {
      // Covers both a real load failure and a genuinely empty deck (the
      // daemon reports the latter as ok=false too, e.g. "No locations
      // defined.") -- either way an operator needs a reason, not a blank
      // square indistinguishable from "the page is just broken".
      container.innerHTML = `<div class="tips-empty">${locationsResult.message}</div>`;
      return;
    }
    container.innerHTML = '';
    locationsResult.locations
      .filter(loc => loc.x != null && loc.y != null)
      .forEach(loc => container.appendChild(renderTile(loc, tipsByName[loc.name])));
  }

  async function loadLocations() {
    try {
      const res = await fetch('/locations');
      const result = await res.json();
      if (!res.ok || !result.ok) {
        return {
          ok: false,
          message: result.message || result.detail || 'Failed to load locations',
          locations: [],
        };
      }
      return { ok: true, locations: result.data.locations || [] };
    } catch (e) {
      return { ok: false, message: 'Failed to load locations', locations: [] };
    }
  }

  async function loadTipsByName() {
    const byName = {};
    try {
      const res = await fetch('/tips');
      const result = await res.json();
      if (result.ok) {
        (result.data.boxes || []).forEach(box => { byName[box.name] = box; });
      }
    } catch (e) {
      // leave byName empty -- tipbox tiles just render without their grid
    }
    return byName;
  }

  // ── tile rendering ───────────────────────────────────────────────────────
  function renderTile(loc, tipbox) {
    const isTipbox = loc.type === 'TipBox';
    const { leftPct, topPct } = toPercent(loc.x, loc.y);

    const tile = document.createElement('div');
    tile.className = `deck-tile ${isTipbox ? 'deck-tile-tipbox' : 'deck-tile-dot'}`;
    tile.style.left = `${leftPct}%`;
    tile.style.top = `${topPct}%`;
    tile.dataset.name = loc.name;
    tile.title = loc.name;

    if (isTipbox && tipbox) {
      tile.appendChild(renderMiniGrid(tipbox));
    }

    tile.addEventListener('click', () => selectTile(loc));
    return tile;
  }

  // Non-interactive mini occupancy grid -- same present/eligible payload
  // tips.js's renderBox reads, rendered smaller and with no click handlers
  // (the Tips page, not this one, owns editing). Color convention matches
  // tips.js's `.tip-cell.present` (green = present).
  function renderMiniGrid(box) {
    const grid = document.createElement('div');
    grid.className = 'deck-mini-grid';
    grid.style.gridTemplateColumns = `repeat(${box.num_col}, 1fr)`;
    grid.style.gridTemplateRows = `repeat(${box.num_row}, 1fr)`;

    const eligible = new Set(box.eligible || []);
    for (let row = 0; row < box.num_row; row++) {
      for (let col = 0; col < box.num_col; col++) {
        const index = row * box.num_col + col;
        const cell = document.createElement('div');
        cell.className = 'deck-mini-cell';
        if (!eligible.has(index)) {
          cell.classList.add('masked');
        } else {
          cell.classList.add(box.present[index] ? 'present' : 'empty');
        }
        grid.appendChild(cell);
      }
    }
    return grid;
  }

  // ── tap interaction: info panel + tipbox -> Tips tab shortcut ───────────
  function selectTile(loc) {
    document.querySelectorAll('.deck-tile').forEach(t => {
      t.classList.toggle('selected', t.dataset.name === loc.name);
    });

    document.getElementById('deckInfo').innerHTML = `
      <div class="deck-info-name">${loc.name}</div>
      <div class="deck-info-row"><span>Type</span><span>${loc.type}</span></div>
      <div class="deck-info-row"><span>X</span><span>${loc.x}</span></div>
      <div class="deck-info-row"><span>Y</span><span>${loc.y}</span></div>
      <div class="deck-info-row"><span>Z</span><span>${loc.z}</span></div>
      ${loc.details ? `<div class="deck-info-details">${loc.details}</div>` : ''}
    `;

    if (loc.type === 'TipBox') {
      App.switchTo('tips');
    }
  }

  App.registerPage('deck', { onShow: loadDeck });
})();
