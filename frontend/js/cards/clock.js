/* Klokkekortet: klokkeslett og dato. Det minste mulige kortet – fint som mal
   for nye kort. Ingen data fra backend, bare tick() hvert sekund. */

let timeEl = null;
let dateEl = null;

export default {
  id: 'clock',
  title: 'Klokke',
  refreshMs: 0,          // ingen refresh() – alt skjer i tick()
  headerless: true,      // ingen overskrift, klokka taler for seg selv

  mount(body) {
    body.innerHTML = `
      <div class="clock">
        <div class="clock-time" data-time></div>
        <div class="clock-date" data-date></div>
      </div>`;
    timeEl = body.querySelector('[data-time]');
    dateEl = body.querySelector('[data-date]');
    this.tick();
  },

  tick() {
    const now = new Date();
    timeEl.textContent = now.toLocaleTimeString('nb-NO', { hour: '2-digit', minute: '2-digit' });
    const date = now.toLocaleDateString('nb-NO', { weekday: 'long', day: 'numeric', month: 'long' });
    dateEl.textContent = date.charAt(0).toUpperCase() + date.slice(1);
  },
};
