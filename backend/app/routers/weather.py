"""GET /api/weather – vær nå, neste timer og neste dager for stedet i config.yaml."""
from fastapi import APIRouter, Request

router = APIRouter(prefix="/weather", tags=["weather"])


@router.get("")
async def get_weather(request: Request) -> dict:
    return (await request.app.state.weather.get()).model_dump()
