"""File serving, change detection, uploads and deletion of uploaded files."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from ..fsutil import safe_resolve, tree_fingerprint
from ..repo import AREA_RE, BadRequest, NotFound
from .deps import RepoDep, is_htmx, render_str

router = APIRouter()

INLINE_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
TEXT_SUFFIXES = {".md", ".csv", ".txt"}

FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<rect width='32' height='32' rx='7' fill='#0172ad'/>"
    "<path d='M8 17l5 5 11-12' stroke='white' stroke-width='4'"
    " fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>"
)


@router.get("/favicon.ico")
def favicon() -> Response:
    """The same check mark as the inline icon, for browsers that still ask for it."""
    return Response(FAVICON_SVG, media_type="image/svg+xml")


@router.get("/archivo/{ruta:path}")
def serve_file(repo: RepoDep, ruta: str) -> Response:
    """Serve a file of the data root (D19): PDFs, images and text inline, the rest as download."""
    path = safe_resolve(repo.root, ruta)
    if not path.is_file():
        raise NotFound(f"No existe el archivo «{ruta}».")
    headers = {"X-Content-Type-Options": "nosniff"}
    suffix = path.suffix.lower()
    filename = quote(path.name)
    if suffix in INLINE_TYPES:
        headers["Content-Disposition"] = f"inline; filename*=utf-8''{filename}"
        return FileResponse(path, media_type=INLINE_TYPES[suffix], headers=headers)
    if suffix in TEXT_SUFFIXES:
        headers["Content-Disposition"] = f"inline; filename*=utf-8''{filename}"
        return FileResponse(path, media_type="text/plain; charset=utf-8", headers=headers)
    headers["Content-Disposition"] = f"attachment; filename*=utf-8''{filename}"
    return FileResponse(path, media_type="application/octet-stream", headers=headers)


@router.get("/api/huella")
def fingerprint(
    repo: RepoDep,
    request: Request,
    ruta: str = "",
    huella: str = "",
) -> Response:
    """204 while the watched folder is unchanged; the reload banner otherwise (D14)."""
    folder = safe_resolve(repo.root, ruta)
    if tree_fingerprint(folder) == huella:
        return Response(status_code=204)
    html = render_str(
        request,
        "_banner.html",
        id="sondeo",
        nivel="aviso",
        mensaje="Hay cambios en los archivos hechos fuera de la web.",
        recargar=True,
    )
    return HTMLResponse(html)


def _tab_url(s: str, e: str, area: str, archivo: str = "", ok: str = "") -> str:
    """URL of the tab that shows `area` (enunciado or one part of a submission)."""
    if area == "enunciado":
        params = {"tab": "enunciado"}
    else:
        _, alumno, parte = area.split("/")
        params = {"tab": "entregas", "alumno": alumno, "parte": parte}
    if archivo:
        params["archivo"] = archivo
    if ok:
        params["ok"] = ok
    return f"/a/{s}/e/{e}?{urlencode(params)}"


@router.post("/a/{s}/e/{e}/subir")
async def upload(
    repo: RepoDep,
    s: str,
    e: str,
    destino: Annotated[str, Form()] = "",
    archivos: Annotated[list[UploadFile] | None, File()] = None,
) -> RedirectResponse:
    if not AREA_RE.match(destino):
        raise BadRequest(f"Destino no válido: «{destino}».")
    repo.exam_dir(s, e)
    saved = []
    for upload_file in archivos or []:
        if not upload_file.filename:
            continue
        data = await upload_file.read()
        saved.append(repo.save_upload(s, e, destino, upload_file.filename, data))
    ok = f"subidos-{len(saved)}" if saved else ""
    return RedirectResponse(_tab_url(s, e, destino, saved[0] if saved else "", ok), 303)


@router.post("/a/{s}/e/{e}/borrar-archivo")
def delete_file(
    repo: RepoDep,
    request: Request,
    s: str,
    e: str,
    ruta: Annotated[str, Form()] = "",
) -> Response:
    """Move an uploaded file to the trash and go back to its tab."""
    repo.trash_file(s, e, ruta)
    exam_dir = repo.exam_dir(s, e).resolve()
    area = safe_resolve(repo.root, ruta).parent.relative_to(exam_dir).as_posix()
    url = _tab_url(s, e, area, ok="borrado")
    if is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, 303)
