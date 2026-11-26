// Header pipette pill: names the active pipette file on every tab, and
// opens a list of pipette files to swap to (`POST /settings/load_pipette`).
// Reads `GET /settings`, the same payload the Settings page renders. A swap
// invalidates homing; the daemon says so on the shared status stream and
// the Move page shows it. Disabled while `config_locked`, like Settings.
const PipettePill = (() => {
  const pill = document.getElementById('pipettePill');
  const label = document.getElementById('pipettePillLabel');
  const switcher = document.getElementById('pipetteSwitcher');
  const options = document.getElementById('pipetteOptions');
  const feedback = document.getElementById('pipetteFeedback');
  let pipette = null;

  const stem = file => file.replace(/\.json$/, '');

  async function refresh() {
    try {
      const result = await (await fetch('/settings')).json();
      if (!result.ok) return;
      pipette = result.data.pipette;
      // An inlined pipette block has no file; fall back to its model name.
      label.textContent = pipette.file ? stem(pipette.file) : pipette.name;
    } catch (e) {
      // daemon not reachable yet: keep the last label
    }
  }

  function close() { switcher.classList.remove('open'); }

  function open() {
    options.replaceChildren(...pipette.files.map(file => {
      const btn = document.createElement('button');
      btn.className = 'pipette-option';
      btn.classList.toggle('active', file === pipette.file);
      btn.textContent = stem(file);
      btn.addEventListener('click', () => load(file));
      return btn;
    }));
    feedback.textContent = '';
    switcher.classList.add('open');
  }

  async function load(filename) {
    try {
      const res = await fetch('/settings/load_pipette', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      });
      const result = await res.json();
      if (!result.ok) {
        feedback.textContent = result.message || 'Failed';
        return;
      }
      close();
      await refresh();
    } catch (e) {
      feedback.textContent = e.message;
    }
  }

  pill.addEventListener('click', e => {
    e.stopPropagation();
    if (switcher.classList.contains('open')) close();
    else if (pipette) open();
  });
  document.addEventListener('click', e => {
    if (!switcher.contains(e.target)) close();
  });

  App.onStatus(data => {
    pill.disabled = !!data.config_locked;
    if (pill.disabled) close();
    if (!pipette) refresh(); // the daemon wasn't up for the first fetch
  });

  refresh();
  return { refresh };
})();
