#!/usr/bin/env python3
"""Sjekker om en WiZ-pære svarer på en bestemt IP-adresse, uten søk.

Søket i discover_bulbs.py bruker broadcast, som ofte stopper i nettverks-
extendere og mesh-noder. Selve styringen går direkte til pærens IP og
virker som regel likevel. Finn IP-en i WiZ-appen (pæra → innstillinger →
enhetsinformasjon) og sjekk den her:

    python scripts/check_bulb.py 10.0.0.42

Svarer pæra, får du en ferdig config-blokk å lime inn.
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
    from pywizlight import wizlight
    from pywizlight.exceptions import WizLightConnectionError, WizLightTimeOutError
except ImportError as exc:
    _need_venv(exc.name or "pywizlight")


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    ip = sys.argv[1]
    light = wizlight(ip)
    print(f"Spør pæra på {ip} …")
    try:
        result = await asyncio.wait_for(light.updateState(), 8)
        parser = result[0] if isinstance(result, list) else result
        mac = await asyncio.wait_for(light.getMac(), 8)
        try:
            bt = await asyncio.wait_for(light.get_bulbtype(), 8)
            kind = bt.name or "ukjent type"
        except Exception:
            kind = "ukjent type"
        state = "på" if parser and parser.get_state() else "av"
        print(f"\nPæra svarer! Type: {kind}, MAC: {mac}, tilstand: {state}\n")
        print("Legg dette inn under lights.bulbs i config/config.yaml:")
        print("    - id: nytt_navn")
        print("      name: Nytt navn")
        print(f"      ip: {ip}")
        print(f"      mac: {mac}")
        print("\nTips: gi pæra fast IP i ruteren (DHCP-reservasjon), så adressen ikke endrer seg.")
    except (asyncio.TimeoutError, WizLightTimeOutError, WizLightConnectionError, OSError) as exc:
        print(f"\nIngen svar fra {ip} ({type(exc).__name__}).")
        print("  - Stemmer IP-en? Se WiZ-appen → pæra → innstillinger → enhetsinformasjon.")
        print("  - Er pæra skrudd på med bryteren, og er den grønn/online i WiZ-appen?")
        print("  - Har pæra en adresse i samme nett som denne maskinen (f.eks. begge 10.0.0.x)?")
        print("    Hvis ikke, står extenderen trolig i ruter-modus. Sett den i bro-/AP-modus,")
        print("    eller koble pæra til hovednettet.")
        sys.exit(1)
    finally:
        await light.async_close()


if __name__ == "__main__":
    asyncio.run(main())
