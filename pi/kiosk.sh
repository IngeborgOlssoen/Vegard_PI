#!/usr/bin/env bash
# Åpner Hjemmepanel i Chromium i kioskmodus (fullskjerm, uten knapper og
# meldinger) og holder den i live. Settes i autostart av pi/install.sh, men
# kan også kjøres for hånd fra en terminal på skrivebordet for å se feil.
#
# Miljøvariabel HJEMMEPANEL_URL kan overstyre adressen (standard localhost:8000).

URL="${HJEMMEPANEL_URL:-http://localhost:8000}"

BROWSER="$(command -v chromium-browser || command -v chromium || true)"
if [ -z "$BROWSER" ]; then
  echo "Fant ikke Chromium. Installer med: sudo apt install chromium" >&2
  exit 1
fi

# Vent til backend svarer – den bruker noen sekunder etter oppstart, og
# nettet kan komme sent. Uten dette ville Chromium vist en feilside.
echo "Venter på $URL ..."
until curl -sf "$URL/api/health" >/dev/null 2>&1; do
  sleep 2
done

# På X11: skru av skjermsparer. (På Wayland/labwc gjøres dette av install.sh via raspi-config.)
if command -v xset >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
  xset s off 2>/dev/null; xset -dpms 2>/dev/null; xset s noblank 2>/dev/null
fi

while true; do
  "$BROWSER" \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --no-first-run \
    --incognito \
    --start-maximized \
    --touch-events=enabled \
    --overscroll-history-navigation=0 \
    --disable-pinch \
    --check-for-update-interval=31536000 \
    --autoplay-policy=no-user-gesture-required \
    "$URL"
  # Hit kommer vi bare hvis Chromium avsluttet (krasj, noen lukket den). Start på nytt.
  echo "Chromium avsluttet, starter på nytt om 3 sekunder ..."
  sleep 3
done
