#!/usr/bin/env python3
"""Sjekker Sonos-høyttalerne slik panelet ser dem, og kan prøve å legge en
Spotify-spilleliste i køen for å se hvilken Spotify-variant systemet bruker.

Bruk (venv aktivert, fra repo-roten):
    python scripts/sonos_check.py                          # rom, kontoer, hva som spilles
    python scripts/sonos_check.py --play spotify:playlist:37i9dQZF1DXcBWIGoYBM5M
    python scripts/sonos_check.py --ip 10.0.0.20           # hvis søk ikke finner høyttalerne
    python scripts/sonos_check.py --next                   # prøv «neste» i rommet som spiller, vis feilen
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _need_venv(module: str) -> None:
    print(f"Fant ikke pakken «{module}». Aktiver først det virtuelle miljøet, så prøv igjen:\n")
    print("    source .venv/bin/activate        (Windows: .venv\\Scripts\\activate)")
    print(f"    python {sys.argv[0]}\n")
    sys.exit(1)


try:
    from soco import SoCo, discover  # noqa: E402
    from app.services.sonos import SPOTIFY_SERVICE_TYPES, enqueue_spotify, playback_source, spotify_accounts  # noqa: E402
except ImportError as exc:
    _need_venv(exc.name or "soco")


def arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and len(sys.argv) > sys.argv.index(name) + 1 else None


def main() -> None:
    ip = arg("--ip")
    if ip:
        zones = set(SoCo(ip).all_zones)
    else:
        print("Søker etter Sonos-høyttalere (5 s) …")
        found = discover(timeout=5) or set()
        zones = set()
        for z in found:
            zones |= set(z.all_zones)
    zones = [z for z in zones if z.is_visible and not z.is_bridge]
    if not zones:
        print("Fant ingen høyttalere. Prøv med --ip <adresse til én høyttaler> (Sonos-appen → Innstillinger → System → Om systemet).")
        sys.exit(1)

    print(f"\nRom ({len(zones)}):")
    for z in sorted(zones, key=lambda z: z.player_name):
        coord = z.group.coordinator if z.group else z
        state = coord.get_current_transport_info().get("current_transport_state")
        print(f"  - {z.player_name:<20} {z.ip_address:<15} volum {z.volume:>3}   gruppe: {coord.player_name} ({state})")

    first = sorted(zones, key=lambda z: z.player_name)[0]
    print("\nSpotify-kontoer i Sonos-systemet (type, kontonummer):")
    accounts = spotify_accounts(first)
    for service, sn in accounts:
        print(f"  - type {service}, konto {sn}")
    if not accounts:
        print("  (fant ingen – panelet prøver standardvariantene", ", ".join(SPOTIFY_SERVICE_TYPES), ")")

    seen = set()
    playing_coord = None
    for z in sorted(zones, key=lambda z: z.player_name):
        coord = z.group.coordinator if z.group else z
        if coord.uid in seen:
            continue
        seen.add(coord.uid)
        state = coord.get_current_transport_info().get("current_transport_state")
        info = coord.get_current_track_info()
        uri = info.get("uri") or ""
        print(f"\nGruppe «{coord.player_name}»: {state}, kilde: {playback_source(uri)}, "
              f"kø: {coord.queue_size} spor, spor nr. {info.get('playlist_position') or '-'}")
        if info.get("title"):
            print(f"  {info['title']} – {info.get('artist')}  ({info.get('position')} / {info.get('duration')})")
        print(f"  uri: {uri or '-'}")
        if state == "PLAYING" and playing_coord is None:
            playing_coord = coord

    if "--next" in sys.argv:
        coord = playing_coord or first
        print(f"\nPrøver «neste» i «{coord.player_name}» …")
        try:
            coord.next()
            time.sleep(1.5)
            info = coord.get_current_track_info()
            print(f"  OK. Spiller nå: {info.get('title')} – {info.get('artist')}")
        except Exception as exc:
            print(f"  Feil: {type(exc).__name__}: {exc}")
            info = coord.get_current_track_info()
            if info.get("playlist_position") and playback_source(info.get("uri")) == "queue":
                pos = int(info["playlist_position"])
                print(f"  Prøver hopp via køposisjon ({pos + 1}) …")
                try:
                    coord.play_from_queue(pos)
                    time.sleep(1.5)
                    info = coord.get_current_track_info()
                    print(f"  OK. Spiller nå: {info.get('title')} – {info.get('artist')}")
                except Exception as exc2:
                    print(f"  Feil: {type(exc2).__name__}: {exc2}")

    uri = arg("--play")
    if uri:
        room = arg("--room")
        zone = next((z for z in zones if room and z.player_name.lower() == room.lower()), first)
        coord = zone.group.coordinator if zone.group else zone
        print(f"\nPrøver å legge {uri} i køen til {coord.player_name} …")
        coord.clear_queue()
        added = enqueue_spotify(coord, uri)
        print(f"  Sanger lagt i køen: {added}")
        if added:
            coord.play_from_queue(0)
            time.sleep(2)
            info = coord.get_current_track_info()
            print(f"  Spiller nå: {info.get('title')} – {info.get('artist')} ({info.get('duration')})")
        else:
            print("  Ingen sanger kom inn. Er Spotify lagt til i Sonos-appen (Innstillinger → Tjenester og stemme)?")


if __name__ == "__main__":
    main()
