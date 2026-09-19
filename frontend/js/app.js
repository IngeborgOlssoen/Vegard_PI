/* Selve dashbordet: leser sider og layout fra backend, lager kortene og holder
   dem oppdatert. Feil i ett kort skal aldri påvirke de andre.
   Med flere sider i config sveiper man sidelengs mellom dem. */

import { api } from './api.js';
import { getCard } from './cards/index.js';
import { showToast } from './components/toast.js';
import { escapeHtml } from './components/sheet.js';

// Kort som er tilgjengelige. Importen registrerer dem i registeret.
import './cards/registry.js';

const OFFLINE_AFTER_MS = 60_000;   // vis "ingen kontakt"-overlay etter så lang tid uten svar
const SWIPE_MIN_PX = 70;           // så langt må fingeren dras for å bytte side

let lastSuccess = Date.now();
let lastActivity = Date.now();
const cards = [];
const mountedIds = new Set();
let pageCount = 1;
let currentPage = 0;

async function main() {
  // Hindre at lange trykk på berøringsskjerm åpner høyreklikk-meny
  document.addEventListener('contextmenu', (e) => e.preventDefault());

  const config = await loadConfigWithRetry();
  document.title = config.title || 'Hjemmepanel';
  buildPages(config);
  setupSwipe();
  setInterval(checkOffline, 5000);
  setInterval(() => cards.forEach((c) => safeTick(c)), 1000);
  if (config.home_after_seconds > 0) {
    setInterval(() => {
      if (currentPage !== 0 && Date.now() - lastActivity > config.home_after_seconds * 1000) goToPage(0);
    }, 5000);
  }
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

/* ---------- Sider ---------- */

function buildPages(config) {
  const pagesEl = document.getElementById('pages');
  const pages = config.pages?.length ? config.pages : [{ name: '', layout: config.layout || [] }];
  pageCount = pages.length;

  pages.forEach((page, i) => {
    const pageEl = document.createElement('section');
    pageEl.className = 'page';
    pageEl.dataset.page = i;
    const dashboard = document.createElement('main');
    dashboard.className = 'dashboard';
    dashboard.setAttribute('aria-label', page.name || `Side ${i + 1}`);
    buildGrid(dashboard, page.layout || [], config);
    pageEl.appendChild(dashboard);
    pagesEl.appendChild(pageEl);
  });

  const dots = document.getElementById('page-dots');
  if (pageCount > 1) {
    document.body.classList.add('has-pages');
    dots.hidden = false;
    dots.innerHTML = pages.map((p, i) =>
      `<button class="page-dot" data-page="${i}" aria-label="${escapeHtml(p.name || `Side ${i + 1}`)}"></button>`).join('');
    dots.querySelectorAll('.page-dot').forEach((b) => b.addEventListener('click', () => goToPage(Number(b.dataset.page))));
  }
  goToPage(0);
}

export function goToPage(index) {
  currentPage = Math.max(0, Math.min(pageCount - 1, index));
  document.getElementById('pages').style.transform = `translateX(-${currentPage * 100}vw)`;
  document.querySelectorAll('.page-dot').forEach((d, i) => d.classList.toggle('is-active', i === currentPage));
  lastActivity = Date.now();
}

/** Sveip sidelengs for å bytte side. Ignorerer skyvere, ark og rader som ruller sidelengs. */
function setupSwipe() {
  let startX = 0, startY = 0, tracking = false;
  document.addEventListener('pointerdown', (e) => {
    lastActivity = Date.now();
    if (pageCount < 2) return;
    if (e.target.closest('input, .sheet-backdrop, .scene-row, .swatch-row, .no-swipe')) return;
    startX = e.clientX; startY = e.clientY; tracking = true;
  });
  document.addEventListener('pointerup', (e) => {
    if (!tracking) return;
    tracking = false;
    const dx = e.clientX - startX, dy = e.clientY - startY;
    if (Math.abs(dx) >= SWIPE_MIN_PX && Math.abs(dx) > Math.abs(dy) * 1.5) goToPage(currentPage + (dx < 0 ? 1 : -1));
  });
  document.addEventListener('pointercancel', () => { tracking = false; });
  // Piltaster fungerer også (praktisk på PC)
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowRight') goToPage(currentPage + 1);
    if (e.key === 'ArrowLeft') goToPage(currentPage - 1);
  });
}

/* ---------- Rutenett og kort ---------- */

/** Bygger rutenettet for én side fra layouten i config.yaml. */
function buildGrid(dashboard, layout, config) {
  const rows = layout.map((r) => r.trim().split(/\s+/));
  const cols = Math.max(...rows.map((r) => r.length), 1);

  dashboard.style.gridTemplateAreas = rows.map((r) => `"${r.join(' ')}"`).join(' ');
  dashboard.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  dashboard.style.gridTemplateRows = `repeat(${Math.max(rows.length, 1)}, minmax(0, 1fr))`;

  const ids = [...new Set(rows.flat())].filter((id) => id !== '.');
  for (const id of ids) {
    const card = getCard(id);
    let el;
    if (card && mountedIds.has(id)) {
      // Samme kort på to sider ville delt tilstand og gått i stykker – si fra i stedet
      el = createCardElement(id, null, `Kortet «${id}» er allerede brukt på en annen side.`);
    } else {
      el = createCardElement(id, card);
      if (card) { mountedIds.add(id); startCard(card, el, config); }
    }
    dashboard.appendChild(el);
  }
}

function createCardElement(id, card, placeholder = null) {
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
      `<div class="card-placeholder">${escapeHtml(placeholder || `Fant ikke kortet «${id}».`)}<br>Sjekk layout i config.yaml.</div>`;
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
