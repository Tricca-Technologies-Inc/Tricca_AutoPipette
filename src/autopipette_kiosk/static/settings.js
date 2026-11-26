// Settings page (issue #33 slice c): a renderer over `GET /settings`
// (`config.settings`), which reports every editable field, its bounds, and
// the `config.set_value` target an edit must be written to. No config logic
// lives here: a field edit posts that target back to `/settings/set`, and
// the daemon enforces the same bounds again server-side.
//
// Pipette and gantry values are shown read-only: they change by switching
// the system profile here, or the pipette from the header pill (pipette.js).
// `tap`'s `set_config` still edits them. Liquid fields save on change, no
// confirm. While `config_locked` is set on the shared status stream, every
// control is disabled with the reason shown.
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
        root.innerHTML = '<div class="tips-empty"></div>';
        root.firstChild.textContent = result.message || 'Failed to load settings';
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
    columns.appendChild(renderValues(`Pipette · ${data.pipette.name}`, 'settingsPipette',
      data.pipette.fields));
    columns.appendChild(renderValues('Gantry', 'settingsGantry', data.gantry.fields));
    root.appendChild(columns);
    root.appendChild(renderLiquids(data.liquids));
    applyLock();
  }

  function panel(title, id) {
    const el = document.createElement('div');
    el.className = 'move-panel settings-panel';
    el.id = id;
    el.innerHTML = '<div class="panel-header"></div>';
    el.firstChild.textContent = title;
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

  // A profile switch re-renders on success, since the whole payload
  // (values, targets) can change, and invalidates homing.
  async function runAction(url, body, msg) {
    try {
      const result = await post(url, body);
      if (!result.ok) {
        showMsg(msg, resultMessage(result), true);
        return;
      }
      showHomeRequired();
      await loadSettings();
      PipettePill.refresh();
    } catch (e) {
      showMsg(msg, e.message, true);
    }
  }

  function renderSystem(data) {
    const el = panel('System profile', 'settingsSystem');
    el.appendChild(picker('settingsSystemSelect', data.system_profiles, data.system_profile,
      'Switch', (filename, msg) =>
        runAction('/settings/switch_system', { filename }, msg)));
    return el;
  }

  function renderValues(title, id, fields) {
    const el = panel(title, id);
    fields.forEach(field => {
      const row = document.createElement('div');
      row.className = 'settings-field';
      row.dataset.key = field.key;
      const label = document.createElement('label');
      label.textContent = field.key;
      const value = document.createElement('span');
      value.className = 'settings-value';
      value.textContent = field.value === null ? '—' : field.value;
      row.append(label, value);
      el.appendChild(row);
    });
    return el;
  }

  function renderLiquids(liquids) {
    const el = panel('Liquids', 'settingsLiquids');
    const grid = document.createElement('div');
    grid.className = 'settings-liquids';
    liquids.loaded.forEach(liquid => {
      const card = document.createElement('div');
      card.className = 'settings-liquid';
      card.dataset.liquid = liquid.name;
      const head = document.createElement('div');
      head.className = 'settings-liquid-head';
      const nameEl = document.createElement('span');
      nameEl.className = 'tipbox-name';
      nameEl.textContent = liquid.name;
      head.appendChild(nameEl);
      if (liquid.active) head.insertAdjacentHTML('beforeend', '<span class="settings-active">active</span>');
      card.appendChild(head);
      liquid.fields.forEach(f => card.appendChild(fieldRow(f)));
      grid.appendChild(card);
    });
    el.appendChild(grid);
    return el;
  }

  // ── one editable field ───────────────────────────────────────────────
  function fieldRow(field) {
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

    // A bounded field (a liquid's syringe-speed override, issue #120) gets
    // the native range hint; the daemon enforces it anyway.
    if (field.min !== null) {
      input.min = field.min;
      input.max = field.max;
    }
    input.addEventListener('change', () => {
      const text = input.value.trim();
      // Empty means "no override": defer to the pipette's default.
      write(field, text === '' ? null : Number(text), msg);
    });
    row.append(label, line, msg);
    return row;
  }

  async function write(field, value, msg) {
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

  let shown = false;
  document.addEventListener('pipette-changed', () => { if (shown) loadSettings(); });

  App.registerPage('settings', {
    onShow: () => { shown = true; loadSettings(); },
    onHide: () => { shown = false; },
  });
})();
