// One-command-at-a-time kiosk adapter to the daemon's restricted dispatcher.
(() => {
  const form = document.getElementById('commandForm');
  const input = document.getElementById('commandInput');
  const button = document.getElementById('commandSendBtn');
  const availability = document.getElementById('commandAvailability');
  const output = document.getElementById('commandOutput');
  let pending = false;

  function renderAvailability() {
    const active = App.isRunActive(App.getStatus().status);
    const connected = App.isConnected();
    button.disabled = pending || active || !connected || !input.value.trim();
    availability.textContent = !connected ? 'Control daemon not connected.' :
      active ? 'Commands are locked while a protocol is running.' : '';
  }

  function showResult(command, message, data, error) {
    const entry = document.createElement('div');
    entry.className = `command-result${error ? ' error' : ''}`;
    const heading = document.createElement('strong');
    heading.textContent = `> ${command}`;
    const result = document.createElement('div');
    result.textContent = message;
    entry.append(heading, result);
    if (data) {
      const details = document.createElement('pre');
      details.textContent = JSON.stringify(data, null, 2);
      entry.appendChild(details);
    }
    output.prepend(entry);
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const command = input.value.trim();
    if (!command || pending || !App.isConnected() ||
        App.isRunActive(App.getStatus().status)) return;
    pending = true;
    renderAvailability();
    try {
      const response = await fetch('/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command }),
      });
      const result = await response.json();
      if (!response.ok) {
        const detail = result.detail || `HTTP ${response.status}`;
        const message = response.status >= 500
          ? `Outcome not confirmed: ${detail}. Check the machine before retrying.`
          : detail;
        showResult(command, message, null, true);
      } else {
        showResult(command, result.message || (result.ok ? 'Request accepted.' : 'Refused.'),
          result.data, !result.ok);
      }
    } catch (error) {
      showResult(command,
        `Outcome not confirmed: ${error.message}. Check the machine before retrying.`,
        null, true);
    } finally {
      pending = false;
      renderAvailability();
    }
  });

  input.addEventListener('input', renderAvailability);
  App.onStatus(renderAvailability);
  App.registerPage('commands', {});
})();
