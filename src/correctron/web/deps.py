"""Helpers shared by every route: repository access, rendering and page state."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..fsutil import tree_fingerprint
from ..repo import NotFound, Repository

EXAM_TABS = {
    "resumen": "Resumen",
    "alumnos": "Alumnos",
    "config": "Configuración",
    "enunciado": "Enunciado",
    "entregas": "Entregas",
    "notas": "Notas",
    "comparar": "Comparar",
    "revisiones": "Revisiones",
}
SUBJECT_TABS = {
    "alumnos": "Alumnos",
    "examenes": "Exámenes y trabajos",
    "datos": "Datos",
    "problemas": "Problemas",
}


def get_repo(request: Request) -> Repository:
    return request.app.state.repo


RepoDep = Annotated[Repository, Depends(get_repo)]


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def breadcrumbs(request: Request, tab: str | None = None) -> list[tuple[str, str]]:
    """(label, url) pairs: Inicio / Asignatura / Examen / Pestaña."""
    repo = get_repo(request)
    crumbs = [("Inicio", "/")]
    subject = request.path_params.get("s")
    exam = request.path_params.get("e")
    if not subject:
        return crumbs
    try:
        meta, _, _ = repo.subject_meta(subject)
        crumbs.append((meta.get("nombre") or subject, f"/a/{subject}"))
    except NotFound:
        return crumbs
    if not exam:
        if tab in SUBJECT_TABS:
            crumbs.append((SUBJECT_TABS[tab], f"/a/{subject}?tab={tab}"))
        return crumbs
    try:
        cfg, _, _ = repo.exam_config(subject, exam)
    except NotFound:
        return crumbs
    crumbs.append((cfg.nombre if cfg else exam, f"/a/{subject}/e/{exam}"))
    if tab in EXAM_TABS:
        crumbs.append((EXAM_TABS[tab], f"/a/{subject}/e/{exam}?tab={tab}"))
    return crumbs


def render_str(request: Request, template: str, **ctx: Any) -> str:
    """Render a template to a string (for fragments that are concatenated)."""
    return _templates(request).get_template(template).render(request=request, **ctx)


def render(
    request: Request,
    template: str,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    **ctx: Any,
) -> HTMLResponse:
    """Render a page or fragment, adding `repo`, the current path and the breadcrumbs."""
    ctx.setdefault("repo", get_repo(request))
    ctx.setdefault("ruta_actual", request.url.path)
    if "migas" not in ctx:
        ctx["migas"] = breadcrumbs(request, ctx.get("tab"))
    return HTMLResponse(
        render_str(request, template, **ctx), status_code=status_code, headers=headers
    )


def rel_dir(request: Request, path: Path) -> str:
    """Path of a directory relative to the data root, as used by /api/huella."""
    return path.relative_to(get_repo(request).root).as_posix()


def estado_oob(
    request: Request,
    watched_dir: Path,
    version_id: str | None = None,
    version: str | None = None,
) -> str:
    """Out-of-band refresh of the page fingerprint (and a file version), after a write (D14)."""
    return render_str(
        request,
        "_estado_oob.html",
        huella=tree_fingerprint(watched_dir),
        version_id=version_id,
        version=version or "",
    )


def aviso_oob(request: Request, nivel: str, mensaje: str) -> str:
    """Out-of-band notice appended to #avisos. `nivel`: ok, info, aviso or error."""
    return render_str(request, "_aviso_oob.html", nivel=nivel, mensaje=mensaje)


def fragment(main: str = "", *oob: str) -> HTMLResponse:
    """A htmx response: the main content, then the out-of-band parts.

    The out-of-band parts go inside a <template>, which htmx unwraps, so they
    parse correctly even when the main content is a table row.
    """
    tail = f"<template>{''.join(oob)}</template>" if oob else ""
    return HTMLResponse(main + tail)
