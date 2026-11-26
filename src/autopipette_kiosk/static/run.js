// Run page: protocol list, run button, detailed status card.
//
// Subscribes to App.onStatus rather than owning any WebSocket connection or
// run-status state itself (app.js owns both, since the header's compact
// status pill and paused-run banner need the same data regardless of which
// tab is active -- see issue #25).
(() => {
  let selected = null;
  let protocols = [];
  let folder = '';

  // ── protocol list ──────────────────────────────────────────────────────
  async function loadProtocols() {
    try {
      const res = await fetch('/protocols');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      protocols = await res.json();
      renderList();
    } catch (e) {
      document.getElementById('protocolList').innerHTML =
        '<div class="empty-state">Failed to load protocols</div>';
    }
  }

  function renderList() {
    const list = document.getElementById('protocolList');
    list.replaceChildren();
    if (!protocols.length) {
      list.innerHTML = '<div class="empty-state">No .pipette files found</div>';
      return;
    }
    if (folder) {
      const back = document.createElement('button');
      back.className = 'protocol-folder';
      back.textContent = '← Back';
      back.addEventListener('click', () => {
        folder = folder.split('/').slice(0, -1).join('/');
        renderList();
      });
      list.appendChild(back);
      const current = document.createElement('div');
      current.className = 'protocol-current-folder';
      current.textContent = folder;
      list.appendChild(current);
    }

    const prefix = folder ? `${folder}/` : '';
    const folders = new Set();
    const files = [];
    protocols.forEach(protocol => {
      if (!protocol.filename.startsWith(prefix)) return;
      const remainder = protocol.filename.slice(prefix.length);
      if (remainder.includes('/')) folders.add(remainder.split('/')[0]);
      else files.push(protocol);
    });
    [...folders].sort().forEach(name => {
      const button = document.createElement('button');
      button.className = 'protocol-folder';
      button.textContent = `${name} /`;
      button.addEventListener('click', () => {
        folder = prefix + name;
        renderList();
      });
      list.appendChild(button);
    });
    files.forEach(protocol => {
      const item = document.createElement('button');
      item.className = 'protocol-item';
      item.dataset.filename = protocol.filename;
      item.classList.toggle('selected', selected === protocol.filename);
      const icon = document.createElement('span');
      icon.className = 'protocol-icon';
      icon.textContent = protocol.name.slice(0, 2);
      const name = document.createElement('span');
      name.className = 'protocol-name';
      name.textContent = protocol.name;
      const ext = document.createElement('span');
      ext.className = 'protocol-ext';
      ext.textContent = '.pipette';
      item.append(icon, name, ext);
      item.addEventListener('click', () => selectProtocol(item, protocol.filename));
      list.appendChild(item);
    });
  }

  function selectProtocol(el, filename) {
    document.querySelectorAll('.protocol-item').forEach(i => i.classList.remove('selected'));
    el.classList.add('selected');
    selected = filename;

    const nameEl = document.getElementById('selectionName');
    nameEl.textContent = filename.slice(0, -'.pipette'.length);
    nameEl.classList.remove('placeholder');
    document.getElementById('runBtn').disabled = App.isRunActive(App.getStatus().status);
    document.getElementById('checkBtn').disabled = false;
    document.getElementById('findingsList').innerHTML = '';
  }

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
      renderTips(body.data && body.data.tips ? body.data.tips : {});
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

  // Tips each box must supply, so an operator can top a box up before Run.
  function renderTips(tips) {
    const list = document.getElementById('findingsList');
    list.insertAdjacentHTML('beforeend', Object.entries(tips).map(([box, t]) => `
      <div class="finding-item info tip-count">
        <span class="finding-severity">tips</span>
        <span class="finding-message">${box}: needs ${t.needed} of ${t.left} left</span>
      </div>
    `).join(''));
  }

  // ── time left: elapsed running time over progress made, extrapolated.
  // Paused time doesn't count. Client-side only; resets with each run. ─────
  let eta = null; // { start, startProgress, pausedMs, pausedAt }

  function timeLeft(progress, paused) {
    const now = Date.now();
    if (!eta) eta = { start: now, startProgress: progress, pausedMs: 0, pausedAt: null };
    if (paused && eta.pausedAt === null) eta.pausedAt = now;
    if (!paused && eta.pausedAt !== null) {
      eta.pausedMs += now - eta.pausedAt;
      eta.pausedAt = null;
    }
    const activeMs = (eta.pausedAt ?? now) - eta.start - eta.pausedMs;
    const done = progress - eta.startProgress;
    if (done < 0.005 || activeMs < 5000) return null; // too little to go on
    return (activeMs / done) * (1 - progress);
  }

  function formatDuration(ms) {
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ${s % 60}s`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
  }

  function renderProgress(data, active) {
    const bar = document.getElementById('progressBar');
    const label = document.getElementById('progressLabel');
    const p = data.progress;
    const known = active && typeof p === 'number';
    bar.classList.toggle('determinate', known);
    bar.style.width = known ? `${Math.floor(p * 100)}%` : '';
    if (!active) eta = null;
    if (!known) {
      label.textContent = '';
      return;
    }
    const left = timeLeft(p, !!data.paused);
    const percent = `${Math.floor(p * 100)}%`;
    label.textContent = left === null ? percent : `${percent} · ~${formatDuration(left)} left`;
  }

  // ── Pause/Resume and Cancel ────────────────────────────────────────────
  let paused = false;

  async function runControl(action) {
    if (action === 'cancel' && !window.confirm(
      'Cancel this protocol? Cancel is not an emergency stop.'
    )) return;
    await fetch(`/run/${action}`, { method: 'POST' });
  }

  document.getElementById('pauseBtn').addEventListener(
    'click', () => runControl(paused ? 'resume' : 'pause'));
  document.getElementById('cancelBtn').addEventListener(
    'click', () => runControl('cancel'));

  // ── detailed status card (Run-page-specific; the compact pill + global
  // paused-run banner in the header are app.js's job) ─────────────────────
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

    const active = App.isRunActive(s);
    paused = active && !!data.paused;
    icon.classList.toggle('spinning', active && !paused);
    bar.classList.toggle('active', active);
    btn.disabled = active || !selected;
    renderProgress(data, active);

    const pauseBtn = document.getElementById('pauseBtn');
    pauseBtn.textContent = paused ? 'Resume' : 'Pause';
    pauseBtn.disabled = !active;
    document.getElementById('cancelBtn').disabled = !active;
  }

  App.onStatus(renderStatusCard);
  App.registerPage('run', {});

  loadProtocols();
})();
