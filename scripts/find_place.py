#!/usr/bin/env python3
"""Finner koordinater (lat/lon) for et stedsnavn via Kartverkets stedsnavnsøk.

Bruk:
    python scripts/find_place.py "Lillestrøm"
    python scripts/find_place.py "Grünerløkka"

Lim lat og lon inn i config.yaml under weather.
"""
import json
import sys
import urllib.parse
import urllib.request

URL = "https://ws.geonorge.no/stedsnavn/v1/navn"


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    text = " ".join(sys.argv[1:])
    params = urllib.parse.urlencode({"sok": text, "fuzzy": "true", "utkoordsys": 4258, "treffPerSide": 15})
    with urllib.request.urlopen(f"{URL}?{params}", timeout=15) as resp:
        hits = json.load(resp).get("navn", [])
    if not hits:
        print(f"Fant ingen steder som ligner på «{text}».")
        return

    print(f"Steder som ligner på «{text}»:\n")
    for hit in hits:
        point = hit.get("representasjonspunkt") or {}
        lat, lon = point.get("nord"), point.get("øst")
        if lat is None or lon is None:
            continue
        kommuner = ", ".join(k.get("kommunenavn", "") for k in hit.get("kommuner") or [])
        kind = hit.get("navneobjekttype", "")
        print(f"  {hit.get('skrivemåte'):<28} {kind:<18} {kommuner:<20} lat: {lat:.4f}  lon: {lon:.4f}")

    print("\nSett weather.lat og weather.lon i config/config.yaml.")


if __name__ == "__main__":
    main()
