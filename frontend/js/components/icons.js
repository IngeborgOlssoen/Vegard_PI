/* Enkle strek-ikoner som SVG. Ingen eksterne fonter eller emoji, så de ser
   like ut på Pi-en som på PC. Bruk: el.innerHTML = icon('bulb'). */

const PATHS = {
  // lys
  bulb: '<path fill="currentColor" stroke="none" opacity=".95" d="M12 2.5a6.5 6.5 0 0 0-4.2 11.4c.8.7 1.2 1.6 1.2 2.6h6c0-1 .4-1.9 1.2-2.6A6.5 6.5 0 0 0 12 2.5z"/><path d="M9.5 19h5M10.5 21.5h3"/>',
  power: '<path d="M12 3v8"/><path d="M6.6 6.6a7.5 7.5 0 1 0 10.8 0"/>',
  // scener
  moon: '<path d="M20.5 13.5A8.5 8.5 0 1 1 10.5 3.5a7 7 0 0 0 10 10z"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7.5 4v16M16.5 4v16M3 9h4.5M3 15h4.5M16.5 9H21M16.5 15H21"/>',
  off: '<path d="M12 3v8"/><path d="M6.6 6.6a7.5 7.5 0 1 0 10.8 0"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/>',
  star: '<path d="M12 3l2.8 5.8 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 3 1.1-6.2L3 9.7l6.2-.9z"/>',
  coffee: '<path d="M4 8h12v6a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4z"/><path d="M16 9.5h1.5a2.25 2.25 0 0 1 0 4.5H16M7 3v2.5M10 3v2.5M13 3v2.5"/>',
  book: '<path d="M4 4.5h6a2.5 2.5 0 0 1 2.5 2.5v12.5A2 2 0 0 0 10.5 18H4zM20 4.5h-6A2.5 2.5 0 0 0 11.5 7v12.5a2 2 0 0 1 2-1.5H20z"/>',
  party: '<path d="M5 20l3.5-9.5 6 6zM13 8.5l2.5-2.5M15.5 12.5l3-1M11 6l-1-3M17.5 5.5l1-2.5M19.5 9.5l2.5 1"/>',
  // vær
  cloud: '<path d="M7 18.5a4 4 0 0 1-.5-8A6 6 0 0 1 18 9.5a4.5 4.5 0 0 1-.5 9z"/>',
  partly_day: '<circle cx="7.5" cy="7.5" r="2.7"/><path d="M7.5 2v1.3M2 7.5h1.3M3.6 3.6l.9.9M11.4 3.6l-.9.9"/><path d="M9.5 20a3.5 3.5 0 0 1-.4-7A5 5 0 0 1 18.6 13.5 3.3 3.3 0 0 1 18 20z"/>',
  partly_night: '<path d="M10.2 7.8A3.2 3.2 0 1 1 6.5 4a2.7 2.7 0 0 0 3.7 3.8z"/><path d="M9.5 20a3.5 3.5 0 0 1-.4-7A5 5 0 0 1 18.6 13.5 3.3 3.3 0 0 1 18 20z"/>',
  rain: '<path d="M7 15a4 4 0 0 1-.5-8A6 6 0 0 1 18 6a4.5 4.5 0 0 1-.5 9z"/><path d="M8.5 18l-1 3M12.5 18l-1 3M16.5 18l-1 3"/>',
  heavyrain: '<path d="M7 14a4 4 0 0 1-.5-8A6 6 0 0 1 18 5a4.5 4.5 0 0 1-.5 9z"/><path d="M7.5 16.5l-1 3M10.5 16.5l-1 3M13.5 16.5l-1 3M16.5 16.5l-1 3M9 20.5l-.5 1.5M12 20.5l-.5 1.5M15 20.5l-.5 1.5"/>',
  sleet: '<path d="M7 15a4 4 0 0 1-.5-8A6 6 0 0 1 18 6a4.5 4.5 0 0 1-.5 9z"/><path d="M8 18l-1 3M16 18l-1 3"/><circle cx="12" cy="19.5" r="1.1"/>',
  snow: '<path d="M7 15a4 4 0 0 1-.5-8A6 6 0 0 1 18 6a4.5 4.5 0 0 1-.5 9z"/><circle cx="8" cy="19" r="1.1"/><circle cx="12" cy="20.5" r="1.1"/><circle cx="16" cy="19" r="1.1"/>',
  thunder: '<path d="M7 14a4 4 0 0 1-.5-8A6 6 0 0 1 18 5a4.5 4.5 0 0 1-.5 9z"/><path d="M13 12.5l-2.5 4.5h3l-2.5 4.5"/>',
  fog: '<path d="M4 9.5h16M4 13.5h12M8 17.5h12"/>',
  wind: '<path d="M3 8h10a2.5 2.5 0 1 0-2.5-2.5M3 12h15a2.5 2.5 0 1 1-2.5 2.5M3 16h8a2 2 0 1 1-2 2"/>',
  drop: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
  thermometer: '<path d="M10 4a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z"/><path d="M12 10v6"/>',
  // annet
  bus: '<rect x="4" y="3" width="16" height="15" rx="3"/><path d="M4 9.5h16M8 21v-3M16 21v-3M8 14.5h.01M16 14.5h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  warning: '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4M12 17.5h.01"/>',
};

export function icon(name, cls = '') {
  const body = PATHS[name] || PATHS.star;
  return `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
}
