// Commands page: one typed command at a time, over POST /command. The daemon
// decides what may run (motion, tips and pipetting only) and runs it through
// the same dispatch as a protocol line; this page only renders the answer.
(() => {
  const form = document.getElementById('commandForm');
  const input = document.getElementById('commandInput');
  const send = document.getElementById('commandSendBtn');
  const output = document.getElementById('commandOutput');
  let locked = false;
  let pending = false;

  function render() {
    send.disabled = locked || pending || !input.value.trim();
    document.getElementById('commandLock').classList.toggle('active', locked);
  }

  // textContent throughout: the result echoes what was typed.
  function show(command, message, error) {
    const entry = document.createElement('div');
    entry.className = error ? 'command-result error' : 'command-result';
    const heading = document.createElement('strong');
    heading.textContent = `> ${command}`;
    const body = document.createElement('div');
    body.textContent = message;
    entry.append(heading, body);
    output.prepend(entry);
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const command = input.value.trim();
    if (!command || locked || pending) return;
    pending = true;
    render();
    try {
      const res = await fetch('/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command }),
      });
      const result = await res.json();
      if (!res.ok) show(command, result.detail || `HTTP ${res.status}`, true);
      else show(command, result.message, !result.ok);
    } catch (e) {
      show(command, `No answer (${e.message}): check the machine before retrying.`, true);
    } finally {
      pending = false;
      render();
    }
  });

  input.addEventListener('input', render);
  App.onStatus((data) => {
    locked = App.isRunActive(data.status);
    render();
  });
  App.registerPage('commands', {});
})();
