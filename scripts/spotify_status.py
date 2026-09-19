#!/usr/bin/env python3
"""Viser hva Spotify svarer panelet: innlogging, høyttalere og hva som spilles.

Bruk (venv aktivert, fra repo-roten):
    python scripts/spotify_status.py

Nyttig når musikksiden ikke finner Sonos-høyttalerne: er lista fra Spotify tom,
må Spotify kobles til i Sonos-appen (samme konto!), og et rom må velges fra
Spotify-appen én gang. Panelet kan bare vise det Spotify selv kjenner til.
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _need_venv(module: str) -> None:
    print(f"Fant ikke pakken «{module}». Aktiver først det virtuelle miljøet, så prøv igjen:\n")
    print("    source .venv/bin/activate        (Windows: .venv\\Scripts\\activate)")
    print(f"    python {sys.argv[0]}\n")
    sys.exit(1)


try:
    import httpx  # noqa: E402
    from app.config import load_config  # noqa: E402
    from app.errors import ServiceError  # noqa: E402
    from app.services.spotify import SpotifyService  # noqa: E402
except ImportError as exc:
    _need_venv(exc.name or "httpx")


async def main() -> None:
    cfg = load_config()
    token_path = cfg.resolve(cfg.spotify.token_file)
    print(f"Config:      client_id {'satt' if cfg.spotify.client_id else 'MANGLER'}, "
          f"enabled={cfg.spotify.enabled}, simulate={cfg.spotify.simulate}")
    print(f"Innlogging:  {token_path} {'finnes' if token_path.exists() else 'MANGLER – kjør scripts/spotify_login.py'}")
    if not token_path.exists() or not cfg.spotify.client_id:
        return

    async with httpx.AsyncClient() as http:
        svc = SpotifyService(cfg.spotify, http, token_path)
        try:
            resp = await svc._api("GET", "/me")
            me = resp.json()
            print(f"Konto:       {me.get('display_name')} ({me.get('email', 'e-post skjult')}), "
                  f"produkt: {me.get('product', 'ukjent')}  ← må være 'premium' for avspilling")

            devices = await svc.devices(fresh=True)
            print(f"\nHøyttalere Spotify kjenner til ({len(devices)}):")
            for d in devices:
                print(f"  - {d.name:<24} type={d.type:<10} aktiv={'ja' if d.is_active else 'nei'}  volum={d.volume}")
            if not devices:
                print("  (tom liste)")
                print("\nSpotify ser ingen høyttalere for denne kontoen. Sjekk:")
                print("  1. Spotify er lagt til i Sonos-appen (Innstillinger → Tjenester og stemme) med SAMME konto.")
                print("  2. Rommene vises under «Koble til en enhet» i Spotify-appen på mobilen.")
                print("  3. Spill noe på et Sonos-rom fra Spotify-appen én gang, og kjør dette skriptet igjen.")

            state = await svc.state(fresh=True)
            if state.track:
                print(f"\nSpilles nå:  {state.track.title} – {state.track.artists} på {state.device.name} "
                      f"({'spiller' if state.is_playing else 'pause'})")
            else:
                print("\nSpilles nå:  ingenting")
        except ServiceError as exc:
            print(f"\nFeil fra Spotify: {exc.message}")


if __name__ == "__main__":
    asyncio.run(main())
