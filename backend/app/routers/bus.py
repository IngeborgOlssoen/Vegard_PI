"""GET /api/bus – neste avganger fra holdeplassen i config.yaml."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/bus", tags=["bus"])


@router.get("")
async def get_departures(request: Request) -> dict:
    return (await request.app.state.bus.get()).model_dump()
