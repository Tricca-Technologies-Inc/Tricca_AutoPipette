// Deck page (issue #87): a read-only map of the configured deck, for
// verifying the physical setup (plate/tipbox/waste-container positions, tip
// occupancy) against config before a run. A rig whose system file sets
// `deck_grid` gets a grid of its physical slots, each listing the locations
// in it (Scott's 5" redesign); any other rig gets the spatial map.
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

    const grid = locationsResult.grid;
    document.getElementById('deckGrid').hidden = !grid;
    document.getElementById('deckSquare').hidden = !!grid;
    const container = document.getElementById(grid ? 'deckGrid' : 'deckTiles');
    if (!locationsResult.ok) {
      // Covers both a real load failure and a genuinely empty deck (the
      // daemon reports the latter as ok=false too, e.g. "No locations
      // defined.") -- either way an operator needs a reason, not a blank
      // square indistinguishable from "the page is just broken".
      container.innerHTML = '<div class="tips-empty"></div>';
      container.firstChild.textContent = locationsResult.message;
      return;
    }
    container.innerHTML = '';
    const placed = locationsResult.locations.filter(loc => loc.x != null && loc.y != null);
    if (grid) renderGrid(container, grid, placed, tipsByName);
    else placed.forEach(loc => container.appendChild(renderTile(loc, tipsByName[loc.name])));
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
      return {
        ok: true,
        locations: result.data.locations || [],
        grid: result.data.deck_grid || null,
      };
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

  // ── slot grid (deck_grid) ────────────────────────────────────────────────
  // n edges make n + 1 bands; a location is in the band its origin lies in.
  const band = (edges, mm) => edges.filter(edge => mm >= edge).length;

  // Drawn the way the map is: X0 is the right edge, Y0 the back (top), so
  // the highest-X column is leftmost and the lowest-Y row is on top.
  function renderGrid(container, grid, locations, tipsByName) {
    const cols = grid.x_edges.length + 1;
    const rows = grid.y_edges.length + 1;
    container.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
    container.style.gridTemplateRows = `repeat(${rows}, 1fr)`;
    const slots = new Map();
    locations.forEach(loc => {
      const key = `${band(grid.y_edges, loc.y)},${cols - 1 - band(grid.x_edges, loc.x)}`;
      if (!slots.has(key)) slots.set(key, []);
      slots.get(key).push(loc);
    });
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        container.appendChild(renderSlot(row, col, slots.get(`${row},${col}`) || [], tipsByName));
      }
    }
  }

  function renderSlot(row, col, locs, tipsByName) {
    const slot = document.createElement('div');
    slot.className = 'deck-slot';
    slot.dataset.slot = `${row},${col}`;
    const label = document.createElement('div');
    label.className = 'deck-slot-label';
    label.textContent = `Row ${row + 1} · Col ${col + 1}`;
    slot.appendChild(label);
    if (!locs.length) {
      const empty = document.createElement('div');
      empty.className = 'deck-slot-empty';
      empty.textContent = '—';
      slot.appendChild(empty);
      return slot;
    }
    locs.forEach(loc => {
      const content = document.createElement('div');
      content.className = 'deck-slot-content';
      content.classList.toggle('is-tipbox', loc.type === 'TipBox');
      content.dataset.name = loc.name;
      if (loc.type === 'TipBox' && tipsByName[loc.name]) {
        content.appendChild(renderMiniGrid(tipsByName[loc.name]));
      }
      const name = document.createElement('div');
      name.className = 'deck-slot-name';
      name.textContent = loc.name;
      content.appendChild(name);
      content.addEventListener('click', () => selectTile(loc));
      slot.appendChild(content);
    });
    return slot;
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
  // tips.js's `.tip-cell.present`/`.used` (green = present, amber = used).
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
          const used = box.slots && box.slots[index] === 'used';
          cell.classList.add(box.present[index] ? 'present' : used ? 'used' : 'empty');
        }
        grid.appendChild(cell);
      }
    }
    return grid;
  }

  // ── tap interaction: info panel + tipbox -> Tips tab shortcut ───────────
  function selectTile(loc) {
    document.querySelectorAll('.deck-tile, .deck-slot-content').forEach(t => {
      t.classList.toggle('selected', t.dataset.name === loc.name);
    });

    // textContent throughout: names and details come from config files.
    const info = document.getElementById('deckInfo');
    const line = (cls, text) => {
      const el = document.createElement('div');
      el.className = cls;
      el.textContent = text;
      return el;
    };
    const row = (key, value) => {
      const el = document.createElement('div');
      el.className = 'deck-info-row';
      const k = document.createElement('span');
      k.textContent = key;
      const v = document.createElement('span');
      v.textContent = String(value);
      el.append(k, v);
      return el;
    };
    info.replaceChildren(
      line('deck-info-name', loc.name),
      row('Type', loc.type), row('X', loc.x), row('Y', loc.y), row('Z', loc.z),
    );
    if (loc.details) info.appendChild(line('deck-info-details', loc.details));

    if (loc.type === 'TipBox') {
      App.switchTo('tips');
    }
  }

  App.registerPage('deck', { onShow: loadDeck });
})();
