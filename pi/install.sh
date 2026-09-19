#!/usr/bin/env bash
# Installerer Hjemmepanel på en Raspberry Pi med Raspberry Pi OS (Bookworm
# eller nyere) *med skrivebord*. Kan trygt kjøres flere ganger, også for å
# oppdatere etter `git pull`.
#
#   cd ~/hjemmepanel && bash pi/install.sh
#
# Gjør dette:
#   1. installerer Chromium, Python-venv og GPIO-bibliotek (apt)
#   2. lager .venv og installerer Python-avhengigheter
#   3. lager config/config.yaml fra malen hvis den mangler
#   4. installerer og starter systemd-tjenesten "hjemmepanel" (backend)
#   5. legger pi/kiosk.sh i autostart for skrivebordet, og slår på automatisk innlogging
#   6. skrur av skjermsparer/blanking
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"

echo "== Hjemmepanel: installerer fra $DIR for bruker $USER_NAME"

echo "== 1/6 Pakker fra apt"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip python3-gpiozero python3-lgpio curl git
# Pakken heter "chromium" på nyere Pi OS og "chromium-browser" på eldre
sudo apt-get install -y -qq chromium 2>/dev/null || sudo apt-get install -y -qq chromium-browser

echo "== 2/6 Python-miljø (.venv)"
if [ ! -d "$DIR/.venv" ]; then
  # --system-site-packages: gjør gpiozero/lgpio fra apt synlige i venv (til fysiske knapper)
  python3 -m venv --system-site-packages "$DIR/.venv"
fi
"$DIR/.venv/bin/pip" install -q --upgrade pip
"$DIR/.venv/bin/pip" install -q -r "$DIR/backend/requirements.txt"

echo "== 3/6 Konfigurasjon"
if [ ! -f "$DIR/config/config.yaml" ]; then
  cp "$DIR/config/config.example.yaml" "$DIR/config/config.yaml"
  echo "   Laget config/config.yaml fra malen. Husk å sette simulate: false og fylle inn"
  echo "   pærer, holdeplass og sted, og start tjenesten på nytt etterpå."
fi

echo "== 4/6 systemd-tjeneste (backend)"
sed -e "s#__DIR__#$DIR#g" -e "s#__USER__#$USER_NAME#g" "$DIR/pi/hjemmepanel.service" \
  | sudo tee /etc/systemd/system/hjemmepanel.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable hjemmepanel.service >/dev/null
sudo systemctl restart hjemmepanel.service

echo "== 5/6 Autostart av kiosk"
chmod +x "$DIR/pi/kiosk.sh"
KIOSK="$DIR/pi/kiosk.sh"

# labwc (standard skrivebord på Pi OS fra høsten 2024)
mkdir -p "$HOME_DIR/.config/labwc"
LABWC="$HOME_DIR/.config/labwc/autostart"
touch "$LABWC"
grep -qF "pi/kiosk.sh" "$LABWC" || echo "$KIOSK &" >> "$LABWC"

# Wayfire (Pi OS Bookworm før høsten 2024)
WAYFIRE="$HOME_DIR/.config/wayfire.ini"
if [ -f "$WAYFIRE" ] && ! grep -qF "pi/kiosk.sh" "$WAYFIRE"; then
  if grep -q '^\[autostart\]' "$WAYFIRE"; then
    sed -i "/^\[autostart\]/a hjemmepanel = $KIOSK" "$WAYFIRE"
  else
    printf '\n[autostart]\nhjemmepanel = %s\n' "$KIOSK" >> "$WAYFIRE"
  fi
fi

# X11/LXDE (hvis Wayland er skrudd av)
if [ -f /etc/xdg/lxsession/LXDE-pi/autostart ]; then
  mkdir -p "$HOME_DIR/.config/lxsession/LXDE-pi"
  LX="$HOME_DIR/.config/lxsession/LXDE-pi/autostart"
  [ -f "$LX" ] || cp /etc/xdg/lxsession/LXDE-pi/autostart "$LX"
  grep -qF "pi/kiosk.sh" "$LX" || echo "@$KIOSK" >> "$LX"
fi
chown -R "$USER_NAME" "$HOME_DIR/.config" 2>/dev/null || true

if command -v raspi-config >/dev/null 2>&1; then
  # B4 = start skrivebordet og logg inn automatisk, så kiosken kommer opp uten tastatur
  sudo raspi-config nonint do_boot_behaviour B4 || true
fi

echo "== 6/6 Skjermsparer av"
if command -v raspi-config >/dev/null 2>&1; then
  sudo raspi-config nonint do_blanking 1 || true
fi

echo
echo "== Ferdig!"
echo "   Backend:  sudo systemctl status hjemmepanel   (logg: journalctl -u hjemmepanel -f)"
echo "   Nettleser på PC: http://$(hostname -I 2>/dev/null | awk '{print $1}'):8000"
echo "   Rediger config/config.yaml, kjør 'sudo systemctl restart hjemmepanel', og"
echo "   start Pi-en på nytt (sudo reboot) for å se kiosken komme opp av seg selv."
