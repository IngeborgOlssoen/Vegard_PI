"""Starter backend med `python -m app` (kjøres fra backend/-mappa).

Bruk:
  python -m app            # vanlig kjøring (Pi og PC)
  python -m app --reload   # under utvikling: starter på nytt når filer endres
"""
import sys

import uvicorn

from app.config import load_config


def main() -> None:
    config = load_config()
    reload = "--reload" in sys.argv
    uvicorn.run(
        "app.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=reload,
        # Ved --reload må vi også følge med på frontend-mappa, ellers ser vi ikke
        # endringer der før vi laster siden på nytt (statiske filer caches ikke,
        # så en F5 holder uansett).
        reload_dirs=["app"] if reload else None,
        log_level="info",
    )


if __name__ == "__main__":
    main()
