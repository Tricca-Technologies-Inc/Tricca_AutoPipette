// Run page: protocol list, run button, detailed status card.
//
// Subscribes to App.onStatus rather than owning any WebSocket connection or
// run-status state itself (app.js owns both, since the header's compact
// status pill and breakpoint banner need the same data regardless of which
// tab is active -- see issue #25).
(() => {
  let selected = null;
  let protocols = [];
  let folder = '';
  let pendingAction = null;
  let pendingTimer = null;
  let pendingStart = null;
  let startTimer = null;

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
      if (folder === 'legacy' || folder.startsWith('legacy/')) {
        const warning = document.createElement('div');
        warning.className = 'protocol-legacy-warning';
        warning.textContent = 'Legacy protocols are unverified on hardware. Review the protocol and rig configuration before use.';
        list.appendChild(warning);
      }
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
    renderStatusCard(App.getStatus());
    document.getElementById('checkBtn').disabled = false;
    document.getElementById('findingsList').innerHTML = '';
  }

  // ── run ────────────────────────────────────────────────────────────────
  document.getElementById('runBtn').addEventListener('click', async () => {
    const data = App.getStatus();
    if (!App.isConnected() || pendingStart || pendingAction) return;
    if (App.isRunActive(data.status)) {
      if (data.phase === 'printing') sendRunControl('pause');
      else if (data.phase === 'paused') sendRunControl('resume');
      return;
    }
    if (!selected) return;
    const request = {};
    pendingStart = request;
    const feedback = document.getElementById('runControlFeedback');
    feedback.textContent = '';
    renderStatusCard(data);
    try {
      const res = await fetch('/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: selected }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      if (pendingStart === request) {
        feedback.textContent = 'Run requested; waiting for confirmation.';
        startTimer = setTimeout(() => {
          if (pendingStart !== request) return;
          pendingStart = null;
          feedback.textContent = 'Run was not confirmed. Check the machine state.';
          renderStatusCard(App.getStatus());
        }, 5000);
      }
    } catch (e) {
      if (pendingStart === request) {
        pendingStart = null;
        feedback.textContent = `Run failed: ${e.message}`;
        renderStatusCard(App.getStatus());
      }
    }
  });

  async function sendRunControl(action) {
    const data = App.getStatus();
    if (!App.isConnected() || !data.run_id || pendingAction) return;
    if (action === 'cancel' && !window.confirm(
      'Cancel this protocol? Cancel is not an emergency stop.'
    )) return;
    const request = { action, runId: data.run_id };
    pendingAction = request;
    const feedback = document.getElementById('runControlFeedback');
    feedback.textContent = `Sending ${action} request…`;
    renderStatusCard(data);
    try {
      const res = await fetch(`/run/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: data.run_id }),
      });
      const result = await res.json();
      if (!res.ok) throw new Error(result.detail || `HTTP ${res.status}`);
      if (result.refusal || (action === 'resume' && result.message?.includes('resume refused'))) {
        throw new Error(result.message);
      }
      if (pendingAction === request) {
        feedback.textContent = `${action} requested; waiting for confirmation.`;
        pendingTimer = setTimeout(() => {
          if (pendingAction !== request) return;
          pendingAction = null;
          feedback.textContent = `${action} was not confirmed. Check the machine state.`;
          renderStatusCard(App.getStatus());
        }, 5000);
      }
    } catch (e) {
      if (pendingAction === request) {
        pendingAction = null;
        feedback.textContent = `${action} failed: ${e.message}`;
        renderStatusCard(App.getStatus());
      }
    }
  }

  document.getElementById('cancelBtn').addEventListener('click', () => sendRunControl('cancel'));

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
    const progressLabel = document.getElementById('progressLabel');
    const btn   = document.getElementById('runBtn');

    const s = data.status;
    const { label, icon: iconChar } = App.describeStatus(s);

    icon.className  = `status-icon ${s}`;
    state.className = `status-state ${s}`;
    icon.textContent  = iconChar;
    state.textContent = data.phase === 'paused' ? 'Paused' : label;
    msg.textContent   = data.message || '';

    if (pendingStart && App.isRunActive(s)) {
      clearTimeout(startTimer);
      pendingStart = null;
      document.getElementById('runControlFeedback').textContent = '';
    }
    if (pendingAction && (
      data.run_id !== pendingAction.runId ||
      s !== 'running' ||
      (pendingAction.action === 'pause' && data.phase === 'paused') ||
      (pendingAction.action === 'resume' && data.phase === 'printing')
    )) {
      clearTimeout(pendingTimer);
      pendingAction = null;
      document.getElementById('runControlFeedback').textContent = '';
    }
    const active = App.isRunActive(s);
    const available = active && App.isConnected() && !!data.run_id && !pendingAction;
    const paused = active && data.phase === 'paused';
    document.getElementById('runBtnLabel').textContent =
      active ? (paused ? 'Resume' : 'Pause') : 'Run protocol';
    document.getElementById('runBtnIcon').setAttribute(
      'd', active && !paused ? 'M6 4h4v16H6zM14 4h4v16h-4z' : 'M8 5v14l11-7z'
    );
    document.getElementById('cancelBtn').disabled =
      !available || !['preparing', 'printing', 'paused'].includes(data.phase);
    icon.classList.toggle('spinning', active && data.phase !== 'paused');
    const progress = data.progress;
    const known = typeof progress === 'number' && Number.isFinite(progress) && progress >= 0 && progress <= 1;
    bar.hidden = !active && !known;
    if (known) {
      const percent = Math.floor(progress * 100);
      bar.value = percent;
      progressLabel.textContent = `Estimated G-code file progress: ${percent}%`;
    } else {
      bar.removeAttribute('value');
      progressLabel.textContent = active ? 'Progress unavailable' : '';
    }
    btn.disabled = active
      ? !available || !['printing', 'paused'].includes(data.phase)
      : !App.isConnected() || !selected || pendingStart;
  }

  App.onStatus(renderStatusCard);
  App.registerPage('run', {});

  loadProtocols();
})();
