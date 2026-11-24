// Deck page: a 4-row × 2-column grid matching Tyson's physical slot layout.
//
// Physical layout (operator-confirmed):
//   - Origin (0,0) is back-right; X increases left, Y increases toward front
//   - Two columns:  left = high X (~288-294),  right = low X (~20-96)
//   - Four rows:    front = high Y (~280),  then ~188,  ~107-146,  back ~0-91
//
// Locations are grouped into the nearest slot by X/Y thresholds. Multiple
// logical names at the same physical position are listed together in the slot.
//
// Data sources (same as before — no new daemon logic):
//   GET /locations  — plate/tipbox/waste positions from config
//   GET /tips       — tip occupancy per tipbox (reused from tips.js)
(() => {

  // ── slot definition ───────────────────────────────────────────────────────
  // Thresholds that separate left column from right, and the 4 row bands.
  // Adjust if a new machine has a different spacing.
  const COL_THRESHOLD = 190;   // x >= threshold → left column
  const ROW_THRESHOLDS = [235, 165, 70]; // y boundaries (front→back): >235 row0, >165 row1, >70 row2, else row3

  function slotOf(loc) {
    const col = loc.x >= COL_THRESHOLD ? 0 : 1;   // 0=left, 1=right
    let row = 3;
    if (loc.y > ROW_THRESHOLDS[0]) row = 0;
    else if (loc.y > ROW_THRESHOLDS[1]) row = 1;
    else if (loc.y > ROW_THRESHOLDS[2]) row = 2;
    return { row, col };
  }

  // ── data loading ──────────────────────────────────────────────────────────
  async function loadDeck() {
    const [locationsResult, tipsByName] = await Promise.all([
      loadLocations(),
      loadTipsByName(),
    ]);

    const container = document.getElementById('deckTiles');
    if (!locationsResult.ok) {
      container.innerHTML = `<div class="tips-empty">${locationsResult.message}</div>`;
      return;
    }

    // Group locations into 4×2 grid slots
    const grid = Array.from({ length: 4 }, () => [[], []]);  // grid[row][col] = [locs]
    locationsResult.locations
      .filter(loc => loc.x != null && loc.y != null)
      .forEach(loc => {
        const { row, col } = slotOf(loc);
        grid[row][col].push(loc);
      });

    // Render the grid
    container.innerHTML = '';
    container.style.display = 'grid';
    container.style.gridTemplateColumns = '1fr 1fr';
    container.style.gridTemplateRows = 'repeat(4, 1fr)';
    container.style.gap = '8px';
    container.style.padding = '8px';
    container.style.boxSizing = 'border-box';

    // Render back→front (row 3 first, row 0 last) so front is at the bottom
    for (let row = 3; row >= 0; row--) {
      for (let col = 0; col < 2; col++) {
        const locs = grid[row][col];
        container.appendChild(renderSlot(row, col, locs, tipsByName));
      }
    }
  }

  async function loadLocations() {
    try {
      const res = await fetch('/locations');
      const result = await res.json();
      if (!res.ok || !result.ok) {
        return { ok: false, message: result.message || result.detail || 'Failed to load locations', locations: [] };
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
    } catch (e) {}
    return byName;
  }

  // ── slot rendering ────────────────────────────────────────────────────────
  function renderSlot(row, col, locs, tipsByName) {
    const slot = document.createElement('div');
    slot.className = 'deck-slot';

    // Row label: front=1, back=4
    const rowLabel = document.createElement('div');
    rowLabel.className = 'deck-slot-label';
    rowLabel.textContent = `Row ${row + 1} ${col === 0 ? '· Left' : '· Right'}`;
    slot.appendChild(rowLabel);

    if (!locs.length) {
      const empty = document.createElement('div');
      empty.className = 'deck-slot-empty';
      empty.textContent = '—';
      slot.appendChild(empty);
      return slot;
    }

    // Deduplicate by rounded coordinate — show unique physical positions
    const seen = new Set();
    const unique = locs.filter(loc => {
      const key = `${Math.round(loc.x)},${Math.round(loc.y)}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });

    // Pick the most informative representative (prefer tipbox/waste, then first)
    const primary = unique.find(l => l.type === 'TipBox' || l.type === 'waste_container') || unique[0];
    const tipbox = tipsByName[primary.name];
    const isTipbox = primary.type === 'TipBox';
    const isWaste = primary.type === 'waste_container';

    // All logical names at this slot
    const names = locs.map(l => l.name);

    const content = document.createElement('div');
    content.className = `deck-slot-content ${isTipbox ? 'is-tipbox' : ''} ${isWaste ? 'is-waste' : ''}`;

    if (isTipbox && tipbox) {
      content.appendChild(renderMiniGrid(tipbox));
    }

    // Show the first unique name prominently, count if many
    const nameEl = document.createElement('div');
    nameEl.className = 'deck-slot-name';
    // Find shortest / most distinct name among the group
    const display = names.reduce((a, b) => a.length <= b.length ? a : b);
    nameEl.textContent = names.length > 1 ? `${display} +${names.length - 1}` : display;
    content.appendChild(nameEl);

    content.addEventListener('click', () => selectSlot(primary, names, slot));
    slot.appendChild(content);
    return slot;
  }

  function renderMiniGrid(box) {
    const grid = document.createElement('div');
    grid.className = 'deck-mini-grid';
    grid.style.gridTemplateColumns = `repeat(${box.num_col}, 1fr)`;
    grid.style.gridTemplateRows = `repeat(${box.num_row}, 1fr)`;
    const eligible = new Set(box.eligible || []);
    for (let r = 0; r < box.num_row; r++) {
      for (let c = 0; c < box.num_col; c++) {
        const index = r * box.num_col + c;
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

  // ── tap interaction ───────────────────────────────────────────────────────
  function selectSlot(loc, allNames, slotEl) {
    document.querySelectorAll('.deck-slot-content').forEach(el => el.classList.remove('selected'));
    slotEl.querySelector('.deck-slot-content')?.classList.add('selected');

    document.getElementById('deckInfo').innerHTML = `
      <div class="deck-info-name">${loc.name}</div>
      ${allNames.length > 1 ? `<div class="deck-info-row"><span>Also here</span><span>${allNames.filter(n => n !== loc.name).join(', ')}</span></div>` : ''}
      <div class="deck-info-row"><span>Type</span><span>${loc.type}</span></div>
      <div class="deck-info-row"><span>X</span><span>${loc.x}</span></div>
      <div class="deck-info-row"><span>Y</span><span>${loc.y}</span></div>
      <div class="deck-info-row"><span>Z</span><span>${loc.z}</span></div>
    `;

    if (loc.type === 'TipBox') App.switchTo('tips');
  }

  App.registerPage('deck', { onShow: loadDeck });
})();
