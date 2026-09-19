# Hjemmepanel

Et lite dashbord og kontrollpanel for hjemmet, laget for en Raspberry Pi 5 med
10" berøringsskjerm. Viser lysstyring for WiZ-pærer, bussavganger fra Ruter/Entur
og vær fra MET (Yr) på én skjerm. Alt er på norsk, og alt kan utvikles og testes
på en vanlig PC først.

## Tekniske valg (kort)

| Del | Valg | Hvorfor |
|---|---|---|
| Backend | Python 3.9+ og FastAPI | Python er «hjemme» på Pi-en (GPIO, systemd), og `pywizlight` styrer WiZ-pærer lokalt over UDP uten sky. FastAPI gir et lite, asynkront API som ikke låser seg når en pære eller tjeneste henger. |
| Frontend | Ren HTML/CSS/JS (ES-moduler), ingen byggesteg | Ingenting å installere eller kompilere, lett å endre på Pi-en med en teksteditor. Hvert «kort» er én JS-fil med en fast kontrakt. |
| Visning | Chromium i kioskmodus | Fullskjerm, god berøringsstøtte, starter automatisk ved oppstart og startes på nytt hvis den dør. |
| Drift | systemd for backend + autostart for kiosk | Backend starter ved boot og restartes automatisk ved feil. |
| Buss | Entur Journey Planner (GraphQL) | Ruters sanntidsdata er tilgjengelig gratis via Entur, uten API-nøkkel. |
| Vær | MET Locationforecast 2.0 | Samme data som Yr, gratis, uten nøkkel (krever bare en identifiserende User-Agent). |
| Musikk | Sonos lokalt (SoCo) + Spotify Web API | Sonos styres direkte på hjemmenettet: avspilling, volum per rom og gruppering virker alltid og raskt. Spotify brukes til spillelister og cover. (Spotify sitt API alene ser ikke Sonos-rom som står stille, og får ikke styre volum på dem.) |
| Konfig | `config/config.yaml` + `config/scenes.json` | Alt du vil endre (pærer, holdeplass, sted, layout, scener) ligger i to lesbare filer. |

**Én skjerm eller flere?** Hovedskjermen viser alt du trenger med et blikk (lys, buss,
vær), og detaljstyring av en pære åpnes som et stort «ark» oppå. Ting som trenger hele
skjermen, som musikk, får en egen side man sveiper til. Sidene og layouten er små
tegninger i `config.yaml`, så nye kort får plass uten å røre koden.

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
      sonos.py         Sonos lokalt (avspilling, rom, volum)
      spotify.py       Spotify Web API (spillelister, cover)
      music.py         setter Sonos og Spotify sammen for musikkortet
    routers/           HTTP-endepunktene under /api/...
    buttons.py         fysiske knapper via GPIO (valgfritt)
  tests/               pytest
frontend/
  index.html
  css/                 base.css (farger, knapper, ark), cards.css (rutenett + kort)
  js/
    app.js             bygger rutenettet, oppdaterer kortene, håndterer feil
    api.js             fetch med tidsavbrudd og norske feilmeldinger
    cards/             ett kort per fil: lights.js, bus.js, weather.js, clock.js, music.js
    components/        sheet.js (ark/dialog), toast.js, icons.js, color.js
config/
  config.example.yaml  mal → kopier til config.yaml
  scenes.example.json  mal → blir til scenes.json første gang appen starter
scripts/               hjelpeskript: finn pærer, holdeplass og koordinater
pi/                    installasjon, systemd-tjeneste og kiosk-skript for Pi-en
```

Dataflyt: nettleseren spør backend (`/api/lights`, `/api/bus`, `/api/weather`)
med faste mellomrom. Backend snakker med pærene lokalt og med Entur/MET på nett.
Feiler en tjeneste, svarer backend med en norsk feilmelding som vises i det
aktuelle kortet, mens de andre kortene fortsetter som før.

## Kom i gang på PC

Krav: Python 3.9 eller nyere (Pi-en har 3.11 eller nyere, Mac-er har ofte 3.9).

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
dem i `config.yaml`). Sett `weather.user_agent` til noe med din e-post
først, ellers kan MET avvise kallene.

Tester: `cd backend && pytest`.

### Test steg for steg

Prosjektet er bygget i steg, ett kort om gangen. Hvert steg er én commit i git,
og du kan teste dem uavhengig ved å endre `dashboard.layout` i `config.yaml`:

1. **Lys** – `layout: ["lights"]`. Med `simulate: true` ser du fire falske pærer.
   Sett `simulate: false` og fyll inn IP-adresser for å styre ekte pærer.
2. **Buss** – `layout: ["bus"]`. Sett holdeplassene under `bus.stops`
   (`python scripts/find_stop.py "Navn"` finner id-ene).
3. **Vær** – `layout: ["weather"]`. Sett `weather.lat/lon` og `user_agent`
   (`python scripts/find_place.py "Sted"`).
4. **Samlet** – standardlayouten viser alt sammen, og `clock` kan legges til.
5. **Musikk** – sett `sonos.simulate: true` og `spotify.simulate: true`, og
   legg til en side med `music` for å se den falske spilleren. Ekte oppsett:
   se «Musikk (Sonos + Spotify)».

## Konfigurasjon

### Pærer

Finn pærene på nettet (PC-en må være på samme nett som pærene):

```bash
python scripts/discover_bulbs.py
```

Skriptet skriver ut en ferdig `bulbs:`-blokk du kan lime inn i `config.yaml`.
Gi gjerne pærene fast IP i ruteren (DHCP-reservasjon). Har du fylt inn `mac`,
finner appen pæra igjen selv om IP-en endrer seg.

Finner ikke søket en pære som står bak en nettverksextender eller mesh-node?
Søket bruker broadcast, som slike bokser ofte stopper, mens selve styringen
går direkte til IP-en og virker likevel. Finn IP-en i WiZ-appen (pæra →
innstillinger → enhetsinformasjon) og sjekk den med
`python scripts/check_bulb.py 10.0.0.42`. Svarer pæra, får du config-blokken
rett fra skriptet. Får pæra en adresse i et annet nett enn resten (f.eks.
192.168.x.x når alt annet er 10.0.0.x), står extenderen i ruter-modus og må
settes i bro-/AP-modus.

### Scener

Scenene ligger i `config/scenes.json` (lages fra `scenes.example.json` første
gang appen starter) og kan endres på to måter:

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

Holdeplassene ligger under `bus.stops`. Hver har en Entur-id som
`NSR:StopPlace:58366`, et valgfritt `name` (ellers brukes navnet fra Entur) og
et valgfritt `line_filter`, f.eks. `["31", "37"]`. Finn id-ene med
`python scripts/find_stop.py "Holdeplassnavn"`.

```yaml
bus:
  stops:
    - stop_place_id: NSR:StopPlace:6451
      name: Dælenenga
    - stop_place_id: NSR:StopPlace:6453
      name: Københavngata
```

Kortet `bus` viser alle holdeplassene under hverandre. Vil du ha ett kort per
holdeplass, bruk `bus1`, `bus2` … `bus8` i layouten (nummeret er plassen i lista):

```yaml
dashboard:
  layout:
    - "lights lights bus1"
    - "lights lights bus2"
    - "lights lights weather"
```

**Dele opp i retning.** En holdeplass har én plattform per retning. Bruk
plattform-id-en (`NSR:Quay:…`) i stedet for holdeplass-id-en, én oppføring per
retning. `--quays` viser plattformene og hvor bussene fra hver av dem går:

```
$ python scripts/find_stop.py "Dælenenga" --quays
  NSR:StopPlace:6451   Dælenenga (Oslo, Oslo) [onstreetBus]
      NSR:Quay:11342   plattform A  →  31 Snarøya, 37 Nydalen
      NSR:Quay:11343   plattform B  →  31 Grorud, 37 Helsfyr
```

```yaml
bus:
  stops:
    - { stop_place_id: NSR:Quay:11342, name: "Dælenenga → sentrum" }
    - { stop_place_id: NSR:Quay:11343, name: "Dælenenga → Grorud" }
    - { stop_place_id: NSR:Quay:11350, name: "Kbh.gata → sentrum" }
    - { stop_place_id: NSR:Quay:11351, name: "Kbh.gata → Grorud" }
dashboard:
  layout:
    - "lights lights bus1 bus2"
    - "lights lights bus3 bus4"
    - "lights lights weather weather"
```

Korte navn passer best når kortene er smale. Kortene tilpasser seg plassen:
smale busskort bruker mindre tekst, og et lavt værkort dropper dagsvarselet.

### Vær

`weather.lat` og `weather.lon` finner du med `python scripts/find_place.py "Sted"`
(bruker Kartverkets stedsnavnsøk). MET krever at `user_agent` inneholder noe som
identifiserer deg (e-post eller nettadresse), ellers kan de blokkere kallene.

### Layout og sider

```yaml
dashboard:
  pages:
    - name: Hjem
      layout:
        - "lights lights bus"
        - "lights lights weather"
        - "clock  clock  weather"
    - name: Musikk
      layout:
        - "music"
  home_after_seconds: 120
```

Hvert ord er en kort-id, og et kort dekker alle cellene der id-en står. Alle
rader på en side må ha like mange ord. Med flere sider sveiper du sidelengs
mellom dem (piltastene virker også på PC), og prikkene nederst viser hvor du
er. `home_after_seconds` sender skjermen tilbake til første side etter en
stund uten berøring (0 = aldri). Et kort kan bare brukes på én side.

### Musikk (Sonos + Spotify)

Musikksiden styrer Sonos-høyttalerne direkte på hjemmenettet: hva som
spilles, spill/pause/neste, volum per rom og hvilke rom som spiller sammen.
Spillelistene og coverbildene kommer fra Spotify-kontoen din, og en spilleliste
startes ved at Sonos legger den i køen med sin egen Spotify-kobling.

**Sonos** (ingen innlogging, bare samme nett):

```yaml
sonos:
  enabled: true
  default_room: Stue      # rommet som er valgt når panelet starter
```

Panelet finner høyttalerne selv. Gjør det ikke det (f.eks. gjennom en
extender), oppgi IP-en til én av dem under `speakers`; resten finnes via den.
IP-en står i Sonos-appen under Innstillinger → System → Om systemet.

**Spotify** (for spillelister; krever Premium og en gratis «app»):

1. Legg Spotify-kontoen til i Sonos-appen (Innstillinger → Tjenester og stemme),
   ellers kan ikke Sonos spille spillelistene.
2. Gå til <https://developer.spotify.com/dashboard>, lag en app (navn f.eks.
   Hjemmepanel), sett Redirect URI til nøyaktig `http://127.0.0.1:8888/callback`
   og kryss av for Web API. Kopier «Client ID».
3. I `config.yaml`: `spotify.enabled: true` og `spotify.client_id: <id>`.
4. Logg inn én gang fra en PC med nettleser (venv aktivert):

   ```bash
   python scripts/spotify_login.py
   ```

   Nøkkelen lagres i `config/spotify_token.json`, og backend fornyer den selv.
5. Skal panelet kjøre på Pi-en, kopier nøkkelen dit:
   `scp config/spotify_token.json pi@<pi-adresse>:~/hjemmepanel/config/`

Legg til musikksiden under `dashboard.pages` (se «Layout og sider»), og restart
backend. Vil du se siden på PC uten høyttalere, sett `sonos.simulate: true` og
`spotify.simulate: true`.

**Rom-arket** («Spilles på …»-knappen): trykk på et rom for å spille der. Spiller
det allerede musikk, blir rommet med i gruppa; trykk igjen for å ta det ut.
Hver rad har sin egen volumskyver, og skyveren på hovedsiden styrer hele gruppa.

**Feilsøking:** `python scripts/sonos_check.py` viser rommene slik panelet ser
dem, hvilken Spotify-variant Sonos-systemet bruker og hva som spilles.
`--play spotify:playlist:<id>` prøver å legge ei liste i køen og sier hvor mange
sanger som kom inn. Kommer det ingen, er Spotify ikke lagt til i Sonos-appen
med kontoen spillelistene tilhører.

**Uten Sonos:** med bare `spotify.enabled` går avspillingen via Spotify Connect,
som virker for mange andre høyttalere. `python scripts/spotify_status.py` viser
hva Spotify svarer, inkludert hvilke høyttalere den kjenner til.

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
5. Legger `pi/kiosk.sh` i autostart for skrivebordet (labwc, Wayfire eller
   LXDE), slik at Chromium åpner panelet i fullskjerm ved oppstart, og slår på
   automatisk innlogging. Skriptet venter til backend svarer, og starter
   Chromium på nytt hvis den skulle dø.
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
   Kontrakten er beskrevet øverst i `frontend/js/cards/index.js`. Se
   `clock.js` for det minste mulige eksempelet og `bus.js` for et kort som
   henter data fra backend. Kaster `refresh()` en feil, vises meldingen i
   kortet og forrige innhold blir stående.
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

## Slik håndteres feil

- Hvert kort har sin egen oppdateringsløkke. Feiler ett kort, viser det en rød
  melding øverst og beholder forrige innhold; de andre kortene merker ingenting.
- Værkortet viser forrige varsel med en advarsel hvis MET ikke svarer.
  Busskortet teller ned lokalt til nettet er tilbake.
- En pære som ikke svarer vises med stiplet ramme og «Ingen kontakt», og
  panelet leter etter den igjen på nettet hvis `mac` er satt.
- Mister skjermen kontakt med backend i over ett minutt, dekkes den av
  «Ingen kontakt med serveren» til den svarer igjen. systemd starter backend
  på nytt, og `kiosk.sh` starter Chromium på nytt.

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
