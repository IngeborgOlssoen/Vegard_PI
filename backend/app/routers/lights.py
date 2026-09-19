"""HTTP-endepunkter for lys. Alle svarer med JSON som frontend viser direkte.

  GET  /api/lights                          alle pærer + scener
  POST /api/lights/all            {cmd}     samme kommando til alle pærer
  POST /api/lights/all/toggle               alle av hvis noen er på, ellers alle på
  POST /api/lights/bulbs/{id}     {cmd}     kommando til én pære
  POST /api/lights/bulbs/{id}/toggle
  GET  /api/lights/scenes
  POST /api/lights/scenes/{id}/activate
  POST /api/lights/scenes/{id}/capture      lagre nåværende lys i scenen
  PUT  /api/lights/scenes/{id}    {scene}   erstatt/lag scene

{cmd} = {"on": true, "brightness": 50, "colortemp": 2700} eller {"rgb": [255,0,0]}
"""
from fastapi import APIRouter, Request

from app.errors import ServiceError
from app.services.lights import LightCommand, LightService
from app.services.scenes import Scene, SceneStore

router = APIRouter(prefix="/lights", tags=["lights"])


def _lights(request: Request) -> LightService:
    return request.app.state.lights


def _scenes(request: Request) -> SceneStore:
    return request.app.state.scenes


def _dump(states) -> list[dict]:
    return [s.model_dump() for s in states]


@router.get("")
async def get_lights(request: Request) -> dict:
    return {
        "bulbs": _dump(_lights(request).states()),
        "scenes": [s.model_dump(exclude_none=True) for s in _scenes(request).list()],
    }


@router.post("/all")
async def set_all(cmd: LightCommand, request: Request) -> dict:
    if cmd.is_empty():
        raise ServiceError("Kommandoen er tom", code="empty_command", status=400)
    return {"bulbs": _dump(await _lights(request).set_all(cmd))}


@router.post("/all/toggle")
async def toggle_all(request: Request) -> dict:
    return {"bulbs": _dump(await _lights(request).toggle_all())}


@router.post("/bulbs/{bulb_id}")
async def set_bulb(bulb_id: str, cmd: LightCommand, request: Request) -> dict:
    if cmd.is_empty():
        raise ServiceError("Kommandoen er tom", code="empty_command", status=400)
    return (await _lights(request).set_bulb(bulb_id, cmd)).model_dump()


@router.post("/bulbs/{bulb_id}/toggle")
async def toggle_bulb(bulb_id: str, request: Request) -> dict:
    return (await _lights(request).toggle_bulb(bulb_id)).model_dump()


@router.get("/scenes")
async def list_scenes(request: Request) -> dict:
    return {"scenes": [s.model_dump(exclude_none=True) for s in _scenes(request).list()]}


@router.post("/scenes/{scene_id}/activate")
async def activate_scene(scene_id: str, request: Request) -> dict:
    return {"bulbs": _dump(await _lights(request).activate_scene(scene_id))}


@router.post("/scenes/{scene_id}/capture")
async def capture_scene(scene_id: str, request: Request) -> dict:
    return _lights(request).capture_scene(scene_id).model_dump(exclude_none=True)


@router.put("/scenes/{scene_id}")
async def put_scene(scene_id: str, scene: Scene, request: Request) -> dict:
    if scene.id != scene_id:
        raise ServiceError("Scene-id i URL og innhold er forskjellige", code="scene_id_mismatch", status=400)
    return _scenes(request).upsert(scene).model_dump(exclude_none=True)
