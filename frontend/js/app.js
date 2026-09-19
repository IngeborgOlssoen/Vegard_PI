/* Selve dashbordet: leser layout fra backend, lager kortene og holder dem
   oppdatert. Feil i ett kort skal aldri påvirke de andre. */

import { api } from './api.js';
import { getCard } from './cards/index.js';
import { showToast } from './components/toast.js';
import { escapeHtml } from './components/sheet.js';

// Kort som er tilgjengelige. Importen registrerer dem i registeret.
import './cards/registry.js';

const OFFLINE_AFTER_MS = 60_000;   // vis "ingen kontakt"-overlay etter så lang tid uten svar

let lastSuccess = Date.now();
const cards = [];

async function main() {
  // Hindre at lange trykk på berøringsskjerm åpner høyreklikk-meny
  document.addEventListener('contextmenu', (e) => e.preventDefault());

  const config = await loadConfigWithRetry();
  document.title = config.title || 'Hjemmepanel';
  buildGrid(config);
  setInterval(checkOffline, 5000);
  setInterval(() => cards.forEach((c) => safeTick(c)), 1000);
}

/** Henter /api/config og prøver igjen til det lykkes (backend kan være på vei opp). */
async function loadConfigWithRetry() {
  for (;;) {
    try {
      const cfg = await api.get('/api/config');
      markOnline();
      return cfg;
    } catch (err) {
      console.warn('Får ikke config fra backend, prøver igjen om 3 s:', err.message);
      checkOffline();
      await sleep(3000);
    }
  }
}

/** Bygger rutenettet fra layouten i config.yaml. */
function buildGrid(config) {
  const dashboard = document.getElementById('dashboard');
  const rows = (config.layout || []).map((r) => r.trim().split(/\s+/));
  const cols = Math.max(...rows.map((r) => r.length), 1);

  dashboard.style.gridTemplateAreas = rows.map((r) => `"${r.join(' ')}"`).join(' ');
  dashboard.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  dashboard.style.gridTemplateRows = `repeat(${rows.length}, minmax(0, 1fr))`;

  const ids = [...new Set(rows.flat())].filter((id) => id !== '.');
  for (const id of ids) {
    const card = getCard(id);
    const el = createCardElement(id, card);
    dashboard.appendChild(el);
    if (card) startCard(card, el, config);
  }
}

function createCardElement(id, card) {
  const el = document.createElement('section');
  el.className = 'card' + (card?.headerless ? ' card-headerless' : '');
  el.style.gridArea = id;
  el.dataset.card = id;
  el.innerHTML = `
    <div class="card-header">
      <div class="card-title">${escapeHtml(card ? card.title : id)}</div>
      <div class="card-status"></div>
    </div>
    <div class="card-error" hidden></div>
    <div class="card-body"></div>`;
  if (!card) {
    el.querySelector('.card-body').innerHTML =
      `<div class="card-placeholder">Fant ikke kortet «${escapeHtml(id)}».<br>Sjekk layout i config.yaml.</div>`;
  }
  return el;
}

/** Monterer et kort og starter oppdateringsløkka for det. */
function startCard(card, el, config) {
  const titleEl = el.querySelector('.card-title');
  const statusEl = el.querySelector('.card-status');
  const errorEl = el.querySelector('.card-error');
  const body = el.querySelector('.card-body');

  const ctx = {
    config,
    showToast,
    setTitle(text) { titleEl.textContent = text; },
    setStatus(text, { loading = false } = {}) {
      statusEl.textContent = text || '';
      statusEl.classList.toggle('is-loading', loading);
    },
    setError(message) {
      errorEl.textContent = message;
      errorEl.hidden = !message;
    },
  };

  const entry = { card, ctx, timer: null };
  cards.push(entry);

  try {
    card.mount(body, ctx);
  } catch (err) {
    console.error(`Kortet ${card.id} feilet under oppsett`, err);
    ctx.setError(`Kortet kunne ikke vises: ${err.message}`);
    return;
  }

  const refreshMs = card.refreshMs ?? 0;

  async function loop() {
    ctx.setStatus('Oppdaterer', { loading: true });
    try {
      const result = await card.refresh(ctx);
      markOnline();
      // Et kort kan returnere { warning: '...' } for å vise en advarsel uten å regnes som feilet
      ctx.setError(result?.warning || '');
      ctx.setStatus(`Oppdatert ${timeNow()}`);
      entry.timer = refreshMs > 0 ? setTimeout(loop, refreshMs) : null;
    } catch (err) {
      console.warn(`Kortet ${card.id} fikk feil:`, err);
      ctx.setError(err.message || 'Ukjent feil');
      ctx.setStatus('Feil');
      // Prøv igjen litt raskere enn vanlig når noe feiler
      const retry = refreshMs > 0 ? Math.min(refreshMs, 15000) : 15000;
      entry.timer = setTimeout(loop, retry);
    }
  }

  if (typeof card.refresh === 'function') loop();
  else ctx.setStatus('');
}

function safeTick(entry) {
  if (typeof entry.card.tick !== 'function') return;
  try { entry.card.tick(entry.ctx); } catch (err) { console.warn(`tick i ${entry.card.id} feilet`, err); }
}

/* ---------- Frakoblet-håndtering ---------- */

function markOnline() {
  lastSuccess = Date.now();
  document.getElementById('offline-overlay').hidden = true;
}

function checkOffline() {
  const overlay = document.getElementById('offline-overlay');
  overlay.hidden = Date.now() - lastSuccess < OFFLINE_AFTER_MS;
}

// Gjør markOnline tilgjengelig for kortene (så f.eks. et vellykket lystrykk teller som "online")
export { markOnline };

/* ---------- Småting ---------- */

function timeNow() {
  return new Date().toLocaleTimeString('nb-NO', { hour: '2-digit', minute: '2-digit' });
}
function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// Uventede feil skal vises, ikke stoppe siden
window.addEventListener('error', (e) => showToast(`Feil: ${e.message}`, { error: true }));
window.addEventListener('unhandledrejection', (e) => showToast(`Feil: ${e.reason?.message || e.reason}`, { error: true }));

main();
