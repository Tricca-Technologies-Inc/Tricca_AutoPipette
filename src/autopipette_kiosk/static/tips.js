// Tips page (issue #17): per-box tip-inventory grid, reset button,
// tap-to-toggle. A second renderer of `TipBoxManager.describe`'s payload
// (the same data `cli/report_tables.py`'s `build_tipbox_map` renders as
// ASCII) -- no tip logic lives here beyond turning that payload into a grid
// and turning a tap back into a `config.set_tips` call.
(() => {
  let running = false;

  // ── well-id math (mirrors core/traversal.py's rc_to_well_id: zero-based
  // row/col in, single-letter-row "A1"-style id out) ──────────────────────
  function wellId(row, col) {
    return String.fromCharCode(65 + row) + (col + 1);
  }

  // ── data loading ─────────────────────────────────────────────────────
  async function loadTips() {
    const container = document.getElementById('tipboxList');
    try {
      const res = await fetch('/tips');
      const result = await res.json();
      if (!result.ok) {
        container.innerHTML = `<div class="tips-empty">${result.message || 'Failed to load tip boxes'}</div>`;
        return;
      }
      renderBoxes(result.data.boxes || []);
    } catch (e) {
      container.innerHTML = '<div class="tips-empty">Failed to load tip boxes</div>';
    }
  }

  function renderBoxes(boxes) {
    const container = document.getElementById('tipboxList');
    if (!boxes.length) {
      container.innerHTML = '<div class="tips-empty">No tipboxes are loaded.</div>';
      return;
    }
    container.innerHTML = '';
    boxes.forEach(box => container.appendChild(renderBox(box)));
    applyRunningState();
  }

  function renderBox(box) {
    const card = document.createElement('div');
    card.className = 'tipbox-card';
    card.dataset.box = box.name;

    const header = document.createElement('div');
    header.className = 'tipbox-header';
    header.innerHTML = `
      <span class="tipbox-name">${box.name}</span>
      <span class="tipbox-count">${box.remaining}/${box.capacity} available</span>
      <span class="tipbox-spacer"></span>
    `;
    const resetBtn = document.createElement('button');
    resetBtn.className = 'tipbox-reset-btn';
    resetBtn.textContent = 'Reloaded';
    resetBtn.title = `Mark ${box.name} as full`;
    resetBtn.addEventListener('click', () => resetBox(box.name));
    header.appendChild(resetBtn);
    card.appendChild(header);

    const grid = document.createElement('div');
    grid.className = 'tipbox-grid';
    grid.style.gridTemplateColumns = `repeat(${box.num_col}, 1fr)`;
    grid.style.gridTemplateRows = `repeat(${box.num_row}, 1fr)`;

    const eligible = new Set(box.eligible || []);
    for (let row = 0; row < box.num_row; row++) {
      for (let col = 0; col < box.num_col; col++) {
        const index = row * box.num_col + col;
        const cell = document.createElement('div');
        cell.className = 'tip-cell';
        cell.dataset.index = String(index);
        const isEligible = eligible.has(index);
        if (!isEligible) {
          cell.classList.add('masked');
          cell.title = `${wellId(row, col)} (not usable)`;
        } else {
          cell.title = wellId(row, col);
          if (box.present[index]) cell.classList.add('present');
          if (index === box.next_index) cell.classList.add('next');
          cell.addEventListener('click', () => toggleCell(box, index, cell));
        }
        grid.appendChild(cell);
      }
    }
    card.appendChild(grid);
    return card;
  }

  // ── toggle math: pure, no DOM/fetch -- given a box's current present/
  // eligible state and the toggled index, the new present array and the
  // full consumed-well-id list `set_tips` needs (issue #17's Q2: it
  // replaces a box's whole state, so every toggle resends the box's full
  // current consumed set restricted to eligible positions; masked-out
  // positions are never listed either way). ──────────────────────────────
  function computeToggle(box, index) {
    const present = box.present.slice();
    present[index] = !present[index];

    const eligible = new Set(box.eligible || []);
    const consumedRanges = [];
    for (let i = 0; i < present.length; i++) {
      if (eligible.has(i) && !present[i]) {
        const row = Math.floor(i / box.num_col);
        const col = i % box.num_col;
        consumedRanges.push(wellId(row, col));
      }
    }
    return { present, consumedRanges };
  }

  // ── mutations: thin DOM+fetch adapter around computeToggle -- immediate
  // auto-save per tap, not a batched "Apply" (issue #17's Q2). ──────────
  async function toggleCell(box, index, cell) {
    const wasPresent = box.present[index];
    const { present, consumedRanges } = computeToggle(box, index);
    box.present = present; // optimistic update
    cell.classList.toggle('present', box.present[index]);
    cell.classList.add('pending');

    try {
      const res = await fetch('/tips/set', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: box.name, ranges: consumedRanges, available: false }),
      });
      const result = await res.json();
      if (!res.ok || !result.ok) {
        box.present[index] = wasPresent; // revert on failure
        cell.classList.toggle('present', box.present[index]);
      }
    } catch (e) {
      box.present[index] = wasPresent;
      cell.classList.toggle('present', box.present[index]);
    } finally {
      cell.classList.remove('pending');
      // Refetch so remaining/capacity/next_well (server-computed) and any
      // change from a concurrent client are reflected, not just this cell.
      loadTips();
    }
  }

  async function resetBox(name) {
    try {
      await fetch('/tips/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
    } finally {
      loadTips();
    }
  }

  // ── grey out while a run is active (client-side only, issue #17's Q3) ──
  function applyRunningState() {
    document.querySelectorAll('.tipbox-card').forEach(card => {
      card.classList.toggle('disabled', running);
    });
  }

  App.onStatus(data => {
    running = data.status === 'running';
    applyRunningState();
  });

  App.registerPage('tips', { onShow: loadTips });
})();
