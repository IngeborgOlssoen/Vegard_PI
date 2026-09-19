/* Importerer og registrerer alle kort. Legg til to linjer her for et nytt kort,
   og bruk id-en i dashboard.layout i config.yaml. */
import { registerCard } from './index.js';

import lights from './lights.js';
import bus, { createBusCard } from './bus.js';
import weather from './weather.js';
import clock from './clock.js';

registerCard(lights);
registerCard(bus);                          // "bus": alle holdeplassene i ett kort
for (let i = 1; i <= 8; i++) {
  registerCard(createBusCard(`bus${i}`, i - 1));   // "bus1".."bus8": én holdeplass/retning per kort
}
registerCard(weather);
registerCard(clock);
