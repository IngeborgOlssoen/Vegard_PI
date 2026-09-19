/* Busskortet: neste avganger fra holdeplassene i config.yaml (via Entur).

   Backend hentes hvert `bus.refresh_seconds`. Mellom hentingene teller vi
   ned selv ut fra forventet avgangstid, så minuttene stemmer selv om nettet
   skulle falle ut en stund.

   Kortet finnes i flere varianter (se registry.js):
     bus   – alle holdeplassene i ett kort, med overskrift per holdeplass
     bus1  – bare første holdeplass i config, bus2 – andre, osv. */

import { api } from '../api.js';
import { escapeHtml } from '../components/sheet.js';

/**
 * Lager et busskort.
 * @param {string} id        kort-id (brukes i layout)
 * @param {number|null} stopIndex  null = alle holdeplasser, ellers 0-basert indeks i bus.stops
 */
export function createBusCard(id, stopIndex = null) {
  let root = null;
  let stops = [];
  let lastTick = 0;

  function render() {
    const list = root.querySelector('[data-list]');
    const now = Date.now();
    const showHeadings = stops.length > 1;
    list.classList.toggle('is-multi', showHeadings);

    list.innerHTML = stops.map((stop) => {
      const departures = (stop.departures || []).filter((d) => new Date(d.expected).getTime() > now - 30000);
      let body;
      if (stop.error) {
        body = `<div class="dep-error">${escapeHtml(stop.error)}</div>`;
      } else if (!departures.length) {
        body = '<div class="dep-empty">Ingen avganger de neste timene</div>';
      } else {
        body = departures.map((d) => {
          const { label, cls } = timeLabel(d, now);
          return `
            <div class="dep-row ${d.cancelled ? 'is-cancelled' : ''}">
              <span class="dep-line mode-${escapeHtml(d.mode)}">${escapeHtml(d.line)}</span>
              <span class="dep-dest">${escapeHtml(d.destination)}${d.platform ? `<span class="dep-platform">${escapeHtml(d.platform)}</span>` : ''}</span>
              <span class="dep-time ${cls}">${label}</span>
            </div>`;
        }).join('');
      }
      return `
        <div class="dep-stop">
          ${showHeadings ? `<div class="dep-stop-name">${escapeHtml(stop.stop_name)}</div>` : ''}
          ${body}
        </div>`;
    }).join('');
  }

  return {
    id,
    title: 'Buss',
    refreshMs: 30000,

    mount(body, ctx) {
      root = body;
      this.refreshMs = (ctx.config.bus?.refresh_seconds ?? 30) * 1000;
      body.innerHTML = '<div class="bus"><div class="dep-list" data-list></div></div>';
    },

    async refresh(ctx) {
      const all = await api.get('/api/bus');
      if (stopIndex == null) {
        stops = all.stops;
      } else {
        if (!all.stops[stopIndex]) {
          throw new Error(`Det er ingen holdeplass nr. ${stopIndex + 1} under bus.stops i config.yaml`);
        }
        stops = [all.stops[stopIndex]];
      }
      ctx.setTitle(stops.length === 1 ? stops[0].stop_name : 'Buss');
      render();

      // Én holdeplass som feiler = kortet feiler. Flere: vis feilen inne i kortet.
      const failed = stops.filter((s) => s.error);
      if (failed.length && stops.length === 1) throw new Error(failed[0].error);
      return failed.length ? { warning: failed.map((s) => `${s.stop_name}: ${s.error}`).join(' · ') } : undefined;
    },

    tick() {
      // Oppdater minuttene hvert 15. sekund uten å spørre backend
      if (!stops.length || Date.now() - lastTick < 15000) return;
      lastTick = Date.now();
      render();
    },
  };
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

export default createBusCard('bus', null);
