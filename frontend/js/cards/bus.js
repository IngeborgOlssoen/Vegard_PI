/* Busskortet: neste avganger fra holdeplassen i config.yaml (via Entur).

   Backend hentes hvert `bus.refresh_seconds`. Mellom hentingene teller vi
   ned selv ut fra forventet avgangstid, så minuttene stemmer selv om nettet
   skulle falle ut en stund. */

import { api } from '../api.js';
import { escapeHtml } from '../components/sheet.js';

let root = null;
let data = null;
let lastTick = 0;

export default {
  id: 'bus',
  title: 'Buss',
  refreshMs: 30000,

  mount(body, ctx) {
    root = body;
    this.refreshMs = (ctx.config.bus?.refresh_seconds ?? 30) * 1000;
    body.innerHTML = `<div class="bus"><div class="dep-list" data-list></div></div>`;
  },

  async refresh(ctx) {
    data = await api.get('/api/bus');
    ctx.setTitle(data.stop_name);   // holdeplassnavnet som overskrift
    render();
  },

  tick() {
    // Oppdater minuttene hvert 15. sekund uten å spørre backend
    if (!data || Date.now() - lastTick < 15000) return;
    lastTick = Date.now();
    render();
  },
};

function render() {
  const list = root.querySelector('[data-list]');
  const now = Date.now();
  const departures = data.departures.filter((d) => new Date(d.expected).getTime() > now - 30000);

  if (!departures.length) {
    list.innerHTML = '<div class="card-placeholder">Ingen avganger de neste timene</div>';
    return;
  }

  list.innerHTML = departures.map((d) => {
    const { label, cls } = timeLabel(d, now);
    return `
      <div class="dep-row ${d.cancelled ? 'is-cancelled' : ''}">
        <span class="dep-line mode-${escapeHtml(d.mode)}">${escapeHtml(d.line)}</span>
        <span class="dep-dest">${escapeHtml(d.destination)}${d.platform ? `<span class="dep-platform">${escapeHtml(d.platform)}</span>` : ''}</span>
        <span class="dep-time ${cls}">${label}</span>
      </div>`;
  }).join('');
}

/** Tekst for avgangstid: "nå", "7 min" eller klokkeslett (uten sanntid eller langt fram). */
function timeLabel(d, now) {
  if (d.cancelled) return { label: 'Innstilt', cls: 'is-cancelled' };
  const minutes = Math.floor((new Date(d.expected).getTime() - now) / 60000);
  const clock = new Date(d.expected).toLocaleTimeString('nb-NO', { hour: '2-digit', minute: '2-digit' });
  if (!d.realtime) return { label: clock, cls: 'is-scheduled' };
  if (minutes < 1) return { label: 'nå', cls: 'is-now' };
  if (minutes < 60) return { label: `${minutes} min`, cls: '' };
  return { label: clock, cls: 'is-scheduled' };
}
