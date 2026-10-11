"""FastAPI application factory for the PDF tools web."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..fsutil import PathOutsideData, VersionConflict
from ..pdftools import PdfError
from ..web.app import STATIC_DIR as GRADING_STATIC_DIR
from . import routes

PDFWEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PDFWEB_DIR / "templates"
STATIC_DIR = PDFWEB_DIR / "static"

_CONFLICT_MESSAGE = (
    "El archivo ha cambiado fuera de esta página. No se ha guardado nada: "
    "recarga para ver la versión actual."
)
_OUTSIDE_MESSAGE = "Ruta no válida: está fuera de la carpeta de datos."


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.trim_blocks = True
    templates.env.lstrip_blocks = True
    return templates


def _error_response(request: Request, status: int, mensaje: str) -> HTMLResponse | JSONResponse:
    """JSON `{"error": …}` for the /api/ routes, the error page for the others."""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": mensaje}, status_code=status)
    return request.app.state.templates.TemplateResponse(
        request,
        "error.html",
        {
            "codigo": status,
            "mensaje": mensaje,
            "recargar": status == 409,
            "volver": request.headers.get("referer", ""),
        },
        status_code=status,
    )


def _register_handlers(app: FastAPI) -> None:
    async def pdf_error(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
        return _error_response(request, 400, str(exc) or "Petición no válida.")

    async def version_conflict(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
        return _error_response(request, 409, _CONFLICT_MESSAGE)

    async def outside_data(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
        return _error_response(request, 404, _OUTSIDE_MESSAGE)

    async def http_error(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
        assert isinstance(exc, StarletteHTTPException)
        mensajes = {404: "Esta página no existe.", 405: "Método no permitido."}
        mensaje = mensajes.get(exc.status_code, str(exc.detail))
        return _error_response(request, exc.status_code, mensaje)

    app.add_exception_handler(PdfError, pdf_error)
    app.add_exception_handler(VersionConflict, version_conflict)
    app.add_exception_handler(PathOutsideData, outside_data)
    app.add_exception_handler(StarletteHTTPException, http_error)


def create_app(data_dir: Path) -> FastAPI:
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Correctron PDF", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.root = root
    app.state.templates = make_templates()
    # The grading web's vendored libraries and stylesheet are reused read-only.
    app.mount("/comun", StaticFiles(directory=str(GRADING_STATIC_DIR)), name="comun")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    _register_handlers(app)
    app.include_router(routes.router)
    return app
