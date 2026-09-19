/* Lyskortet: alle pærene med av/på, scener, og et ark for dimming og farge.

   Data kommer fra GET /api/lights. Endringer sendes som POST og svaret
   (ny tilstand) legges rett inn, så skjermen alltid viser det pæra sier. */

import { api } from '../api.js';
import { icon } from '../components/icons.js';
import { openSheet, confirmSheet, escapeHtml } from '../components/sheet.js';
import { kelvinToRgb, hsvToRgb, rgbToHue, rgbCss, describeKelvin } from '../components/color.js';

const LONG_PRESS_MS = 800;      // hold scene-knappen så lenge for å lagre nåværende lys i scenen
const SEND_THROTTLE_MS = 250;   // maks én kommando til pæra per så mange ms mens man drar en skyver

const SWATCHES = [
  { name: 'Rød', rgb: [255, 0, 0] },
  { name: 'Oransje', rgb: [255, 110, 0] },
  { name: 'Gul', rgb: [255, 220, 0] },
  { name: 'Grønn', rgb: [40, 220, 60] },
  { name: 'Turkis', rgb: [0, 210, 210] },
  { name: 'Blå', rgb: [30, 90, 255] },
  { name: 'Lilla', rgb: [150, 50, 255] },
  { name: 'Rosa', rgb: [255, 70, 160] },
];

let root = null;
let ctx = null;
let data = { bulbs: [], scenes: [] };
let sheet = null;               // åpent pære-ark: { bulbId, handle, els, dragging, pane, paneLockUntil, send }
let renderedSceneIds = '';
let renderedBulbIds = '';

export default {
  id: 'lights',
  title: 'Lys',
  refreshMs: 10000,

  mount(body, context) {
    root = body;
    ctx = context;
    this.refreshMs = (context.config.lights?.poll_interval_seconds ?? 10) * 1000;

    body.innerHTML = `
      <div class="lights">
        <div class="lights-top">
          <button class="btn" data-all="on">${icon('power')}<span>Alle på</span></button>
          <button class="btn" data-all="off">${icon('off')}<span>Alle av</span></button>
        </div>
        <div class="scene-row" data-scenes></div>
        <div class="bulb-grid" data-bulbs></div>
      </div>`;

    body.querySelector('[data-all=on]').addEventListener('click', () => sendAll({ on: true }));
    body.querySelector('[data-all=off]').addEventListener('click', () => sendAll({ on: false }));
  },

  async refresh() {
    data = await api.get('/api/lights');
    render();
  },
};

/* ---------- Tegning ---------- */

function render() {
  renderScenes();
  renderBulbs();
  if (sheet && !sheet.dragging) updateSheet();
}

function renderScenes() {
  const row = root.querySelector('[data-scenes]');
  const ids = data.scenes.map((s) => s.id).join(',');
  if (ids === renderedSceneIds) return;
  renderedSceneIds = ids;
  row.innerHTML = '';
  if (!data.scenes.length) {
    row.innerHTML = '<div class="muted">Ingen scener i config/scenes.json</div>';
    return;
  }
  for (const scene of data.scenes) {
    const btn = document.createElement('button');
    btn.className = 'btn scene-btn';
    btn.innerHTML = `${icon(scene.icon || 'star')}<span>${escapeHtml(scene.name)}</span>`;
    wireLongPress(btn, () => activateScene(scene), () => captureScene(scene));
    row.appendChild(btn);
  }
}

function renderBulbs() {
  const grid = root.querySelector('[data-bulbs]');
  const ids = data.bulbs.map((b) => b.id).join(',');
  if (ids !== renderedBulbIds) {
    renderedBulbIds = ids;
    grid.innerHTML = '';
    if (!data.bulbs.length) {
      grid.innerHTML = '<div class="card-placeholder">Ingen pærer i config.yaml.<br>Kjør scripts/discover_bulbs.py.</div>';
    }
    for (const b of data.bulbs) {
      const tile = document.createElement('div');
      tile.className = 'bulb-tile';
      tile.dataset.bulb = b.id;
      tile.innerHTML = `
        <button class="bulb-open">
          <span class="bulb-icon">${icon('bulb')}</span>
          <span class="bulb-text">
            <span class="bulb-name">${escapeHtml(b.name)}</span>
            <span class="bulb-status"></span>
          </span>
        </button>
        <button class="bulb-power" aria-label="Av/på">${icon('power')}</button>`;
      tile.querySelector('.bulb-open').addEventListener('click', () => openBulbSheet(b.id));
      tile.querySelector('.bulb-power').addEventListener('click', () => toggleBulb(b.id));
      grid.appendChild(tile);
    }
  }
  for (const b of data.bulbs) {
    const tile = grid.querySelector(`[data-bulb="${CSS.escape(b.id)}"]`);
    if (tile) updateTile(tile, b);
  }
}

function updateTile(tile, b) {
  tile.classList.toggle('is-on', b.reachable && b.on);
  tile.classList.toggle('is-unreachable', !b.reachable);
  tile.querySelector('.bulb-icon').style.color = bulbColor(b);
  tile.querySelector('.bulb-status').textContent = statusText(b);
  tile.querySelector('.bulb-open').title = b.error || '';
}

function bulbColor(b) {
  if (!b.reachable || !b.on) return '';
  if (b.mode === 'color' && b.rgb) return rgbCss(b.rgb);
  return rgbCss(kelvinToRgb(b.colortemp ?? 2700));
}

function statusText(b) {
  if (!b.reachable) return 'Ingen kontakt';
  if (!b.on) return 'Av';
  let mode;
  if (b.mode === 'color') mode = 'Farge';
  else if (b.mode === 'scene') mode = b.scene_name || 'Scene';
  else mode = describeKelvin(b.colortemp);
  return `${b.brightness} % · ${mode}`;
}

function findBulb(id) {
  return data.bulbs.find((b) => b.id === id);
}

/* ---------- Kommandoer til backend ---------- */

function replaceBulb(state) {
  const i = data.bulbs.findIndex((b) => b.id === state.id);
  if (i >= 0) data.bulbs[i] = state; else data.bulbs.push(state);
}

async function sendBulb(id, cmd) {
  try {
    replaceBulb(await api.post(`/api/lights/bulbs/${encodeURIComponent(id)}`, cmd));
    render();
  } catch (err) {
    ctx.showToast(err.message, { error: true });
  }
}

async function toggleBulb(id) {
  const b = findBulb(id);
  if (b) { b.on = !b.on; render(); }   // vis endringen med en gang, rett opp hvis pæra sier noe annet
  try {
    replaceBulb(await api.post(`/api/lights/bulbs/${encodeURIComponent(id)}/toggle`));
  } catch (err) {
    ctx.showToast(err.message, { error: true });
    try { data = await api.get('/api/lights'); } catch { /* vises ved neste oppdatering */ }
  }
  render();
}

async function sendAll(cmd) {
  try {
    data.bulbs = (await api.post('/api/lights/all', cmd)).bulbs;
    render();
  } catch (err) {
    ctx.showToast(err.message, { error: true });
  }
}

async function activateScene(scene) {
  try {
    data.bulbs = (await api.post(`/api/lights/scenes/${encodeURIComponent(scene.id)}/activate`)).bulbs;
    render();
  } catch (err) {
    ctx.showToast(err.message, { error: true });
  }
}

async function captureScene(scene) {
  const ok = await confirmSheet(
    `Lagre scenen «${scene.name}»?`,
    'Lysene slik de står nå blir lagret som denne scenen. Den gamle innstillingen overskrives.',
    { okLabel: 'Lagre' },
  );
  if (!ok) return;
  try {
    await api.post(`/api/lights/scenes/${encodeURIComponent(scene.id)}/capture`);
    ctx.showToast(`Scenen «${scene.name}» er oppdatert`);
  } catch (err) {
    ctx.showToast(err.message, { error: true });
  }
}

/* ---------- Ark for én pære: dimming, fargetemperatur og farge ---------- */

function openBulbSheet(bulbId) {
  const b = findBulb(bulbId);
  if (!b) return;

  const send = throttle((cmd) => sendBulb(bulbId, cmd), SEND_THROTTLE_MS);
  sheet = { bulbId, send, dragging: false, pane: null, paneLockUntil: 0, els: {} };

  sheet.handle = openSheet(b.name, (body) => {
    const f = b.features || {};
    body.innerHTML = `
      <div class="bulb-sheet">
        <div class="row bulb-sheet-top">
          <button class="btn btn-big" data-act="toggle">${icon('power')}<span data-toggle-label>På</span></button>
          <div class="bulb-sheet-status muted" data-status></div>
        </div>

        <div class="control" ${f.brightness === false ? 'hidden' : ''}>
          <div class="control-label"><span>Lysstyrke</span><span class="control-value" data-val="brightness"></span></div>
          <input type="range" class="slider slider-brightness" data-slider="brightness" min="10" max="100" step="1">
        </div>

        <div class="mode-tabs" ${f.color && f.colortemp ? '' : 'hidden'}>
          <button class="btn" data-mode="white">Hvitt</button>
          <button class="btn" data-mode="color">Farge</button>
        </div>

        <div class="control" data-pane="white" ${f.colortemp === false ? 'hidden' : ''}>
          <div class="control-label"><span>Fargetemperatur</span><span class="control-value" data-val="kelvin"></span></div>
          <input type="range" class="slider slider-kelvin" data-slider="kelvin"
                 min="${f.kelvin_min ?? 2200}" max="${f.kelvin_max ?? 6500}" step="50">
          <div class="preset-row">
            <button class="btn" data-kelvin="2700">Varmt</button>
            <button class="btn" data-kelvin="4000">Nøytralt</button>
            <button class="btn" data-kelvin="6000">Kaldt</button>
          </div>
        </div>

        <div class="control" data-pane="color" ${f.color === false ? 'hidden' : ''}>
          <div class="control-label"><span>Farge</span></div>
          <input type="range" class="slider slider-hue" data-slider="hue" min="0" max="359" step="1">
          <div class="swatch-row">
            ${SWATCHES.map((s) => `<button class="swatch" data-rgb="${s.rgb.join(',')}" style="background:${rgbCss(s.rgb)}" aria-label="${s.name}"></button>`).join('')}
          </div>
        </div>
      </div>`;

    const els = sheet.els = {
      toggle: body.querySelector('[data-act=toggle]'),
      toggleLabel: body.querySelector('[data-toggle-label]'),
      status: body.querySelector('[data-status]'),
      brightness: body.querySelector('[data-slider=brightness]'),
      brightnessVal: body.querySelector('[data-val=brightness]'),
      kelvin: body.querySelector('[data-slider=kelvin]'),
      kelvinVal: body.querySelector('[data-val=kelvin]'),
      hue: body.querySelector('[data-slider=hue]'),
      tabs: [...body.querySelectorAll('[data-mode]')],
      panes: { white: body.querySelector('[data-pane=white]'), color: body.querySelector('[data-pane=color]') },
      presets: [...body.querySelectorAll('[data-kelvin]')],
      swatches: [...body.querySelectorAll('.swatch')],
    };

    els.toggle.addEventListener('click', () => toggleBulb(bulbId));

    wireSlider(els.brightness, (v, final) => {
      els.brightnessVal.textContent = `${v} %`;
      sendCmd({ brightness: v }, final);
    });
    wireSlider(els.kelvin, (v, final) => {
      els.kelvinVal.textContent = `${v} K`;
      sendCmd({ colortemp: v }, final);
    });
    wireSlider(els.hue, (v, final) => {
      sendCmd({ rgb: hsvToRgb(v, 1, 1) }, final);
    });

    for (const tab of els.tabs) {
      tab.addEventListener('click', () => {
        setPane(tab.dataset.mode, true);
        if (tab.dataset.mode === 'white') sendCmd({ colortemp: Number(els.kelvin.value) }, true);
        else sendCmd({ rgb: hsvToRgb(Number(els.hue.value), 1, 1) }, true);
      });
    }
    for (const p of els.presets) {
      p.addEventListener('click', () => {
        els.kelvin.value = p.dataset.kelvin;
        els.kelvinVal.textContent = `${p.dataset.kelvin} K`;
        sendCmd({ colortemp: Number(p.dataset.kelvin) }, true);
      });
    }
    for (const s of els.swatches) {
      s.addEventListener('click', () => {
        const rgb = s.dataset.rgb.split(',').map(Number);
        els.hue.value = rgbToHue(rgb);
        sendCmd({ rgb }, true);
      });
    }
  }, { onClose: () => { sheet = null; } });

  updateSheet();
}

/** Sender en kommando fra arket. `final` = siste verdi etter at fingeren er sluppet. */
function sendCmd(cmd, final) {
  if (!sheet) return;
  if (final) {
    sheet.send.cancel();
    sendBulb(sheet.bulbId, cmd);
  } else {
    sheet.send(cmd);
  }
}

function setPane(pane, byUser = false) {
  if (!sheet) return;
  sheet.pane = pane;
  if (byUser) sheet.paneLockUntil = Date.now() + 3000;   // ikke la en gammel status flippe fanen tilbake
  for (const tab of sheet.els.tabs) tab.classList.toggle('is-active', tab.dataset.mode === pane);
  for (const [name, el] of Object.entries(sheet.els.panes)) {
    if (!el) continue;
    el.style.display = name === pane ? '' : 'none';
  }
}

/** Oppdaterer arket fra siste kjente tilstand (kalles etter hver oppdatering). */
function updateSheet() {
  if (!sheet) return;
  const b = findBulb(sheet.bulbId);
  if (!b) { sheet.handle.close(); return; }
  const els = sheet.els;

  els.toggle.classList.toggle('is-active', b.reachable && b.on);
  els.toggleLabel.textContent = b.on ? 'På' : 'Av';
  els.status.textContent = statusText(b);

  if (!sheet.dragging) {
    els.brightness.value = Math.max(10, b.brightness || 10);
    if (b.colortemp) els.kelvin.value = b.colortemp;
    if (b.rgb) els.hue.value = rgbToHue(b.rgb);
  }
  els.brightnessVal.textContent = `${els.brightness.value} %`;
  els.kelvinVal.textContent = `${els.kelvin.value} K`;

  for (const p of els.presets) p.classList.toggle('is-active', b.mode === 'white' && Number(p.dataset.kelvin) === b.colortemp);
  for (const s of els.swatches) s.classList.toggle('is-active', b.mode === 'color' && s.dataset.rgb === (b.rgb || []).join(','));

  const f = b.features || {};
  if (Date.now() > sheet.paneLockUntil || !sheet.pane) {
    let pane = b.mode === 'color' ? 'color' : 'white';
    if (pane === 'color' && f.color === false) pane = 'white';
    if (pane === 'white' && f.colortemp === false && f.color) pane = 'color';
    setPane(pane);
  }
}

/* ---------- Småhjelpere ---------- */

/** Skyver: `onValue(v, final)` kalles mens man drar (final=false) og når man slipper (final=true). */
function wireSlider(input, onValue) {
  if (!input) return;
  const start = () => { if (sheet) sheet.dragging = true; };
  const end = () => { if (sheet) sheet.dragging = false; };
  input.addEventListener('pointerdown', start);
  input.addEventListener('input', () => onValue(Number(input.value), false));
  input.addEventListener('change', () => { onValue(Number(input.value), true); end(); });
  input.addEventListener('pointerup', end);
  input.addEventListener('pointercancel', end);
}

/** Kort trykk → onTap, holde inne → onLong. Gir visuell fylling mens man holder. */
function wireLongPress(btn, onTap, onLong) {
  let timer = null;
  let fired = false;
  const cancel = () => { clearTimeout(timer); timer = null; btn.classList.remove('is-pressing'); };
  btn.addEventListener('pointerdown', () => {
    fired = false;
    btn.classList.add('is-pressing');
    timer = setTimeout(() => { fired = true; cancel(); onLong(); }, LONG_PRESS_MS);
  });
  btn.addEventListener('pointerup', () => { const wasLong = fired; cancel(); if (!wasLong) onTap(); });
  btn.addEventListener('pointerleave', cancel);
  btn.addEventListener('pointercancel', cancel);
}

/** Kaller fn maks én gang per `ms`, med siste argumenter. `.cancel()` dropper ventende kall. */
function throttle(fn, ms) {
  let last = 0, timer = null, pending = null;
  const run = () => { last = Date.now(); timer = null; const args = pending; pending = null; fn(...args); };
  const wrapped = (...args) => {
    pending = args;
    const wait = ms - (Date.now() - last);
    if (wait <= 0) run();
    else if (!timer) timer = setTimeout(run, wait);
  };
  wrapped.cancel = () => { clearTimeout(timer); timer = null; pending = null; };
  return wrapped;
}
