/* Modification History: 1.0.0 | 2026-10-11 | Codex | 复用控制台的显示偏好，首屏绘制前应用。 */
(() => {
  const root = document.documentElement;
  const system = matchMedia('(prefers-color-scheme: dark)');
  let prefs = {};
  try { prefs = JSON.parse(localStorage.getItem('vp-display-preferences') || '{}') || {}; } catch (_) {}
  const theme = ['system', 'dark', 'light', 'contrast'].includes(prefs.theme) ? prefs.theme : 'system';
  const apply = () => {
    root.dataset.theme = theme === 'system' ? (system.matches ? 'dark' : 'light') : theme;
    root.dataset.textSize = ['standard', 'large', 'xlarge'].includes(prefs.size) ? prefs.size : 'large';
  };
  apply();
  system.addEventListener('change', apply);
})();
