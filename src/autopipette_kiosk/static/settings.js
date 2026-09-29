// Settings page (issue #33 slice c): a renderer over `GET /settings`
// (`config.settings`), which reports every editable field, its bounds, and
// the `config.set_value` target an edit must be written to. No config logic
// lives here: a field edit posts that target back to `/settings/set`, and
// the daemon enforces the same bounds again server-side.
//
// Pipette and gantry fields are high-risk: bounds are checked here first and
// a Save needs an explicit confirm. Liquid fields are low-risk: saved on
// change, no confirm. While `config_locked` is set on the shared status
// stream, every control is disabled with the reason shown.
(() => {
  const LOCK_REASON = 'Locked while a protocol is running.';
  let locked = false;

  async function post(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return res.json();
  }

  // A refused write's text: the run-lock gets the same wording as the
  // banner, anything else its own message.
  function resultMessage(result) {
    if (result.data && result.data.reason === 'run_active') return LOCK_REASON;
    return result.message || 'Failed';
  }

  function showMsg(el, text, isError) {
    el.textContent = text;
    el.classList.toggle('error', !!isError);
  }

  function showHomeRequired() {
    document.getElementById('settingsHomeBanner').classList.add('active');
  }

  // ── data loading ─────────────────────────────────────────────────────
  async function loadSettings() {
    const root = document.getElementById('settingsContent');
    try {
      const res = await fetch('/settings');
      const result = await res.json();
      if (!result.ok) {
        root.innerHTML = `<div class="tips-empty">${result.message || 'Failed to load settings'}</div>`;
        return;
      }
      render(result.data);
    } catch (e) {
      root.innerHTML = '<div class="tips-empty">Failed to load settings</div>';
    }
  }

  function render(data) {
    const root = document.getElementById('settingsContent');
    root.innerHTML = '';
    const columns = document.createElement('div');
    columns.className = 'settings-columns';
    columns.appendChild(renderSystem(data));
    columns.appendChild(renderPipette(data.pipette));
    columns.appendChild(renderPanel('Gantry', 'settingsGantry', data.gantry.fields, true));
    root.appendChild(columns);
    root.appendChild(renderLiquids(data.liquids));
    applyLock();
  }

  function panel(title, id) {
    const el = document.createElement('div');
    el.className = 'move-panel settings-panel';
    el.id = id;
    el.innerHTML = `<div class="panel-header">${title}</div>`;
    return el;
  }

  // A <select> of config files plus an action button, e.g. "Switch".
  function picker(id, files, current, label, onPick) {
    const row = document.createElement('div');
    row.className = 'settings-picker';
    const select = document.createElement('select');
    select.className = 'move-loc-select';
    select.id = id;
    files.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      if (name === current) opt.selected = true;
      select.appendChild(opt);
    });
    const btn = document.createElement('button');
    btn.className = 'settings-btn';
    btn.textContent = label;
    const msg = document.createElement('div');
    msg.className = 'move-feedback';
    btn.addEventListener('click', () => onPick(select.value, msg));
    row.append(select, btn);
    const wrap = document.createElement('div');
    wrap.append(row, msg);
    return wrap;
  }

  // Load/swap/switch actions all re-render on success, since the whole
  // payload (values, targets) can change.
  async function runAction(url, body, msg, homeRequired) {
    try {
      const result = await post(url, body);
      if (!result.ok) {
        showMsg(msg, resultMessage(result), true);
        return;
      }
      if (homeRequired) showHomeRequired();
      await loadSettings();
    } catch (e) {
      showMsg(msg, e.message, true);
    }
  }

  function renderSystem(data) {
    const el = panel('System profile', 'settingsSystem');
    el.appendChild(picker('settingsSystemSelect', data.system_profiles, data.system_profile,
      'Switch', (filename, msg) =>
        runAction('/settings/switch_system', { filename }, msg, true)));
    return el;
  }

  function renderPipette(pipette) {
    const el = panel(`Pipette · ${pipette.name}`, 'settingsPipette');
    el.appendChild(picker('settingsPipetteSelect', pipette.files, pipette.file,
      'Load', (filename, msg) =>
        runAction('/settings/load_pipette', { filename }, msg, true)));
    pipette.fields.forEach(f => el.appendChild(fieldRow(f, true)));
    return el;
  }

  function renderPanel(title, id, fields, highRisk) {
    const el = panel(title, id);
    fields.forEach(f => el.appendChild(fieldRow(f, highRisk)));
    return el;
  }

  function renderLiquids(liquids) {
    const el = panel('Liquids', 'settingsLiquids');
    el.appendChild(picker('settingsLiquidSelect', liquids.files, null, 'Load',
      (filename, msg) => runAction('/settings/load_liquid', { filename }, msg, false)));
    const grid = document.createElement('div');
    grid.className = 'settings-liquids';
    liquids.loaded.forEach(liquid => {
      const card = document.createElement('div');
      card.className = 'settings-liquid';
      card.dataset.liquid = liquid.name;
      const head = document.createElement('div');
      head.className = 'settings-liquid-head';
      head.innerHTML = `<span class="tipbox-name">${liquid.name}</span>` +
        (liquid.active ? '<span class="settings-active">active</span>' : '');
      const msg = document.createElement('div');
      msg.className = 'move-feedback';
      if (!liquid.active) { // the active liquid can't be unloaded
        const unload = document.createElement('button');
        unload.className = 'settings-btn subtle';
        unload.textContent = 'Unload';
        unload.addEventListener('click', () =>
          runAction('/settings/unload_liquid', { name: liquid.name }, msg, false));
        head.appendChild(unload);
      }
      card.append(head, msg);
      liquid.fields.forEach(f => card.appendChild(fieldRow(f, false)));
      grid.appendChild(card);
    });
    el.appendChild(grid);
    return el;
  }

  // ── one editable field ───────────────────────────────────────────────
  function fieldRow(field, highRisk) {
    const row = document.createElement('div');
    row.className = 'settings-field';
    row.dataset.key = field.key;

    const label = document.createElement('label');
    label.textContent = field.key;
    const input = document.createElement('input');
    input.type = 'number';
    input.step = 'any';
    input.className = 'coord-input';
    input.value = field.value === null ? '' : field.value;
    const msg = document.createElement('div');
    msg.className = 'move-feedback';

    const line = document.createElement('div');
    line.className = 'settings-field-line';
    line.appendChild(input);

    // Any bounded field (high-risk, or a liquid's syringe-speed override,
    // issue #120) gets the native range hint; the daemon enforces it anyway.
    if (field.min !== null) {
      input.min = field.min;
      input.max = field.max;
    }
    if (highRisk) {
      const range = document.createElement('span');
      range.className = 'settings-range';
      range.textContent = `${field.min}–${field.max}`;
      const save = document.createElement('button');
      save.className = 'settings-btn';
      save.textContent = 'Save';
      save.addEventListener('click', () => confirmHighRisk(field, input, msg, line));
      line.append(range, save);
    } else {
      input.addEventListener('change', () => {
        const text = input.value.trim();
        // Empty means "no override": defer to the pipette's default.
        write(field, text === '' ? null : Number(text), msg, false);
      });
    }
    row.append(label, line, msg);
    return row;
  }

  // Bounds first, then an explicit confirm step, then the write.
  function confirmHighRisk(field, input, msg, line) {
    const value = Number(input.value);
    if (input.value.trim() === '' || !Number.isFinite(value)) {
      showMsg(msg, 'Enter a number.', true);
      return;
    }
    if (value < field.min || value > field.max) {
      showMsg(msg, `Out of range: must be ${field.min}–${field.max}.`, true);
      return;
    }
    showMsg(msg, `Change ${field.key} from ${field.value} to ${value}?`, false);
    const confirmBtn = document.createElement('button');
    confirmBtn.className = 'settings-btn confirm';
    confirmBtn.textContent = 'Confirm';
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'settings-btn subtle';
    cancelBtn.textContent = 'Cancel';
    const done = () => { confirmBtn.remove(); cancelBtn.remove(); };
    confirmBtn.addEventListener('click', async () => {
      done();
      if (await write(field, value, msg, true)) field.value = value;
    });
    cancelBtn.addEventListener('click', () => {
      done();
      input.value = field.value;
      showMsg(msg, '', false);
    });
    msg.append(' ', confirmBtn, cancelBtn);
  }

  async function write(field, value, msg, homeRequired) {
    try {
      const result = await post('/settings/set', {
        category: field.category,
        filename: field.filename,
        key_path: field.key_path,
        value,
      });
      if (!result.ok) {
        showMsg(msg, resultMessage(result), true);
        return false;
      }
      showMsg(msg, 'Saved.', false);
      if (homeRequired) showHomeRequired();
      return true;
    } catch (e) {
      showMsg(msg, e.message, true);
      return false;
    }
  }

  // ── run-lock: disable everything, say why ────────────────────────────
  function applyLock() {
    const page = document.getElementById('page-settings');
    page.querySelectorAll('input, select, button').forEach(el => { el.disabled = locked; });
    document.getElementById('settingsLockBanner').classList.toggle('active', locked);
  }

  App.onStatus(data => {
    locked = !!data.config_locked;
    applyLock();
  });

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('homeBtn').addEventListener('click', () => {
      document.getElementById('settingsHomeBanner').classList.remove('active');
    });
  });

  App.registerPage('settings', { onShow: loadSettings });
})();
