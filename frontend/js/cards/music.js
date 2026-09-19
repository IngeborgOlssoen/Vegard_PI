/* Musikkortet: hva som spilles, spill/pause/neste, volum, rom (Sonos) og
   spillelistene dine (Spotify). Backend (/api/music) bestemmer hva som styres
   lokalt på Sonos og hva som går via Spotify; kortet er det samme uansett.
   Laget for å fylle en hel side, men fungerer også i et mindre kort. */

import { api } from '../api.js';
import { icon } from '../components/icons.js';
import { openSheet, escapeHtml } from '../components/sheet.js';

let root = null;
let ctx = null;
let data = null;             // siste svar fra /api/spotify
let lastSync = 0;            // når progress_ms sist ble hentet (for lokal telling)
let volumeDragging = false;
let pendingVolume = null;
let renderedPlaylists = '';
let roomsSheet = null;       // åpent rom-ark: { handle, body }

export default {
  id: 'music',
  title: 'Musikk',
  refreshMs: 5000,
  headerless: true,

  mount(body, context) {
    root = body;
    ctx = context;
    this.refreshMs = (context.config.music?.refresh_seconds ?? 5) * 1000;

    if (!context.config.music?.enabled) {
      body.innerHTML = `<div class="card-placeholder">Musikk er ikke skrudd på.<br>
        Sett <code>sonos.enabled: true</code> (og/eller <code>spotify.enabled</code>) i config.yaml, se README.</div>`;
      this.refresh = null;
      return;
    }

    body.innerHTML = `
      <div class="music">
        <div class="music-player">
          <div class="music-cover" data-cover>${icon('music')}</div>
          <div class="music-title" data-title>Ingenting spilles</div>
          <div class="music-artist" data-artist></div>
          <div class="music-progress"><div class="music-progress-bar" data-bar></div></div>
          <div class="music-times"><span data-pos>0:00</span><span data-dur>0:00</span></div>
          <div class="music-controls">
            <button class="btn btn-round" data-act="previous" aria-label="Forrige">${icon('previous')}</button>
            <button class="btn btn-round btn-play" data-act="toggle" aria-label="Spill/pause">${icon('play')}</button>
            <button class="btn btn-round" data-act="next" aria-label="Neste">${icon('next')}</button>
          </div>
          <div class="music-volume">
            ${icon('volume')}
            <input type="range" class="slider slider-volume" data-volume min="0" max="100" step="1" aria-label="Volum">
            <span class="music-volume-value" data-volume-value></span>
          </div>
          <button class="btn music-device" data-act="device">${icon('speaker')}<span data-device>Velg rom</span></button>
        </div>
        <div class="music-playlists">
          <div class="music-section-title">Spillelister</div>
          <div class="playlist-grid" data-playlists></div>
        </div>
      </div>`;

    body.querySelector('[data-act=toggle]').addEventListener('click', togglePlay);
    body.querySelector('[data-act=next]').addEventListener('click', () => command('next'));
    body.querySelector('[data-act=previous]').addEventListener('click', () => command('previous'));
    body.querySelector('[data-act=device]').addEventListener('click', openRoomsSheet);

    const vol = body.querySelector('[data-volume]');
    vol.addEventListener('pointerdown', () => { volumeDragging = true; });
    vol.addEventListener('input', () => {
      body.querySelector('[data-volume-value]').textContent = `${vol.value} %`;
      pendingVolume = Number(vol.value);
    });
    const done = () => {
      volumeDragging = false;
      if (pendingVolume != null) { command('volume', { percent: pendingVolume }); pendingVolume = null; }
    };
    vol.addEventListener('change', done);
    vol.addEventListener('pointerup', done);
    vol.addEventListener('pointercancel', done);
  },

  async refresh() {
    data = await api.get('/api/music');
    lastSync = Date.now();
    render();
    if (!data.ready) return { warning: data.message };
    return data.warning ? { warning: data.warning } : undefined;
  },

  tick() {
    // Framdriftslinja teller lokalt mellom hentingene
    if (!data?.ready || !data.state.track) return;
    renderProgress();
  },
};

/* ---------- Tegning ---------- */

function render() {
  if (!root || !data) return;
  const s = data.state;
  const q = (sel) => root.querySelector(sel);

  const coverEl = q('[data-cover]');
  if (s.track?.image) {
    if (coverEl.dataset.src !== s.track.image) {
      coverEl.dataset.src = s.track.image;
      coverEl.innerHTML = `<img src="${escapeHtml(s.track.image)}" alt="">`;
    }
  } else {
    coverEl.dataset.src = '';
    coverEl.innerHTML = icon('music');
  }
  coverEl.classList.toggle('is-playing', s.is_playing);

  q('[data-title]').textContent = s.track ? s.track.title : (data.ready ? 'Ingenting spilles' : 'Spotify');
  q('[data-artist]').textContent = s.track ? [s.track.artists, s.track.album].filter(Boolean).join(' · ') : '';
  q('[data-act=toggle]').innerHTML = icon(s.is_playing ? 'pause' : 'play');
  q('[data-act=toggle]').classList.toggle('is-active', s.is_playing);

  const vol = q('[data-volume]');
  const volume = s.device?.volume;
  if (!volumeDragging && volume != null) vol.value = volume;
  vol.disabled = !s.device || s.device.supports_volume === false;
  q('[data-volume-value]').textContent = volume != null ? `${vol.value} %` : '';

  q('[data-device]').textContent = s.device ? `Spilles på ${s.device.name}` : 'Velg rom';
  renderProgress();
  renderPlaylists();
  if (roomsSheet) renderRooms();
}

function renderProgress() {
  const s = data.state;
  const dur = s.track?.duration_ms || 0;
  let pos = s.progress_ms || 0;
  if (s.is_playing) pos = Math.min(dur, pos + (Date.now() - lastSync));
  root.querySelector('[data-bar]').style.width = dur ? `${(pos / dur) * 100}%` : '0%';
  root.querySelector('[data-pos]').textContent = fmtTime(pos);
  root.querySelector('[data-dur]').textContent = fmtTime(dur);
}

function renderPlaylists() {
  const grid = root.querySelector('[data-playlists]');
  const key = data.playlists.map((p) => p.uri).join(',');
  if (key !== renderedPlaylists) {
    renderedPlaylists = key;
    grid.innerHTML = data.playlists.length ? data.playlists.map((p) => `
      <button class="playlist" data-uri="${escapeHtml(p.uri)}" title="${escapeHtml(p.name)}">
        <span class="playlist-cover" style="${p.image ? '' : `background:${placeholderColor(p.name)}`}">
          ${p.image ? `<img src="${escapeHtml(p.image)}" alt="" loading="lazy">` : `<span class="playlist-initial">${escapeHtml(p.name.slice(0, 1))}</span>`}
        </span>
        <span class="playlist-name">${escapeHtml(p.name)}</span>
        <span class="playlist-meta">${p.tracks} spor</span>
      </button>`).join('')
      : '<div class="muted">Ingen spillelister funnet på Spotify-kontoen.</div>';
    grid.querySelectorAll('.playlist').forEach((b) =>
      b.addEventListener('click', () => command('play', { context_uri: b.dataset.uri })));
  }
  grid.querySelectorAll('.playlist').forEach((b) =>
    b.classList.toggle('is-active', b.dataset.uri === data.state.context_uri));
}

/* ---------- Kommandoer ---------- */

async function command(name, body = {}) {
  try {
    data = await api.post(`/api/music/${name}`, body, { timeoutMs: 20000 });
    lastSync = Date.now();
    render();
  } catch (err) {
    ctx.showToast(err.message, { error: true });
  }
}

function togglePlay() {
  if (!data?.ready) return;
  // Vis endringen med en gang; svaret fra backend retter opp hvis noe annet skjedde
  data.state.is_playing = !data.state.is_playing;
  render();
  command(data.state.is_playing ? 'play' : 'pause');
}

/** Arket med rommene: velg rom, legg til/fjern rom i gruppa som spiller, og volum per rom. */
function openRoomsSheet() {
  if (!data?.ready) return;
  const title = data.engine === 'sonos' ? 'Rom' : 'Spill på';
  roomsSheet = {};
  roomsSheet.handle = openSheet(title, (body) => {
    roomsSheet.body = body;
    renderRooms();
  }, { onClose: () => { roomsSheet = null; } });
}

function renderRooms() {
  const body = roomsSheet?.body;
  if (!body) return;
  if (!data.devices.length) {
    body.innerHTML = `<div class="muted">${data.engine === 'sonos'
      ? 'Fant ingen Sonos-høyttalere. Er de på, og på samme nett som panelet?'
      : 'Fant ingen høyttalere. Er Sonos på, og er Spotify lagt til i Sonos-appen?'}</div>`;
    return;
  }
  const sonos = data.engine === 'sonos';
  const playing = data.state.is_playing;
  const hint = sonos
    ? (playing ? 'Trykk på et rom for å spille der også, eller for å ta det ut av gruppa.' : 'Trykk på rommet du vil spille i.')
    : 'Trykk på høyttaleren du vil spille på.';
  body.innerHTML = `
    <div class="muted room-hint">${hint}</div>
    <div class="room-list">${data.devices.map((d) => `
      <div class="room-row ${d.is_active ? 'is-active' : ''}">
        <button class="btn room-btn ${d.is_active ? 'is-active' : ''}" data-id="${escapeHtml(d.id)}">
          ${icon(d.is_active ? 'check' : 'speaker')}<span class="grow">${escapeHtml(d.name)}</span>
          ${d.is_coordinator && sonos && data.devices.filter((x) => x.is_active).length > 1 ? '<span class="room-tag">hoved</span>' : ''}
        </button>
        ${sonos ? `<div class="room-volume">${icon('volume')}
          <input type="range" class="slider slider-volume" data-room-volume="${escapeHtml(d.id)}" min="0" max="100" value="${d.volume ?? 0}" aria-label="Volum ${escapeHtml(d.name)}">
          <span class="music-volume-value" data-room-volume-value="${escapeHtml(d.id)}">${d.volume ?? ''}${d.volume != null ? ' %' : ''}</span></div>` : ''}
      </div>`).join('')}</div>`;

  body.querySelectorAll('.room-btn').forEach((b) => b.addEventListener('click', () => {
    if (sonos) command(`rooms/${encodeURIComponent(b.dataset.id)}/toggle`);
    else { roomsSheet.handle.close(); command('transfer', { device_id: b.dataset.id }); }
  }));
  body.querySelectorAll('[data-room-volume]').forEach((input) => {
    const id = input.dataset.roomVolume;
    const label = body.querySelector(`[data-room-volume-value="${CSS.escape(id)}"]`);
    input.addEventListener('pointerdown', () => { volumeDragging = true; });
    input.addEventListener('input', () => { label.textContent = `${input.value} %`; });
    const done = () => { volumeDragging = false; command('volume', { percent: Number(input.value), device_id: id }); };
    input.addEventListener('change', done);
  });
}

/* ---------- Småting ---------- */

function fmtTime(ms) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Fast, "tilfeldig" farge per navn til spillelister uten bilde. */
function placeholderColor(name) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `linear-gradient(135deg, hsl(${h} 45% 35%), hsl(${(h + 40) % 360} 55% 25%))`;
}
