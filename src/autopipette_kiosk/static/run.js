// Protocols page + Run page (Scott's 5" redesign).
//
// Protocols (page-protocols): the protocol list, Check (pre-flight
// findings, issue #88), and Load, which dry-runs the protocol and opens the
// Run page with its description and tip needs. Run (page-run): the loaded
// protocol, the detailed status card, progress, and one Run button that
// becomes Pause and Resume during a run, plus Cancel.
//
// Subscribes to App.onStatus rather than owning any WebSocket connection or
// run-status state itself (app.js owns both, since the header's compact
// status pill and paused-run banner need the same data regardless of which
// tab is active -- see issue #25).
(() => {
  let selected = null; // highlighted on the Protocols page
  let loaded = null;   // on the Run page, what Run starts
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

  const stem = filename => filename.slice(0, -'.pipette'.length);

  function selectProtocol(el, filename) {
    document.querySelectorAll('.protocol-item').forEach(i => i.classList.remove('selected'));
    el.classList.add('selected');
    selected = filename;

    const nameEl = document.getElementById('selectionName');
    nameEl.textContent = stem(filename);
    nameEl.classList.remove('placeholder');
    document.getElementById('checkBtn').disabled = false;
    document.getElementById('loadBtn').disabled = false;
    document.getElementById('findingsList').innerHTML = '';
  }

  async function validate(filename) {
    const res = await fetch('/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    return body.data || {};
  }

  // ── load: dry-run, then show what the protocol does and needs ─────────
  // A tip shortfall is a warning, not a block: Check never disables Run
  // (issue #88), and an empty tipbox pauses the run for a reload anyway.
  document.getElementById('loadBtn').addEventListener('click', async () => {
    if (!selected) return;
    loaded = selected;
    document.getElementById('runProtocolName').textContent = stem(loaded);
    const card = document.getElementById('protocolInfoCard');
    const desc = document.getElementById('protocolInfoDescription');
    const tipsEl = document.getElementById('protocolInfoTips');
    const error = document.getElementById('protocolInfoError');
    card.hidden = true;
    error.hidden = true;
    renderStatusCard(App.getStatus());
    App.switchTo('run');
    try {
      const data = await validate(loaded);
      desc.textContent = data.description || '';
      desc.hidden = !data.description;
      const tips = Object.entries(data.tips || {});
      tipsEl.replaceChildren(...tips.map(([box, t]) => {
        const row = document.createElement('div');
        const short = t.needed > t.left;
        row.className = `protocol-info-tip-row ${short ? 'short' : 'ok'}`;
        row.textContent = `${short ? '✗' : '✓'} ${box}: needs ${t.needed}, has ${t.left}`;
        return row;
      }));
      card.hidden = !data.description && !tips.length;
      if (tips.some(([, t]) => t.needed > t.left)) {
        error.textContent = 'Not enough tips: reload the tipbox and reset it on the Tips tab.';
        error.hidden = false;
      }
    } catch (e) {
      error.textContent = `Could not check the protocol: ${e.message}`;
      error.hidden = false;
    }
  });

  // ── run, pause/resume, cancel ──────────────────────────────────────────
  // A refused request is shown under the buttons; the status card keeps
  // showing what the daemon last reported.
  async function post(path, body) {
    const feedback = document.getElementById('runFeedback');
    feedback.textContent = '';
    try {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!res.ok) feedback.textContent = (await res.json()).detail || `HTTP ${res.status}`;
    } catch (e) {
      feedback.textContent = e.message;
    }
  }

  document.getElementById('runBtn').addEventListener('click', () => {
    const data = App.getStatus();
    if (!App.isRunActive(data.status)) {
      if (loaded) post('/run', { filename: loaded });
      return;
    }
    post(data.paused ? '/run/resume' : '/run/pause');
  });

  document.getElementById('cancelBtn').addEventListener('click', () => {
    if (window.confirm('Cancel this protocol? Cancel is not an emergency stop.')) {
      post('/run/cancel');
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
      const data = await validate(selected);
      renderFindings(data.findings || []);
      renderTips(data.tips || {});
    } catch (e) {
      list.innerHTML = '';
      const item = document.createElement('div');
      item.className = 'finding-item error';
      item.textContent = e.message;
      list.appendChild(item);
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
    bar.hidden = !active;
    if (known) bar.value = Math.floor(p * 100);
    else bar.removeAttribute('value'); // indeterminate
    if (!active) eta = null;
    if (!known) {
      label.textContent = '';
      return;
    }
    const left = timeLeft(p, !!data.paused);
    const percent = `${Math.floor(p * 100)}%`;
    label.textContent = left === null ? percent : `${percent} · ~${formatDuration(left)} left`;
  }

  // ── detailed status card (Run-page-specific; the compact pill + global
  // paused-run banner in the header are app.js's job) ─────────────────────
  function renderStatusCard(data) {
    const icon  = document.getElementById('statusIcon');
    const state = document.getElementById('statusState');
    const msg   = document.getElementById('statusMsg');

    const s = data.status;
    const { label, icon: iconChar } = App.describeStatus(s);
    const active = App.isRunActive(s);
    const paused = active && !!data.paused;

    icon.className  = `status-icon ${s}`;
    state.className = `status-state ${s}`;
    icon.textContent  = iconChar;
    state.textContent = paused ? 'Paused' : label;
    msg.textContent   = data.message || '';
    icon.classList.toggle('spinning', active && !paused);
    renderProgress(data, active);

    document.getElementById('runBtnLabel').textContent =
      active ? (paused ? 'Resume' : 'Pause') : 'Run';
    document.getElementById('runBtnIcon').setAttribute(
      'd', active && !paused ? 'M6 4h4v16H6zM14 4h4v16h-4z' : 'M8 5v14l11-7z');
    document.getElementById('runBtn').disabled = !active && !loaded;
    document.getElementById('cancelBtn').disabled = !active;
  }

  App.onStatus(renderStatusCard);
  App.registerPage('protocols', {});
  App.registerPage('run', {});

  loadProtocols();
})();
