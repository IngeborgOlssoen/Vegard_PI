/* Fargehjelpere for lyskortet. */

/** Omtrentlig RGB for en fargetemperatur i kelvin (Tanner Hellands tilnærming). */
export function kelvinToRgb(kelvin) {
  const t = Math.min(40000, Math.max(1000, kelvin)) / 100;
  let r, g, b;
  if (t <= 66) {
    r = 255;
    g = 99.47 * Math.log(t) - 161.12;
    b = t <= 19 ? 0 : 138.52 * Math.log(t - 10) - 305.04;
  } else {
    r = 329.7 * Math.pow(t - 60, -0.1332);
    g = 288.12 * Math.pow(t - 60, -0.0755);
    b = 255;
  }
  return [r, g, b].map((v) => Math.round(Math.min(255, Math.max(0, v))));
}

/** HSV (h 0–360, s og v 0–1) → [r, g, b] */
export function hsvToRgb(h, s, v) {
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  let [r, g, b] = [0, 0, 0];
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  return [r, g, b].map((v) => Math.round((v + m) * 255));
}

/** Fargetonen (0–360) til en RGB-farge, brukes til å plassere fargeskyveren. */
export function rgbToHue([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  if (d === 0) return 0;
  let h;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  h = Math.round(h * 60);
  return h < 0 ? h + 360 : h;
}

export function rgbCss([r, g, b]) {
  return `rgb(${r}, ${g}, ${b})`;
}

/** Kort norsk beskrivelse av en fargetemperatur. */
export function describeKelvin(k) {
  if (k == null) return 'Hvitt';
  if (k < 3300) return 'Varmhvitt';
  if (k < 5000) return 'Nøytralt';
  return 'Kaldhvitt';
}
