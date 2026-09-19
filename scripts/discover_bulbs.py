#!/usr/bin/env python3
"""Finner WiZ-pærer på hjemmenettet og skriver ut en ferdig config-blokk.

Bruk (fra repo-roten, med .venv aktivert):
    python scripts/discover_bulbs.py
    python scripts/discover_bulbs.py 192.168.1.255   # hvis vanlig søk ikke finner noe

Maskinen du kjører fra må være på samme nett som pærene.
"""
import asyncio
import sys

def _need_venv(module: str) -> None:
    """Skriptene trenger pakkene i .venv – si fra på en forståelig måte hvis den ikke er aktivert."""
    print(f"Fant ikke pakken «{module}». Aktiver først det virtuelle miljøet, så prøv igjen:\n")
    print("    source .venv/bin/activate        (Windows: .venv\\Scripts\\activate)")
    print(f"    python {sys.argv[0]}\n")
    print("Mangler .venv? Se «Kom i gang på PC» i README.")
    sys.exit(1)


try:
    from pywizlight import discovery, wizlight
except ImportError as exc:
    _need_venv(exc.name or "pywizlight")


async def main() -> None:
    broadcast = sys.argv[1] if len(sys.argv) > 1 else "255.255.255.255"
    print(f"Søker etter WiZ-pærer (broadcast {broadcast}) i 5 sekunder …")
    bulbs = await discovery.discover_lights(broadcast_space=broadcast, wait_time=5)
    if not bulbs:
        print("Fant ingen pærer. Prøv med nettets broadcast-adresse, f.eks. 192.168.1.255, "
              "og sjekk at pærene har strøm og er på samme WiFi.")
        return

    print(f"Fant {len(bulbs)} pære(r):\n")
    print("bulbs:")
    for i, found in enumerate(bulbs, start=1):
        light = wizlight(found.ip, mac=found.mac)
        try:
            bt = await asyncio.wait_for(light.get_bulbtype(), 10)
            kind = bt.name or "ukjent type"
            features = "farge" if bt.features.color else ("hvitt, justerbar temperatur" if bt.features.color_tmp else "hvitt")
        except Exception as exc:
            kind, features = "ukjent type", f"kunne ikke lese egenskaper ({exc})"
        finally:
            await light.async_close()
        print(f"  - id: paere_{i}")
        print(f"    name: Pære {i}          # {kind}, {features}")
        print(f"    ip: {found.ip}")
        print(f"    mac: {found.mac}")
    print("\nLim blokken inn under `lights:` i config/config.yaml og gi pærene navn.")
    print("Tips: skru en pære av og på i WiZ-appen for å finne ut hvilken som er hvilken.")


if __name__ == "__main__":
    asyncio.run(main())
