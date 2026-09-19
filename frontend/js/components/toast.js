/* Korte meldinger nederst på skjermen ("Scene aktivert", "Fikk ikke kontakt ...") */

export function showToast(message, { error = false, ms = 3500 } = {}) {
  const root = document.getElementById('toast-root');
  if (!root) return;
  const el = document.createElement('div');
  el.className = 'toast' + (error ? ' toast-error' : '');
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), ms);
}
