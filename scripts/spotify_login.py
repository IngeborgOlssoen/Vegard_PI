#!/usr/bin/env python3
"""Kobler Hjemmepanel til Spotify-kontoen din (gjøres én gang).

Forberedelse (5 minutter):
  1. Gå til https://developer.spotify.com/dashboard og logg inn.
  2. "Create app": navn f.eks. Hjemmepanel, Redirect URI = http://127.0.0.1:8888/callback
     (nøyaktig slik – Spotify godtar ikke "localhost"), kryss av for "Web API".
  3. Kopier "Client ID" inn i config/config.yaml under spotify.client_id, og sett
     spotify.enabled: true.

Kjør så dette skriptet på en PC med nettleser (venv aktivert, fra repo-roten):
    python scripts/spotify_login.py

Nettleseren åpner Spotify sin innloggingsside. Når du har godkjent, lagres en
nøkkel i config/spotify_token.json. Skal panelet kjøre på Pi-en, kopier fila
dit (scp config/spotify_token.json pi@<pi>:~/hjemmepanel/config/) eller kjør
skriptet på Pi-en med skrivebord.

Bruker "PKCE"-flyten, så ingen hemmelighet (client secret) trengs.
"""
import base64
import hashlib
import json
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import load_config  # noqa: E402  (bruker samme config-lasting som backend)
from app.services.spotify import SCOPES, SPOTIFY_AUTHORIZE_URL, SPOTIFY_TOKEN_URL  # noqa: E402


def main() -> None:
    cfg = load_config()
    sp = cfg.spotify
    if not sp.client_id:
        print("spotify.client_id mangler i config/config.yaml. Se toppen av dette skriptet.")
        sys.exit(1)

    redirect = urllib.parse.urlparse(sp.redirect_uri)
    if redirect.hostname in (None, "localhost"):
        print("spotify.redirect_uri må bruke 127.0.0.1, f.eks. http://127.0.0.1:8888/callback")
        sys.exit(1)

    # PKCE: en tilfeldig "verifier" og en hash av den som sendes først
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": sp.client_id, "response_type": "code", "redirect_uri": sp.redirect_uri,
        "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state,
    }
    url = f"{SPOTIFY_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if urllib.parse.urlparse(self.path).path != redirect.path:
                self.send_response(404); self.end_headers(); return
            if q.get("state", [""])[0] != state:
                self._page(400, "Feil state – prøv igjen."); return
            if "error" in q:
                result["error"] = q["error"][0]
                self._page(400, f"Spotify sa nei: {q['error'][0]}"); return
            result["code"] = q.get("code", [""])[0]
            self._page(200, "Ferdig! Du kan lukke dette vinduet og gå tilbake til terminalen.")

        def _page(self, status, text):
            body = f"<html><body style='font-family:sans-serif;font-size:20px;padding:40px'>{text}</body></html>".encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer((redirect.hostname, redirect.port or 80), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print("Åpner Spotify i nettleseren. Hvis ingenting skjer, lim inn denne adressen selv:\n")
    print(url, "\n")
    webbrowser.open(url)

    print("Venter på at du godkjenner i nettleseren ...")
    deadline = time.time() + 300
    while not result and time.time() < deadline:
        time.sleep(0.5)
    server.shutdown()
    if "code" not in result:
        print("Fikk ingen godkjenning innen 5 minutter." if not result else f"Feil: {result.get('error')}")
        sys.exit(1)

    data = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": result["code"], "redirect_uri": sp.redirect_uri,
        "client_id": sp.client_id, "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(SPOTIFY_TOKEN_URL, data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as exc:
        print(f"Spotify avviste innloggingen (HTTP {exc.code}): {exc.read().decode(errors='replace')}")
        sys.exit(1)

    token_path = cfg.resolve(sp.token_file)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as f:
        json.dump({
            "access_token": body["access_token"],
            "refresh_token": body["refresh_token"],
            "expires_at": time.time() + int(body.get("expires_in", 3600)),
            "scope": body.get("scope", ""),
        }, f, indent=2)
    print(f"\nInnlogget! Nøkkelen er lagret i {token_path}.")
    print("Start backend på nytt, så er musikksiden klar.")


if __name__ == "__main__":
    main()
