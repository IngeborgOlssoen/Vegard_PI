"""Felles feilhåndtering.

Målet er at ingen feil fra en ekstern tjeneste (pærer, Entur, MET) skal
krasje backend. I stedet kaster tjenestene `ServiceError` med en norsk
melding, og frontend viser meldingen i det aktuelle kortet.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ServiceError(Exception):
    """Feil fra en ekstern tjeneste. `message` vises direkte på skjermen."""

    def __init__(self, message: str, code: str = "service_error", status: int = 503):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def install_error_handlers(app: FastAPI) -> None:
    """Registrerer handlere som gjør feil om til JSON på formen
    {"error": {"code": "...", "message": "..."}}."""

    @app.exception_handler(ServiceError)
    async def _service_error(_: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Siste skanse: uventede feil skal heller ikke krasje – vis en generell melding.
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": f"Uventet feil i backend: {type(exc).__name__}: {exc}",
                }
            },
        )
