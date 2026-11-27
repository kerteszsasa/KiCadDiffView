// Run before the stylesheet so a saved preference applies to the first paint.
(() => {
  'use strict';
  const key = 'kicaddiffview.theme';
  const choices = new Set(['light', 'dark', 'system']);
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try {
    const saved = localStorage.getItem(key);
    if (choices.has(saved)) preference = saved;
  } catch {
    // Themes also work when browser storage is unavailable.
  }

  function apply() {
    const theme = preference === 'system' ? (system.matches ? 'dark' : 'light') : preference;
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
  }

  apply();
  system.addEventListener('change', () => {
    if (preference === 'system') apply();
  });
  document.addEventListener('DOMContentLoaded', () => {
    const select = document.getElementById('theme-select');
    if (!select) return;
    select.value = preference;
    select.addEventListener('change', () => {
      preference = choices.has(select.value) ? select.value : 'system';
      select.value = preference;
      apply();
      try {
        localStorage.setItem(key, preference);
      } catch {
        // Keep the selected theme for this page even if it cannot be saved.
      }
    });
  });
})();
