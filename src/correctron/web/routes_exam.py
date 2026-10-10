"""Exam page: tab shell, summary, roster, configuration, statement and submissions."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..config_io import exam_config_to_dict
from ..effective import effective_grades, list_revisions
from ..fsutil import tree_fingerprint
from ..models import ExamConfig, Issue
from ..repo import BadRequest, Repository
from ..roster import parse_presentado
from ..validation import validate_exam
from . import routes_grades
from .deps import (
    EXAM_TABS,
    RepoDep,
    aviso_oob,
    estado_oob,
    fragment,
    render,
    render_str,
)

router = APIRouter()

# Tabs that still work when config.json cannot be used.
TABS_WITHOUT_CONFIG = {"resumen", "alumnos", "config", "enunciado", "entregas"}

PARTES = {"original": "Original", "corregido": "Corregido"}


def _query(request: Request) -> dict[str, str]:
    return dict(request.query_params)


# --- tab contexts ------------------------------------------------------------


def _resumen(repo: Repository, s: str, e: str, cfg: ExamConfig | None) -> dict[str, Any]:
    exam_dir = repo.exam_dir(s, e)
    roster = repo.roster(s, e)
    states = [parse_presentado(entry.presentado) for entry in roster.entries]
    sheets = [(g, len(repo.sheet(s, e, g).table.rows)) for g in repo.graders(s, e)]
    return {
        "roster": roster,
        "cuentas": {
            "roster": len(states),
            "si": states.count("si"),
            "no": states.count("no"),
            "sin": states.count(""),
            "mal": states.count(None),
        },
        "hojas": sheets,
        "filas_final": len(repo.sheet(s, e, "final").table.rows),
        "revisiones": [p.name for p in list_revisions(exam_dir)],
        "vigentes": effective_grades(exam_dir, cfg, roster) if cfg else [],
        "problemas": validate_exam(repo.root, s, e),
    }


def _roster_panel_ctx(repo: Repository, s: str, e: str) -> dict[str, Any]:
    only_subject, only_exam = repo.roster_diff(s, e)
    return {
        "roster": repo.roster(s, e),
        "solo_asignatura": only_subject,
        "solo_examen": only_exam,
    }


def _config_ctx(
    repo: Repository,
    s: str,
    e: str,
    cfg: ExamConfig | None,
    cfg_issues: list[Issue],
    *,
    errores: list[Issue] | None = None,
    enviado: str | None = None,
    editor: str = "",
) -> dict[str, Any]:
    path = repo.exam_dir(s, e) / "config.json"
    texto = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    datos = exam_config_to_dict(cfg) if cfg else None
    if enviado is not None:
        texto = enviado
        try:
            parsed = json.loads(enviado)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and datos is not None:
            datos = parsed
    orphans = repo.orphan_columns(s, e)
    return {
        "config_datos": datos,
        "config_texto": texto,
        "config_avisos": [i for i in cfg_issues if i.level == "aviso"],
        "config_errores_actuales": [i for i in cfg_issues if i.level == "error"],
        "errores": errores or [],
        "huerfanas": orphans,
        "editor": editor,
    }


def _area_files(repo: Repository, s: str, e: str, area: str, archivo: str) -> dict[str, Any]:
    files = repo.list_files(s, e, area)
    selected = next((f for f in files if f.rel_path == archivo), None)
    if selected is None:
        selected = next((f for f in files if f.is_pdf), None)
    return {"area": area, "archivos": files, "seleccionado": selected}


def _enunciado(repo: Repository, s: str, e: str, q: dict[str, str]) -> dict[str, Any]:
    return _area_files(repo, s, e, "enunciado", q.get("archivo", ""))


def _entregas(repo: Repository, s: str, e: str, q: dict[str, str]) -> dict[str, Any]:
    roster = repo.roster(s, e)
    counts = repo.submission_counts(s, e)
    ctx: dict[str, Any] = {
        "roster": roster,
        "conteos": counts,
        "huerfanas": repo.orphan_submission_dirs(s, e),
        "alumno": None,
    }
    alumno = q.get("alumno", "")
    if not alumno:
        return ctx
    parte = q.get("parte", "original")
    if parte not in PARTES:
        parte = "original"
    ids = [entry.id for entry in roster.entries]
    entry = next((en for en in roster.entries if en.id == alumno), None)
    pos = ids.index(alumno) if alumno in ids else -1
    ctx.update(
        alumno=alumno,
        entrada=entry,
        parte=parte,
        anterior=ids[pos - 1] if pos > 0 else None,
        siguiente=ids[pos + 1] if 0 <= pos < len(ids) - 1 else None,
        partes={p: counts.get(alumno, (0, 0))[i] for i, p in enumerate(PARTES)},
        **_area_files(repo, s, e, f"entregas/{alumno}/{parte}", q.get("archivo", "")),
    )
    return ctx


_OK_MESSAGES = {
    "1": "Guardado.",
    "borrado": "Archivo movido a la papelera (.papelera/ en la carpeta de datos).",
}


def _initial_notices(q: dict[str, str]) -> list[tuple[str, str]]:
    ok = q.get("ok", "")
    if ok.startswith("subidos-"):
        n = ok.removeprefix("subidos-")
        return [("ok", "1 archivo subido." if n == "1" else f"{n} archivos subidos.")]
    if ok.startswith("copiadas-"):
        n = ok.removeprefix("copiadas-")
        return [("ok", "1 fila copiada a final." if n == "1" else f"{n} filas copiadas a final.")]
    if ok in _OK_MESSAGES:
        return [("ok", _OK_MESSAGES[ok])]
    return []


def exam_page(
    request: Request,
    repo: Repository,
    s: str,
    e: str,
    tab: str,
    *,
    status_code: int = 200,
    **extra: Any,
) -> HTMLResponse:
    """Render the exam page with one tab. `extra` overrides the tab context."""
    exam_dir = repo.exam_dir(s, e)
    cfg, cfg_issues, cfg_version = repo.exam_config(s, e)
    if tab not in EXAM_TABS:
        tab = "resumen"
    q = _query(request)
    ctx: dict[str, Any] = {
        "s": s,
        "e": e,
        "tab": tab,
        "cfg": cfg,
        "cfg_version": cfg_version,
        "nombre_examen": cfg.nombre if cfg else e,
        "bloqueada": cfg is None and tab not in TABS_WITHOUT_CONFIG,
        "huella": tree_fingerprint(exam_dir),
        "ruta_vigilada": f"{s}/{e}",
        "avisos_iniciales": _initial_notices(q),
        "decimales": cfg.decimales if cfg else 2,
    }
    if not ctx["bloqueada"]:
        if tab == "resumen":
            ctx.update(_resumen(repo, s, e, cfg))
        elif tab == "alumnos":
            ctx.update(_roster_panel_ctx(repo, s, e))
        elif tab == "config":
            ctx.update(_config_ctx(repo, s, e, cfg, cfg_issues))
        elif tab == "enunciado":
            ctx.update(_enunciado(repo, s, e, q))
        elif tab == "entregas":
            ctx.update(_entregas(repo, s, e, q))
        elif tab == "notas":
            ctx.update(routes_grades.notas_context(repo, s, e, cfg, q))
        elif tab == "comparar":
            ctx.update(routes_grades.comparar_context(repo, s, e, cfg, q))
        elif tab == "revisiones":
            ctx.update(routes_grades.revisiones_context(repo, s, e, cfg, q))
    ctx.update(extra)
    return render(request, "examen.html", status_code=status_code, **ctx)


@router.get("/a/{s}/e/{e}", response_class=HTMLResponse)
def exam_view(
    repo: RepoDep,
    request: Request,
    s: str,
    e: str,
    tab: str = "resumen",
) -> HTMLResponse:
    return exam_page(request, repo, s, e, tab)


# --- roster ------------------------------------------------------------------


def _roster_panel(request: Request, repo: Repository, s: str, e: str, **extra: Any) -> str:
    return render_str(
        request, "_panel_roster.html", s=s, e=e, **_roster_panel_ctx(repo, s, e), **extra
    )


@router.post("/a/{s}/e/{e}/alumnos/{id}", response_class=HTMLResponse)
def edit_roster_entry(
    repo: RepoDep,
    request: Request,
    s: str,
    e: str,
    id: str,
    presentado: Annotated[str, Form()] = "",
    observaciones: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Inline edit of presentado/observaciones (D26): only out-of-band state comes back."""
    repo.update_roster_entry(s, e, id, presentado, observaciones, version)
    exam_dir = repo.exam_dir(s, e)
    return fragment("", estado_oob(request, exam_dir, "version-lista", repo.roster(s, e).version))


@router.post("/a/{s}/e/{e}/alumnos/{id}/borrar", response_class=HTMLResponse)
def remove_roster_entry(
    repo: RepoDep,
    request: Request,
    s: str,
    e: str,
    id: str,
    version: Annotated[str, Form()] = "",
) -> HTMLResponse:
    repo.remove_from_roster(s, e, id, version)
    return fragment(
        _roster_panel(request, repo, s, e),
        estado_oob(request, repo.exam_dir(s, e)),
        aviso_oob(
            request,
            "ok",
            f"«{id}» se ha quitado de la lista del examen. Sus notas y entregas se conservan.",
        ),
    )


@router.post("/a/{s}/e/{e}/alumnos", response_class=HTMLResponse)
def add_roster_entries(
    repo: RepoDep,
    request: Request,
    s: str,
    e: str,
    ids: Annotated[list[str] | None, Form()] = None,
    todos: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
) -> HTMLResponse:
    ids = ids or []
    if todos:
        ids = [st.id for st in repo.roster_diff(s, e)[0]]
    if not ids:
        raise BadRequest("No has seleccionado ningún alumno.")
    repo.add_to_roster(s, e, ids, version)
    n = len(ids)
    return fragment(
        _roster_panel(request, repo, s, e, resaltar=ids),
        estado_oob(request, repo.exam_dir(s, e)),
        aviso_oob(request, "ok", "1 alumno añadido." if n == 1 else f"{n} alumnos añadidos."),
    )


@router.post("/a/{s}/e/{e}/marcar-presentados", response_class=HTMLResponse)
def mark_present(
    repo: RepoDep,
    request: Request,
    s: str,
    e: str,
    version: Annotated[str, Form()] = "",
) -> HTMLResponse:
    n = repo.mark_present(s, e, version)
    if n == 0:
        mensaje = "No había alumnos sin marcar."
    elif n == 1:
        mensaje = "1 alumno marcado como presentado."
    else:
        mensaje = f"{n} alumnos marcados como presentados."
    return fragment(
        _roster_panel(request, repo, s, e),
        estado_oob(request, repo.exam_dir(s, e)),
        aviso_oob(request, "ok" if n else "info", mensaje),
    )


# --- configuration -------------------------------------------------------------


@router.post("/a/{s}/e/{e}/config", response_class=HTMLResponse)
def save_config(
    repo: RepoDep,
    request: Request,
    s: str,
    e: str,
    config_json: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
    editor: Annotated[str, Form()] = "json",
):
    issues = repo.save_exam_config_json(s, e, config_json, version)
    errors = [i for i in issues if i.level == "error"]
    if not errors:
        return RedirectResponse(f"/a/{s}/e/{e}?tab=config&ok=1", status_code=303)
    cfg, cfg_issues, _ = repo.exam_config(s, e)
    return exam_page(
        request,
        repo,
        s,
        e,
        "config",
        **_config_ctx(
            repo, s, e, cfg, cfg_issues, errores=errors, enviado=config_json, editor=editor
        ),
    )
