/* Værkortet: vær nå, de neste timene og de neste dagene (MET/Yr via backend). */

import { api } from '../api.js';
import { icon } from '../components/icons.js';
import { escapeHtml } from '../components/sheet.js';

let root = null;
let data = null;

export default {
  id: 'weather',
  title: 'Vær',
  refreshMs: 600000,

  mount(body, ctx) {
    root = body;
    this.refreshMs = (ctx.config.weather?.refresh_seconds ?? 600) * 1000;
    if (ctx.config.weather?.place_name) ctx.setTitle(ctx.config.weather.place_name);
    body.innerHTML = '<div class="weather" data-weather></div>';
  },

  async refresh(ctx) {
    data = await api.get('/api/weather');
    ctx.setTitle(data.place);
    render();
    // Backend kan svare med gammelt varsel + advarsel hvis MET ikke var å få tak i
    return { warning: data.warning };
  },
};

function render() {
  const el = root.querySelector('[data-weather]');
  const n = data.now;
  el.innerHTML = `
    <div class="weather-now">
      <span class="weather-now-icon">${icon(n.icon)}</span>
      <div class="weather-now-main">
        <div class="weather-temp ${tempClass(n.temp)}">${fmtTemp(n.temp)}</div>
        <div class="weather-desc">${escapeHtml(n.symbol_text)}</div>
      </div>
      <div class="weather-now-details">
        <div title="${escapeHtml(n.wind_text)}">${icon('wind')}${Math.round(n.wind)} m/s ${escapeHtml(n.wind_dir_text)}</div>
        <div>${icon('drop')}${fmtMm(n.precip_1h)} neste time</div>
      </div>
    </div>

    <div class="weather-hours">
      ${data.hours.map((h) => `
        <div class="weather-hour" title="${escapeHtml(h.symbol_text)}">
          <div class="wh-time">${fmtHour(h.time)}</div>
          ${icon(h.icon)}
          <div class="wh-temp ${tempClass(h.temp)}">${fmtTemp(h.temp)}</div>
          <div class="wh-precip">${h.precip > 0 ? fmtMm(h.precip) : ''}</div>
        </div>`).join('')}
    </div>

    <div class="weather-days">
      ${data.days.map((d) => `
        <div class="weather-day" title="${escapeHtml(d.symbol_text)}">
          <span class="wd-label">${escapeHtml(d.label)}</span>
          ${icon(d.icon)}
          <span class="wd-temp"><span class="${tempClass(d.tmax)}">${fmtTemp(d.tmax)}</span> / <span class="${tempClass(d.tmin)}">${fmtTemp(d.tmin)}</span></span>
          <span class="wd-precip">${d.precip > 0 ? fmtMm(d.precip) : ''}</span>
        </div>`).join('')}
    </div>`;
}

function fmtTemp(t) {
  const r = Math.round(t);
  return `${r === 0 ? 0 : r}°`;   // unngå "-0°"
}
function tempClass(t) {
  return Math.round(t) < 0 ? 'temp-minus' : 'temp-plus';
}
function fmtMm(mm) {
  if (mm == null) return '–';
  return `${mm.toLocaleString('nb-NO', { maximumFractionDigits: 1 })} mm`;
}
function fmtHour(iso) {
  return new Date(iso).toLocaleTimeString('nb-NO', { hour: '2-digit' });
}
