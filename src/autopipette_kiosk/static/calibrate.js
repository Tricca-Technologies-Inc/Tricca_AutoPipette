// Calibrate page (issue #26): a step-by-step renderer over the daemon's
// `calibrate.*` session, the second renderer beside `tap`'s `calibrate`.
// The session (targets, commanded travel, masses, which step is due) lives
// in the daemon; this page only shows `data.step` and posts the one action
// that step allows, so a reload or a tab switch resumes where it left off.
// While a run holds the config lock every control is disabled, same as the
// Settings page.
(() => {
  const LOCK_REASON = 'Locked while a protocol is running.';
  let locked = false;
  let session = { active: false };

  const $ = id => document.getElementById(id);

  async function call(method, url, body) {
    try {
      const res = await fetch(url, {
        method,
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body: body ? JSON.stringify(body) : undefined,
      });
      const json = await res.json();
      // A raised daemon error (e.g. not homed) comes back as {detail}.
      if (!res.ok) return { ok: false, message: json.detail || 'Failed', data: null };
      return json;
    } catch (e) {
      return { ok: false, message: e.message, data: null };
    }
  }

  function feedback(result) {
    const el = $('calFeedback');
    const text = result.data && result.data.reason === 'run_active'
      ? LOCK_REASON : result.message || '';
    el.textContent = text;
    el.classList.toggle('error', !result.ok);
  }

  // Apply a step's result: keep the session it carries, then re-render.
  async function act(method, url, body) {
    const result = await call(method, url, body);
    feedback(result);
    if (result.data && 'active' in result.data) session = result.data;
    render(result.data && result.data.fit ? result.data : null);
    return result;
  }

  // ── rendering ────────────────────────────────────────────────────────
  function fmt(v, digits) {
    return v === null || v === undefined ? '—' : Number(v).toFixed(digits);
  }

  function render(preview) {
    $('calSetup').hidden = session.active;
    $('calSession').hidden = !session.active;
    if (!session.active) { applyLock(); return; }

    const n = session.targets_ul.length;
    const step = session.step;
    const title = step === 'dispense' || step === 'record'
      ? `Point ${session.index + 1} of ${n}: ${fmt(session.targets_ul[session.index], 1)} µL target`
      : `All ${n} points measured`;
    $('calStepTitle').textContent = title;
    $('calStepTitle').dataset.step = step;
    $('calTarget').textContent =
      `${session.config_category}/${session.config_file} · ${session.source} → ${session.dest}`;

    const rows = session.targets_ul.map((t, i) => {
      const p = session.points[i] || {};
      return `<tr data-index="${i}"><td>${i + 1}</td><td>${fmt(t, 2)}</td>`
        + `<td>${fmt(p.travel_mm, 4)}</td><td>${fmt(p.mass_g, 4)}</td>`
        + `<td>${fmt(p.volume_ul, 2)}</td></tr>`;
    });
    $('calPoints').innerHTML = rows.join('');

    $('calDispenseBtn').hidden = step !== 'dispense';
    $('calRecordRow').hidden = step !== 'record';
    $('calPreviewBtn').hidden = step !== 'preview' && step !== 'commit';
    $('calCommitBtn').hidden = step !== 'commit';
    if (step === 'record') $('calMassInput').value = '';
    if (preview) renderFit(preview);
    else if (step !== 'commit') $('calFit').innerHTML = '';
    applyLock();
  }

  function renderFit(data) {
    const line = c => `travel_mm = ${fmt(c.slope, 6)} × µL + ${fmt(c.intercept, 6)}`;
    $('calFit').innerHTML =
      `<div><span class="cal-fit-label">New</span> ${line(data.fit)}</div>`
      + (data.current
        ? `<div><span class="cal-fit-label">Current</span> ${line(data.current)}</div>`
        : '');
  }

  async function loadLocations() {
    const result = await call('GET', '/locations');
    const names = ((result.data && result.data.locations) || []).map(l => l.name);
    for (const id of ['calSourceSelect', 'calDestSelect']) {
      const sel = $(id);
      const keep = sel.value;
      sel.innerHTML = '<option value="">Select…</option>'
        + names.map(n => `<option value="${n}">${n}</option>`).join('');
      if (names.includes(keep)) sel.value = keep;
    }
  }

  async function onShow() {
    await loadLocations();
    const result = await call('GET', '/calibrate');
    if (result.data) session = result.data;
    render(null);
  }

  // ── actions ──────────────────────────────────────────────────────────
  function start() {
    const source = $('calSourceSelect').value;
    const dest = $('calDestSelect').value;
    if (!source || !dest) {
      feedback({ ok: false, message: 'Choose a source and a destination.' });
      return;
    }
    const raw = $('calVolumesInput').value.trim();
    const volumes = raw ? raw.split(/[\s,]+/).map(Number) : null;
    if (volumes && volumes.some(v => !Number.isFinite(v))) {
      feedback({ ok: false, message: 'Volumes must be numbers, e.g. 10, 30, 50.' });
      return;
    }
    act('POST', '/calibrate/start', { source, dest, volumes_ul: volumes });
  }

  function record() {
    const mass = Number($('calMassInput').value);
    // An empty field is Number('') === 0: refuse it here rather than send it.
    if (!$('calMassInput').value.trim() || !Number.isFinite(mass) || mass <= 0) {
      feedback({ ok: false, message: 'Enter the measured mass in grams.' });
      return;
    }
    act('POST', '/calibrate/record', { mass_g: mass });
  }

  function applyLock() {
    $('page-calibrate').querySelectorAll('input, select, button').forEach(el => {
      el.disabled = locked;
    });
    $('calLockBanner').classList.toggle('active', locked);
  }

  App.onStatus(data => {
    locked = !!data.config_locked;
    applyLock();
  });

  document.addEventListener('DOMContentLoaded', () => {
    $('calStartBtn').addEventListener('click', start);
    $('calDispenseBtn').addEventListener('click', () => act('POST', '/calibrate/dispense'));
    $('calRecordBtn').addEventListener('click', record);
    $('calMassInput').addEventListener('keydown', e => { if (e.key === 'Enter') record(); });
    $('calPreviewBtn').addEventListener('click', () => act('POST', '/calibrate/preview'));
    $('calCommitBtn').addEventListener('click', () => act('POST', '/calibrate/commit'));
    $('calAbortBtn').addEventListener('click', () => act('POST', '/calibrate/abort'));
  });

  App.registerPage('calibrate', { onShow });
})();
