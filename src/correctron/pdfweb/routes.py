"""Routes of the PDF tools web: home list, PDF file, page thumbnails, split and anonymize pages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from ..fsutil import safe_resolve
from ..pdftools import (
    PdfError,
    anonymize,
    anonymize_folder,
    export_sections,
    folder_pdfs,
    is_pdf_name,
    list_pdfs,
    load_boxes,
    load_sections,
    page_count,
    render_page_jpeg,
    save_boxes,
    save_sections,
    validate_boxes,
    validate_sections,
)

router = APIRouter()


def resolve_pdf(root: Path, rel: str) -> Path:
    """The PDF at `rel` in `root`: PathOutsideData if it leaves the root, PdfError if absent."""
    target = safe_resolve(root, rel)
    if not is_pdf_name(target.name) or not target.is_file():
        raise PdfError(f"No existe el PDF «{rel}».")
    return target


def _group_by_folder(request: Request) -> list[dict]:
    root: Path = request.app.state.root
    groups: dict[str, list[dict]] = {}
    for path in list_pdfs(root):
        rel = path.relative_to(root)
        folder = rel.parent.as_posix() if rel.parent.as_posix() != "." else ""
        try:
            pages: int | None = page_count(path)
        except PdfError:
            pages = None
        groups.setdefault(folder, []).append(
            {"ruta": rel.as_posix(), "nombre": rel.name, "paginas": pages}
        )
    return [{"carpeta": folder, "pdfs": items} for folder, items in groups.items()]


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request,
        "index.html",
        {"raiz": request.app.state.root, "carpetas": _group_by_folder(request)},
    )


@router.get("/archivo/{ruta:path}")
def archivo(ruta: str, request: Request) -> FileResponse:
    target = safe_resolve(request.app.state.root, ruta)
    if not is_pdf_name(target.name) or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(
        target,
        media_type="application/pdf",
        filename=target.name,
        content_disposition_type="inline",
    )


@router.get("/pagina")
def pagina(request: Request, pdf: str, n: int, ancho: int = 220) -> Response:
    target = resolve_pdf(request.app.state.root, pdf)
    data = render_page_jpeg(target, n, ancho)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


# --- Dividir ---------------------------------------------------------------------


def _relative(root: Path, target: Path) -> str:
    return target.relative_to(root).as_posix()


@router.get("/dividir", response_class=HTMLResponse)
def dividir(request: Request, pdf: str) -> HTMLResponse:
    root: Path = request.app.state.root
    target = resolve_pdf(root, pdf)
    paginas = page_count(target)
    data, version = load_sections(target)
    clean = validate_sections(data, paginas)
    estado: dict[str, Any] = {
        "pdf": _relative(root, target),
        "paginas": paginas,
        "secciones": clean["secciones"],
        "girar": clean["girar"],
        "version": version,
    }
    return request.app.state.templates.TemplateResponse(
        request,
        "dividir.html",
        {"nombre": target.name, "ruta": estado["pdf"], "paginas": paginas, "estado": estado},
    )


async def _json_object(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError as exc:
        raise PdfError("La petición no es un JSON válido.") from exc
    if not isinstance(body, dict):
        raise PdfError("La petición no es un JSON válido.")
    return body


@router.put("/api/secciones")
async def guardar_secciones(request: Request, pdf: str) -> dict[str, str]:
    root: Path = request.app.state.root
    body = await _json_object(request)
    version = body.get("version")
    if not isinstance(version, str):
        raise PdfError("Falta la versión del archivo de secciones.")
    data = {"secciones": body.get("secciones"), "girar": body.get("girar")}

    def save() -> str:
        return save_sections(resolve_pdf(root, pdf), data, version)

    return {"version": await run_in_threadpool(save)}


@router.post("/api/secciones/exportar")
def exportar_secciones(request: Request, pdf: str) -> dict[str, list[str]]:
    root: Path = request.app.state.root
    archivos = export_sections(root, resolve_pdf(root, pdf))
    return {"archivos": [_relative(root, archivo) for archivo in archivos]}


# --- Anonimizar ------------------------------------------------------------------


def _pdfs_en_carpeta(pdf: Path) -> int:
    """How many PDFs `anonymize_folder` will touch: the `*.pdf` directly in the folder."""
    return len(folder_pdfs(pdf.parent))


@router.get("/anonimizar", response_class=HTMLResponse)
def anonimizar(request: Request, pdf: str) -> HTMLResponse:
    root: Path = request.app.state.root
    target = resolve_pdf(root, pdf)
    paginas = page_count(target)
    data, version = load_boxes(target)
    estado: dict[str, Any] = {
        "pdf": _relative(root, target),
        "paginas": paginas,
        "recuadros": validate_boxes(data)["recuadros"],
        "version": version,
    }
    return request.app.state.templates.TemplateResponse(
        request,
        "anonimizar.html",
        {
            "nombre": target.name,
            "ruta": estado["pdf"],
            "paginas": paginas,
            "en_carpeta": _pdfs_en_carpeta(target),
            "estado": estado,
        },
    )


@router.put("/api/recuadros")
async def guardar_recuadros(request: Request, pdf: str) -> dict[str, str]:
    root: Path = request.app.state.root
    body = await _json_object(request)
    version = body.get("version")
    if not isinstance(version, str):
        raise PdfError("Falta la versión del archivo de recuadros.")
    data = {"recuadros": body.get("recuadros")}

    def save() -> str:
        return save_boxes(resolve_pdf(root, pdf), data, version)

    return {"version": await run_in_threadpool(save)}


@router.post("/api/anonimizar")
def anonimizar_pdf(request: Request, pdf: str, todos: int = 0) -> dict[str, Any]:
    root: Path = request.app.state.root
    target = resolve_pdf(root, pdf)
    if todos not in (0, 1):
        raise PdfError("El parámetro «todos» debe ser 0 o 1.")
    if todos:
        salidas, avisos = anonymize_folder(root, target)
    else:
        data, _ = load_boxes(target)
        salida, avisos = anonymize(root, target, validate_boxes(data)["recuadros"])
        salidas = [salida]
    return {"archivos": [_relative(root, salida) for salida in salidas], "avisos": avisos}
