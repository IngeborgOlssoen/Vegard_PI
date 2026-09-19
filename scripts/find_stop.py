#!/usr/bin/env python3
"""Finner NSR-id for en holdeplass via Enturs stedssøk.

Bruk:
    python scripts/find_stop.py "Jernbanetorget"
    python scripts/find_stop.py "Majorstuen" --quays     # vis også plattformer

Lim id-en (NSR:StopPlace:xxxxx) inn i config.yaml under bus.stop_place_id.
"""
import json
import sys
import urllib.parse
import urllib.request
from typing import Optional

GEOCODER = "https://api.entur.io/geocoder/v1/autocomplete"
GRAPHQL = "https://api.entur.io/journey-planner/v3/graphql"
CLIENT = "privat-hjemmepanel-oppsett"


def http_json(url: str, data: Optional[dict] = None) -> dict:
    req = urllib.request.Request(url, headers={"ET-Client-Name": CLIENT, "Content-Type": "application/json"})
    body = json.dumps(data).encode() if data else None
    with urllib.request.urlopen(req, data=body, timeout=15) as resp:
        return json.load(resp)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    show_quays = "--quays" in sys.argv
    text = " ".join(args)

    params = urllib.parse.urlencode({"text": text, "layers": "venue", "size": 10, "lang": "no"})
    features = http_json(f"{GEOCODER}?{params}").get("features", [])
    if not features:
        print(f"Fant ingen holdeplasser som ligner på «{text}».")
        return

    print(f"Holdeplasser som ligner på «{text}»:\n")
    for f in features:
        p = f["properties"]
        where = ", ".join(x for x in (p.get("locality"), p.get("county")) if x)
        kinds = ", ".join(p.get("category") or [])
        print(f"  {p['id']:<24} {p['name']} ({where}) [{kinds}]")
        if show_quays:
            q = {"query": "query($id:String!){stopPlace(id:$id){quays{id publicCode description}}}",
                 "variables": {"id": p["id"]}}
            place = (http_json(GRAPHQL, q).get("data") or {}).get("stopPlace") or {}
            for quay in place.get("quays") or []:
                print(f"      {quay['id']:<20} plattform {quay.get('publicCode') or '?'} {quay.get('description') or ''}")

    print("\nSett bus.stop_place_id i config/config.yaml til id-en som passer.")


if __name__ == "__main__":
    main()
