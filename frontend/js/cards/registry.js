/* Importerer og registrerer alle kort. Legg til to linjer her for et nytt kort,
   og bruk id-en i dashboard.layout i config.yaml. */
import { registerCard } from './index.js';

import lights from './lights.js';
import bus from './bus.js';
import weather from './weather.js';
import clock from './clock.js';

registerCard(lights);
registerCard(bus);
registerCard(weather);
registerCard(clock);
