"""Hjemmepanel – backend (FastAPI).

Pakken er delt opp slik:
  config.py     – leser og validerer config/config.yaml
  errors.py     – felles feilhåndtering (feilmeldinger på norsk til skjermen)
  main.py       – setter opp FastAPI-appen, tjenester og statiske filer
  services/     – snakker med pærer, Entur og MET (ingen HTTP-logikk her)
  routers/      – HTTP-endepunktene under /api/...
  buttons.py    – valgfri støtte for fysiske knapper (GPIO) på Pi-en
"""
