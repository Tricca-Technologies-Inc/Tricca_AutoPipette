// Layout toggle: switches between touch-optimised (default) and desktop
// layout by toggling `html.desktop-mode`, which activates style-desktop.css.
// Preference is saved to localStorage so it survives reloads.
//
// Runs before app.js so the class is on <html> before first paint —
// no layout flash on load.
(() => {
  const KEY = 'ap-layout';
  const DESKTOP = 'desktop';
  const TOUCH = 'touch';

  function isDesktop() {
    return document.documentElement.classList.contains('desktop-mode');
  }

  function apply(mode, save) {
    const desktop = mode === DESKTOP;
    document.documentElement.classList.toggle('desktop-mode', desktop);
    const btn = document.getElementById('layoutToggleBtn');
    const lbl = document.getElementById('layoutToggleLabel');
    if (btn) btn.title = desktop
      ? 'Switch to touch layout'
      : 'Switch to desktop layout';
    if (lbl) lbl.textContent = desktop ? 'Touch' : 'Desktop';
    if (save) localStorage.setItem(KEY, mode);
  }

  // Apply saved preference immediately (before paint)
  const saved = localStorage.getItem(KEY);
  if (saved === DESKTOP) apply(DESKTOP, false);

  // Wire up the button once the DOM is ready
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('layoutToggleBtn');
    if (!btn) return;
    // Sync label to whatever was applied above
    apply(isDesktop() ? DESKTOP : TOUCH, false);
    btn.addEventListener('click', () => {
      apply(isDesktop() ? TOUCH : DESKTOP, true);
    });
  });
})();
