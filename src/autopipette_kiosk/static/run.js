// Run page: protocol list, run button, detailed status card.
//
// Subscribes to App.onStatus rather than owning any WebSocket connection or
// run-status state itself (app.js owns both, since the header's compact
// status pill and breakpoint banner need the same data regardless of which
// tab is active -- see issue #25).
(() => {
  let selected = null;

  // ── protocol list ──────────────────────────────────────────────────────
  async function loadProtocols() {
    try {
      const res = await fetch('/protocols');
      const protocols = await res.json();
      renderList(protocols);
    } catch (e) {
      document.getElementById('protocolList').innerHTML =
        '<div class="empty-state">Failed to load protocols</div>';
    }
  }

  function renderList(protocols) {
    const list = document.getElementById('protocolList');
    if (!protocols.length) {
      list.innerHTML = '<div class="empty-state">No .pipette files found</div>';
      return;
    }
    list.innerHTML = protocols.map(p => `
      <div class="protocol-item" data-filename="${p.filename}" onclick="selectProtocol(this, '${p.filename}', '${p.name}')">
        <div class="protocol-icon">${p.name.slice(0, 2)}</div>
        <span class="protocol-name">${p.name}</span>
        <span class="protocol-ext">.pipette</span>
      </div>
    `).join('');
  }

  // Exposed on window: renderList's markup calls this via an inline
  // onclick, same as the kiosk's original single-page script did.
  window.selectProtocol = function selectProtocol(el, filename, name) {
    document.querySelectorAll('.protocol-item').forEach(i => i.classList.remove('selected'));
    el.classList.add('selected');
    selected = filename;

    const nameEl = document.getElementById('selectionName');
    nameEl.textContent = name;
    nameEl.classList.remove('placeholder');
    document.getElementById('runBtn').disabled = App.getStatus().status === 'running';
    document.getElementById('checkBtn').disabled = false;
    document.getElementById('findingsList').innerHTML = '';
  };

  // ── run ────────────────────────────────────────────────────────────────
  document.getElementById('runBtn').addEventListener('click', async () => {
    if (!selected) return;
    try {
      const res = await fetch('/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: selected }),
      });
      if (!res.ok) {
        const err = await res.json();
        renderStatusCard({ status: 'error', message: err.detail });
      }
    } catch (e) {
      renderStatusCard({ status: 'error', message: e.message });
    }
  });

  // ── check (pre-flight validation, issue #88) ──────────────────────────
  // Explicit trigger only (no auto-validate on selection, no bulk
  // pre-validation of the list) and warn-only: findings are advisory
  // display, never disable/block the Run button.
  document.getElementById('checkBtn').addEventListener('click', async () => {
    if (!selected) return;
    const list = document.getElementById('findingsList');
    list.innerHTML = '<div class="empty-state">Checking…</div>';
    try {
      const res = await fetch('/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: selected }),
      });
      const body = await res.json();
      if (!res.ok) {
        list.innerHTML = `<div class="finding-item error">${body.detail}</div>`;
        return;
      }
      renderFindings(body.data && body.data.findings ? body.data.findings : []);
    } catch (e) {
      list.innerHTML = `<div class="finding-item error">${e.message}</div>`;
    }
  });

  function renderFindings(findings) {
    const list = document.getElementById('findingsList');
    if (!findings.length) {
      list.innerHTML = '<div class="empty-state">No issues found</div>';
      return;
    }
    list.innerHTML = findings.map(f => `
      <div class="finding-item ${f.severity}">
        <span class="finding-severity">${f.severity}</span>
        <span class="finding-line">line ${f.line_number}</span>
        <span class="finding-message">${f.message}</span>
      </div>
    `).join('');
  }

  // ── detailed status card (Run-page-specific; the compact pill + global
  // breakpoint banner in the header are app.js's job) ─────────────────────
  function renderStatusCard(data) {
    const icon  = document.getElementById('statusIcon');
    const state = document.getElementById('statusState');
    const msg   = document.getElementById('statusMsg');
    const bar   = document.getElementById('progressBar');
    const btn   = document.getElementById('runBtn');

    const s = data.status;
    const { label, icon: iconChar } = App.describeStatus(s);

    icon.className  = `status-icon ${s}`;
    state.className = `status-state ${s}`;
    icon.textContent  = iconChar;
    state.textContent = label;
    msg.textContent   = data.message || '';

    icon.classList.toggle('spinning', s === 'running');
    bar.classList.toggle('active', s === 'running');
    btn.disabled = s === 'running' || !selected;
  }

  App.onStatus(renderStatusCard);
  App.registerPage('run', {});

  loadProtocols();
})();
