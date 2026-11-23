// Apply the saved theme before first paint to avoid a light/dark flash.
// Kept as a file (not inline) so production can use a strict script-src 'self' policy.
(function () {
  try {
    var mode = localStorage.getItem('rf_theme_mode') || 'system';
    var accent = localStorage.getItem('rf_accent_color') || 'indigo';
    var dark = mode === 'dark' || (mode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.dataset.accent = accent;
  } catch (e) {}
})();
