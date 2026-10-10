"""FastAPI application factory."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..numbers import format_number, parse_number, round_grade
from ..repo import BadRequest, CsvMalformed, NotFound, PathOutsideData, Repository, VersionConflict
from ..roster import parse_presentado
from . import (
    routes_exam,
    routes_files,
    routes_grades,
    routes_home,
    routes_subject,
)
from .deps import EXAM_TABS, is_htmx, render, render_str

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


def nota(value: Decimal | None, decimales: int = 2) -> str:
    """A grade for display: rounded, no trailing zeros, decimal comma; None gives "—"."""
    if value is None:
        return "—"
    return format_number(round_grade(value, decimales)).replace(".", ",")


def celda(raw: str | None) -> str:
    """A raw CSV cell for display: valid numbers with a decimal comma, anything else as is."""
    if raw is None:
        return ""
    try:
        value = parse_number(raw)
    except ValueError:
        return raw
    return "" if value is None else format_number(value).replace(".", ",")


def tamano(size: int) -> str:
    """A file size for display (1,2 MB, 34 KB, 512 B)."""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")
    if size >= 1024:
        return f"{round(size / 1024)} KB"
    return f"{size} B"


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    env = templates.env
    env.filters["nota"] = nota
    env.filters["celda"] = celda
    env.filters["tamano"] = tamano
    env.globals["EXAM_TABS"] = EXAM_TABS
    env.globals["parse_presentado"] = parse_presentado
    env.trim_blocks = True
    env.lstrip_blocks = True
    return templates


_CONFLICT_MESSAGE = (
    "El archivo ha cambiado fuera de esta página desde que la abriste "
    "(otra pestaña, un editor o un LLM). No se ha guardado nada: recarga para ver "
    "la versión actual."
)


def _error_response(request: Request, status: int, mensaje: str) -> HTMLResponse:
    """A short Spanish message: a banner fragment for htmx, a full page otherwise."""
    if is_htmx(request):
        html = render_str(request, "_banner.html", nivel="error", mensaje=mensaje)
        return HTMLResponse(html, status_code=status)
    return render(
        request,
        "error.html",
        status_code=status,
        nivel="error",
        mensaje=mensaje,
        codigo=status,
        recargar=status == 409,
        volver=request.headers.get("referer", ""),
    )


def _register_handlers(app: FastAPI) -> None:
    async def version_conflict(request: Request, exc: Exception) -> HTMLResponse:
        return _error_response(request, 409, _CONFLICT_MESSAGE)

    async def csv_malformed(request: Request, exc: Exception) -> HTMLResponse:
        assert isinstance(exc, CsvMalformed)
        root = request.app.state.repo.root
        try:
            name = Path(exc.path).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            name = Path(exc.path).name
        lines = ", ".join(str(n) for n in exc.lines)
        mensaje = (
            f"«{name}» tiene filas con más celdas que la cabecera (líneas {lines}). "
            "Corrígelo a mano; hasta entonces la web no lo modifica."
        )
        return _error_response(request, 409, mensaje)

    async def not_found(request: Request, exc: Exception) -> HTMLResponse:
        return _error_response(request, 404, str(exc) or "No encontrado.")

    async def outside_data(request: Request, exc: Exception) -> HTMLResponse:
        return _error_response(request, 404, "Ruta no válida: está fuera de la carpeta de datos.")

    async def bad_request(request: Request, exc: Exception) -> HTMLResponse:
        return _error_response(request, 400, str(exc) or "Petición no válida.")

    async def http_error(request: Request, exc: Exception) -> HTMLResponse:
        assert isinstance(exc, StarletteHTTPException)
        mensajes = {404: "Esta página no existe.", 405: "Método no permitido."}
        return _error_response(
            request, exc.status_code, mensajes.get(exc.status_code, str(exc.detail))
        )

    app.add_exception_handler(VersionConflict, version_conflict)
    app.add_exception_handler(CsvMalformed, csv_malformed)
    app.add_exception_handler(NotFound, not_found)
    app.add_exception_handler(PathOutsideData, outside_data)
    app.add_exception_handler(BadRequest, bad_request)
    app.add_exception_handler(StarletteHTTPException, http_error)


def create_app(data_dir: Path) -> FastAPI:
    app = FastAPI(title="Correctron", docs_url=None, redoc_url=None, openapi_url=None)
    repo = Repository(Path(data_dir))
    repo.ensure_root()
    app.state.repo = repo
    app.state.templates = make_templates()
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    _register_handlers(app)
    app.include_router(routes_files.router)
    app.include_router(routes_home.router)
    app.include_router(routes_subject.router)
    app.include_router(routes_exam.router)
    app.include_router(routes_grades.router)
    return app
