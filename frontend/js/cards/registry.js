/* Importerer og registrerer alle kort. Legg til to linjer her for et nytt kort,
   og bruk id-en i dashboard.layout i config.yaml. */
import { registerCard } from './index.js';

import lights from './lights.js';
import bus, { createBusCard } from './bus.js';
import weather from './weather.js';
import clock from './clock.js';

registerCard(lights);
registerCard(bus);                          // "bus": alle holdeplassene i ett kort
registerCard(createBusCard('bus1', 0));     // "bus1": bare første holdeplass i bus.stops
registerCard(createBusCard('bus2', 1));     // "bus2": andre holdeplass
registerCard(createBusCard('bus3', 2));     // "bus3": tredje holdeplass
registerCard(weather);
registerCard(clock);
