// Pipette indicator pill + switcher dropdown.
//
// Shows the active pipette name in the header on every tab.
// Tapping the pill opens a dropdown listing available pipette files;
// tapping one calls /settings/load_pipette and refreshes.
//
// Data comes from /settings (same endpoint the Settings page uses) so
// no new backend route is needed. Refreshes on tab focus and after a
// successful load.
(() => {
  const pill      = document.getElementById('pipettePill');
  const label     = document.getElementById('pipettePillLabel');
  const switcher  = document.getElementById('pipetteSwitcher');
  const optionsEl = document.getElementById('pipetteOptions');

  let activePipette = '';   // bare filename, e.g. "TysonP100.json"
  let activeName    = '';   // display name, e.g. "TysonP100"
  let allFiles      = [];   // all available .json files
  let open          = false;
  let loading       = false;

  // ── Fetch current pipette state from /settings ──────────────────────────

  async function refresh() {
    try {
      const res  = await fetch('/settings');
      const body = await res.json();
      const pip  = body?.data?.pipette;
      if (!pip) return;
      activeName    = pip.name    || '';
      activePipette = pip.file    || '';
      allFiles      = pip.files   || [];
      render();
    } catch (_) {
      // daemon not connected — leave label as-is
    }
  }

  // ── Render pill label ────────────────────────────────────────────────────

  function render() {
    // Shorten "TysonP1000" → "P1000" for tight header space
    const short = activeName.replace(/^[A-Za-z]+(?=[A-Z])/, '');
    label.textContent = short || activeName || '—';
    pill.title = `Active pipette: ${activeName} — tap to switch`;
  }

  // ── Build dropdown options ───────────────────────────────────────────────

  function buildOptions() {
    optionsEl.innerHTML = '';
    if (allFiles.length <= 1) {
      const note = document.createElement('div');
      note.className = 'pipette-switcher-note';
      note.textContent = 'Only one pipette config available.';
      optionsEl.appendChild(note);
      return;
    }
    allFiles.forEach(file => {
      const btn = document.createElement('button');
      btn.className = 'pipette-option' + (file === activePipette ? ' active' : '');
      btn.textContent = file.replace(/\.json$/i, '');
      btn.addEventListener('click', () => loadPipette(file));
      optionsEl.appendChild(btn);
    });
  }

  // ── Open / close ─────────────────────────────────────────────────────────

  function openSwitcher() {
    if (loading) return;
    buildOptions();
    open = true;
    switcher.classList.add('open');
  }

  function closeSwitcher() {
    open = false;
    switcher.classList.remove('open');
  }

  pill.addEventListener('click', e => {
    e.stopPropagation();
    open ? closeSwitcher() : openSwitcher();
  });

  // Close when clicking outside
  document.addEventListener('click', e => {
    if (open && !switcher.contains(e.target)) closeSwitcher();
  });

  // ── Load a pipette ───────────────────────────────────────────────────────

  async function loadPipette(filename) {
    if (loading) return;
    closeSwitcher();
    loading = true;
    pill.classList.add('switching');
    label.textContent = '…';
    try {
      const res = await fetch('/settings/load_pipette', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      });
      const body = await res.json();
      if (!body.ok) {
        label.textContent = 'Error';
        setTimeout(refresh, 1500);
      } else {
        await refresh();
      }
    } catch (_) {
      label.textContent = 'Error';
      setTimeout(refresh, 1500);
    } finally {
      loading = false;
      pill.classList.remove('switching');
    }
  }

  // ── Refresh on tab visibility and status changes ─────────────────────────

  // Refresh when the page becomes visible (e.g. switching back to this tab)
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refresh();
  });

  // Also refresh whenever the kiosk reconnects to the daemon
  if (window.App) {
    App.onStatus(status => {
      // Refresh when daemon reconnects
      if (status.daemon_connected && !activeName) refresh();
    });
  }

  // Initial load — wait for App to be ready
  document.addEventListener('DOMContentLoaded', () => {
    // Small delay so App initialises first
    setTimeout(refresh, 500);
  });

  // Expose refresh so settings.js can call it after a load_pipette
  window.PipetteIndicator = { refresh };
})();
