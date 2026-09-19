/* Register over alle kort. Nye kort legges til her (og i layout i config.yaml).
   Hvert kort er en modul som eksporterer et objekt med denne kontrakten:

   export default {
     id: 'bus',                 // id-en som brukes i layout
     title: 'Buss',             // overskrift på kortet
     refreshMs: 30000,          // hvor ofte refresh() kalles (0 = aldri)
     mount(body, ctx) {},       // bygg innholdet én gang. ctx = { config, setStatus, setError, setTitle, showToast }
     async refresh(ctx) {},     // hent nye data. Kast en Error med norsk melding ved feil.
                                // Kan returnere { warning: 'tekst' } for å vise en advarsel.
     tick(ctx) {},              // (valgfritt) kalles hvert sekund, f.eks. for nedtelling
   }
*/

const registry = {};

export function registerCard(card) {
  registry[card.id] = card;
}

export function getCard(id) {
  return registry[id];
}
