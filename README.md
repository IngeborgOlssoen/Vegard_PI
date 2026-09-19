# Hjemmepanel

Et lite dashbord og kontrollpanel for hjemmet, laget for en Raspberry Pi 5 med
10" berøringsskjerm. Viser lysstyring for WiZ-pærer, bussavganger fra Ruter/Entur
og vær fra MET (Yr) på én skjerm. Alt er på norsk, og alt kan utvikles og testes
på en vanlig PC først.

## Tekniske valg (kort)

| Del | Valg | Hvorfor |
|---|---|---|
| Backend | Python 3.11+ og FastAPI | Python er «hjemme» på Pi-en (GPIO, systemd), og `pywizlight` styrer WiZ-pærer lokalt over UDP uten sky. FastAPI gir et lite, asynkront API som ikke låser seg når en pære eller tjeneste henger. |
| Frontend | Ren HTML/CSS/JS (ES-moduler), ingen byggesteg | Ingenting å installere eller kompilere, lett å endre på Pi-en med en teksteditor. Hvert «kort» er én JS-fil med en fast kontrakt. |
| Visning | Chromium i kioskmodus | Fullskjerm, god berøringsstøtte, starter automatisk ved oppstart og startes på nytt hvis den dør. |
| Drift | systemd for backend + autostart for kiosk | Backend starter ved boot og restartes automatisk ved feil. |
| Buss | Entur Journey Planner (GraphQL) | Ruters sanntidsdata er tilgjengelig gratis via Entur, uten API-nøkkel. |
| Vær | MET Locationforecast 2.0 | Samme data som Yr, gratis, uten nøkkel (krever bare en identifiserende User-Agent). |
| Konfig | `config/config.yaml` + `config/scenes.json` | Alt du vil endre (pærer, holdeplass, sted, layout, scener) ligger i to lesbare filer. |

**Én skjerm eller flere?** Én skjerm. Verdien i et slikt panel er at du ser buss og vær
med et blikk, og at lyset er ett trykk unna. Sveiping mellom sider på en kiosk-skjerm
er lett å bomme på. Løsningen er at hovedskjermen viser alle kortene, mens detaljstyring
av en pære (dimming, farge) åpnes som et stort «ark» oppå. Layouten er en liten tegning i
`config.yaml`, så nye kort får plass uten å røre koden.

## Oppbygging

```
backend/
  app/
    main.py            FastAPI-app, monterer API og frontend
    config.py          leser og validerer config/config.yaml
    errors.py          feil → JSON med norsk melding (aldri krasj)
    services/
      lights.py        WiZ-pærer (ekte + simulert)
      scenes.py        lys-scener (config/scenes.json)
      bus.py           Entur (Ruter sanntid)
      weather.py       MET Locationforecast
    routers/           HTTP-endepunktene under /api/...
    buttons.py         fysiske knapper via GPIO (valgfritt)
  tests/               pytest
frontend/
  index.html
  css/                 base.css (farger, knapper, ark), cards.css (rutenett + kort)
  js/
    app.js             bygger rutenettet, oppdaterer kortene, håndterer feil
    api.js             fetch med tidsavbrudd og norske feilmeldinger
    cards/             ett kort per fil: lights.js, bus.js, weather.js, clock.js
    components/        sheet.js (ark/dialog), toast.js, icons.js
config/
  config.example.yaml  mal → kopier til config.yaml
  scenes.json          lys-scener (kan endres for hånd eller fra skjermen)
scripts/               hjelpeskript: finn pærer, holdeplass og koordinater
pi/                    installasjon, systemd-tjeneste og kiosk-skript for Pi-en
```

Dataflyt: nettleseren spør backend (`/api/lights`, `/api/bus`, `/api/weather`)
med faste mellomrom. Backend snakker med pærene lokalt og med Entur/MET på nett.
Feiler en tjeneste, svarer backend med en norsk feilmelding som vises i det
aktuelle kortet, mens de andre kortene fortsetter som før.

## Kom i gang på PC

Krav: Python 3.11 eller nyere.

```bash
git clone <dette repoet> hjemmepanel
cd hjemmepanel
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cp config/config.example.yaml config/config.yaml
cd backend
python -m app --reload
```

Åpne <http://localhost:8000>. Malen har `lights.simulate: true`, så lyskortet
virker med falske pærer uten at du har WiZ-pærer i nærheten. Buss og vær
henter ekte data med en gang (holdeplassen og stedet i malen er Oslo, bytt
dem i `config.yaml`).

Tester: `cd backend && pytest`.

### Test steg for steg

Prosjektet er bygget i steg, ett kort om gangen. Hvert steg er én commit i git,
og du kan teste dem uavhengig ved å endre `dashboard.layout` i `config.yaml`:

1. **Lys** – `layout: ["lights"]`. Med `simulate: true` ser du fire falske pærer.
   Sett `simulate: false` og fyll inn IP-adresser for å styre ekte pærer.
2. **Buss** – `layout: ["bus"]`. Sett `bus.stop_place_id` til din holdeplass
   (`python scripts/find_stop.py "Navn"`).
3. **Vær** – `layout: ["weather"]`. Sett `weather.lat/lon` og `user_agent`
   (`python scripts/find_place.py "Sted"`).
4. **Samlet** – standardlayouten viser alt sammen, og `clock` kan legges til.

## Konfigurasjon

### Pærer

Finn pærene på nettet (PC-en må være på samme nett som pærene):

```bash
python scripts/discover_bulbs.py
```

Skriptet skriver ut en ferdig `bulbs:`-blokk du kan lime inn i `config.yaml`.
Gi gjerne pærene fast IP i ruteren (DHCP-reservasjon). Har du fylt inn `mac`,
finner appen pæra igjen selv om IP-en endrer seg.

### Scener

Scenene ligger i `config/scenes.json` og kan endres på to måter:

- **I fila.** Hver scene har en `default` (gjelder alle pærer) og valgfrie
  `bulbs` som overstyrer enkeltpærer. Fila leses på nytt automatisk.
- **Fra skjermen.** Still lysene slik du vil ha dem, og hold fingeren på
  scene-knappen i ett sekund. Da lagres nåværende tilstand i den scenen.

```json
{
  "id": "kveld",
  "name": "Kveld",
  "icon": "moon",
  "default": { "on": true, "brightness": 35, "colortemp": 2700 },
  "bulbs": { "soverom": { "on": false } }
}
```

`brightness` er 0–100, `colortemp` er i kelvin (2200–6500), `rgb` er `[r, g, b]`.
Ikoner: `moon`, `film`, `off`, `sun`, `star`, `coffee`, `book`, `party`.

### Buss

`bus.stop_place_id` skal være en Entur-id som `NSR:StopPlace:58366`. Finn den med
`python scripts/find_stop.py "Holdeplassnavn"`. Du kan også bruke en
`NSR:Quay:`-id hvis du bare vil se én retning/plattform. `line_filter` begrenser
til bestemte linjer, f.eks. `["31", "37"]`.

### Vær

`weather.lat` og `weather.lon` finner du med `python scripts/find_place.py "Sted"`
(bruker Kartverkets stedsnavnsøk). MET krever at `user_agent` inneholder noe som
identifiserer deg (e-post eller nettadresse), ellers kan de blokkere kallene.

### Layout

```yaml
dashboard:
  layout:
    - "lights lights bus"
    - "lights lights weather"
```

Hvert ord er en kort-id, og et kort dekker alle cellene der id-en står. Alle
rader må ha like mange ord. Eksempel med klokke:

```yaml
  layout:
    - "lights lights bus"
    - "lights lights weather"
    - "clock  clock  weather"
```

## Oppsett på Raspberry Pi 5

Forutsetter Raspberry Pi OS (Bookworm eller nyere) *med skrivebord*, og at
Pi-en er på samme nett som pærene.

```bash
sudo apt update && sudo apt install -y git
git clone <dette repoet> ~/hjemmepanel
cd ~/hjemmepanel
bash pi/install.sh
```

Skriptet gjør dette (og kan kjøres flere ganger uten skade):

1. Installerer Chromium, Python-venv og GPIO-bibliotek via apt.
2. Lager `.venv` og installerer `backend/requirements.txt`.
3. Kopierer `config.example.yaml` til `config.yaml` hvis den mangler.
4. Installerer og starter systemd-tjenesten `hjemmepanel` (backend), med
   automatisk omstart ved feil.
5. Legger `pi/kiosk.sh` i autostart for skrivebordet (labwc eller Wayfire), slik
   at Chromium åpner panelet i fullskjerm ved oppstart. Skriptet venter til
   backend svarer, og starter Chromium på nytt hvis den skulle dø.
6. Skrur av skjermsparer/blanking.

Etterpå: rediger `config/config.yaml` (sett `simulate: false`, fyll inn pærer,
holdeplass og sted), og start tjenesten på nytt:

```bash
sudo systemctl restart hjemmepanel
sudo systemctl status hjemmepanel      # er den oppe?
journalctl -u hjemmepanel -f           # logg
```

Start Pi-en på nytt (`sudo reboot`) for å se at alt kommer opp av seg selv.

Oppdatere til ny versjon senere:

```bash
cd ~/hjemmepanel && git pull && bash pi/install.sh && sudo systemctl restart hjemmepanel
```

### Når skjermen skrus av og på

Pi-en bør stå på hele tiden; panelet er da alltid klart når skjermen får strøm.
Vil du at skjermen skal slukke om natta, kan du legge til en `cron`-jobb med
`wlr-randr --output HDMI-A-1 --off` / `--on` (labwc) – panelet fortsetter å
kjøre i bakgrunnen.

## Utvide senere

### Nytt kort

1. Lag `frontend/js/cards/mittkort.js` som eksporterer et objekt med
   `id`, `title`, `refreshMs`, `mount(body, ctx)` og `refresh(ctx)`.
   Se `clock.js` for det minste mulige eksempelet og `bus.js` for et kort som
   henter data fra backend.
2. Registrer det i `frontend/js/cards/registry.js`.
3. Legg id-en inn i `dashboard.layout` i `config.yaml`.

Trenger kortet data fra backend, lag en fil under `backend/app/services/` og en
router under `backend/app/routers/`, og monter routeren i `main.py`. Kast
`ServiceError("norsk melding")` ved feil, så vises meldingen i kortet.

### Fysiske knapper

Koble en trykknapp mellom en GPIO-pinne og GND, og sett i `config.yaml`:

```yaml
buttons:
  enabled: true
  buttons:
    - { gpio: 17, action: scene, scene: kveld }
    - { gpio: 27, action: toggle_all }
    - { gpio: 22, action: toggle_bulb, bulb: kjokken }
```

Handlinger: `scene`, `toggle_all`, `all_on`, `all_off`, `toggle_bulb`.
Koden ligger i `backend/app/buttons.py` og bruker `gpiozero`, som følger med
Raspberry Pi OS. Er `gpiozero` ikke installert, logges en advarsel og resten
av panelet virker som før.

## Feilsøking

- **«Ingen kontakt med pæren»** – sjekk at Pi-en og pæra er på samme nett, at
  IP-en stemmer (`python scripts/discover_bulbs.py`), og at pæra har strøm
  (en pære som er skrudd av på bryteren svarer ikke).
- **«Fikk ikke kontakt med Entur / MET»** – nettet er nede eller tjenesten
  har problemer. Kortet viser forrige data og prøver igjen av seg selv.
- **MET svarer 403** – `weather.user_agent` mangler kontaktinfo.
- **Skjermen viser «Ingen kontakt med serveren»** – backend er nede.
  `sudo systemctl status hjemmepanel` og `journalctl -u hjemmepanel -n 50`.
- **Chromium starter ikke ved boot** – sjekk at `pi/kiosk.sh` står i
  `~/.config/labwc/autostart` (eller `~/.config/wayfire.ini`), og kjør
  `bash pi/kiosk.sh` for hånd fra en terminal på skrivebordet for å se feil.
