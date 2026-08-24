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
  // (operator-provided sketch, issue #87). Per core/plates.py's
  // PlateArray._gen_wells (x = start.x - col*spacing_col, y = start.y +
  // row*spacing_row), X decreases and Y increases moving away from the
  // origin -- so a location's real mm coordinates map onto the square as
  // straight-line distance from that top-right corner.
  const SQUARE_MM = 400;

  // ── coordinate transform (pure) ─────────────────────────────────────────
  function toPercent(xMm, yMm) {
    return {
      leftPct: 100 + (xMm / SQUARE_MM) * 100,
      topPct: (yMm / SQUARE_MM) * 100,
    };
  }

  // ── data loading ─────────────────────────────────────────────────────────
  async function loadDeck() {
    const [locations, tipsByName] = await Promise.all([
      loadLocations(),
      loadTipsByName(),
    ]);

    const container = document.getElementById('deckTiles');
    container.innerHTML = '';
    locations
      .filter(loc => loc.x != null && loc.y != null)
      .forEach(loc => container.appendChild(renderTile(loc, tipsByName[loc.name])));
  }

  async function loadLocations() {
    try {
      const res = await fetch('/locations');
      const result = await res.json();
      return result.ok ? result.data.locations || [] : [];
    } catch (e) {
      return [];
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
