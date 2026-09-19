"""HTTP-endepunkter for musikk (Spotify).

  GET  /api/spotify                    hva som spilles, høyttalere og spillelister
  POST /api/spotify/play     {context_uri?, device_id?}   start spilleliste / fortsett
  POST /api/spotify/pause
  POST /api/spotify/next
  POST /api/spotify/previous
  POST /api/spotify/volume   {percent, device_id?}
  POST /api/spotify/transfer {device_id}                  bytt høyttaler
  POST /api/spotify/shuffle  {state}
Alle POST-ene svarer med samme innhold som GET, hentet like etter kommandoen.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/spotify", tags=["spotify"])


class PlayBody(BaseModel):
    context_uri: Optional[str] = None
    device_id: Optional[str] = None


class VolumeBody(BaseModel):
    percent: int = Field(ge=0, le=100)
    device_id: Optional[str] = None


class TransferBody(BaseModel):
    device_id: str


class ShuffleBody(BaseModel):
    state: bool


def _svc(request: Request):
    return request.app.state.spotify


async def _after(request: Request) -> dict:
    # Spotify (og Sonos) trenger et lite øyeblikk før ny tilstand kan leses
    await asyncio.sleep(0.4)
    svc = _svc(request)
    await svc.state(fresh=True)
    return (await svc.overview()).model_dump()


@router.get("")
async def overview(request: Request) -> dict:
    return (await _svc(request).overview()).model_dump()


@router.post("/play")
async def play(body: PlayBody, request: Request) -> dict:
    await _svc(request).play(body.context_uri, body.device_id)
    return await _after(request)


@router.post("/pause")
async def pause(request: Request) -> dict:
    await _svc(request).pause()
    return await _after(request)


@router.post("/next")
async def next_track(request: Request) -> dict:
    await _svc(request).next()
    return await _after(request)


@router.post("/previous")
async def previous_track(request: Request) -> dict:
    await _svc(request).previous()
    return await _after(request)


@router.post("/volume")
async def volume(body: VolumeBody, request: Request) -> dict:
    await _svc(request).set_volume(body.percent, body.device_id)
    return await _after(request)


@router.post("/transfer")
async def transfer(body: TransferBody, request: Request) -> dict:
    await _svc(request).transfer(body.device_id)
    return await _after(request)


@router.post("/shuffle")
async def shuffle(body: ShuffleBody, request: Request) -> dict:
    await _svc(request).shuffle(body.state)
    return await _after(request)
