"""Grades: grid per grader and final, feedback, comparison, building final.csv, revisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..csvtable import Table, read_table
from ..effective import (
    copy_to_final,
    grade_before,
    list_revisions,
    merge_cells,
    new_revision,
    save_revision_row,
)
from ..fsutil import file_version
from ..grades import FINAL, GradeResult, GradeSheet, compute, student_label, validate_cell
from ..models import ExamConfig, RosterEntry
from ..numbers import parse_number
from ..repo import BadRequest, NotFound, Repository
from ..roster import Roster, parse_presentado
from .deps import RepoDep, aviso_oob, estado_oob, fragment, render_str

router = APIRouter()


def _config(repo: Repository, s: str, e: str) -> ExamConfig:
    cfg, _, _ = repo.exam_config(s, e)
    if cfg is None:
        raise BadRequest("config.json tiene errores; corrígelo para continuar.")
    return cfg


def _feedback_ids(exam_dir: Path, name: str) -> set[str]:
    folder = exam_dir / "notas" / name
    if not folder.is_dir():
        return set()
    return {p.stem for p in folder.glob("*.md") if p.is_file()}


# --- grades grid (T16) ---------------------------------------------------------


def _row_view(
    cfg: ExamConfig,
    entry: RosterEntry,
    cells: dict[str, str] | None,
    *,
    errors: dict[str, str] | None = None,
    has_feedback: bool = False,
) -> dict[str, Any]:
    """Everything `_fila_notas.html` needs for one roster entry."""
    cells = dict(cells or {})
    result = compute(cfg, cells)
    invalid = {k: v for k, v in result.cell_errors.items() if k != "total"}
    if cfg.effective_mode() == "manual" and "total" in result.cell_errors:
        invalid["total"] = result.cell_errors["total"]
    invalid.update(errors or {})
    return {
        "entry": entry,
        "p": parse_presentado(entry.presentado),
        "cells": cells,
        "result": result,
        "invalid": invalid,
        "fb": has_feedback,
    }


def _sheet_rows(
    cfg: ExamConfig, roster: Roster, sheet: GradeSheet, feedback: set[str]
) -> list[dict[str, Any]]:
    return [
        _row_view(cfg, entry, sheet.row(entry.id), has_feedback=entry.id in feedback)
        for entry in roster.entries
    ]


def notas_context(
    repo: Repository, s: str, e: str, cfg: ExamConfig | None, q: dict[str, str]
) -> dict[str, Any]:
    assert cfg is not None
    exam_dir = repo.exam_dir(s, e)
    graders = repo.graders(s, e)
    final_exists = (exam_dir / "notas" / "final.csv").is_file()
    name = q.get("corrector") or ("final" if final_exists else (graders[0] if graders else ""))
    ctx: dict[str, Any] = {
        "correctores": graders,
        "corrector": name,
        "hay_revisiones": bool(list_revisions(exam_dir)),
    }
    if not name:
        return ctx
    sheet = repo.sheet(s, e, name)
    roster = repo.roster(s, e)
    roster_ids = {entry.id for entry in roster.entries}
    ctx.update(
        hoja=sheet,
        hoja_rel=f"{s}/{e}/notas/{name}.csv",
        solo_lectura=bool(sheet.table.malformed),
        filas=_sheet_rows(cfg, roster, sheet, _feedback_ids(exam_dir, name)),
        fuera=[row for row in sheet.table.rows if row.get("id", "") not in roster_ids],
        columnas_extra=[
            c
            for c in sheet.table.columns
            if c not in {"id", "alumno", *cfg.leaf_ids(), "total", "comentario", "origen"}
        ],
    )
    return ctx


def _grid_ctx(s: str, e: str, cfg: ExamConfig, name: str) -> dict[str, Any]:
    return {"s": s, "e": e, "cfg": cfg, "corrector": name, "decimales": cfg.decimales}


@router.post("/a/{s}/e/{e}/correctores")
def create_grader(
    repo: RepoDep, s: str, e: str, nombre: Annotated[str, Form()] = ""
) -> RedirectResponse:
    name = repo.create_grader(s, e, nombre)
    return RedirectResponse(f"/a/{s}/e/{e}?tab=notas&corrector={name}", status_code=303)


@router.post("/a/{s}/e/{e}/notas/{name}/{id}", response_class=HTMLResponse)
async def save_row(request: Request, repo: RepoDep, s: str, e: str, name: str, id: str):
    """Save one grid row (D26): out-of-band computed cells, or the row with its errors."""
    cfg = _config(repo, s, e)
    form = await request.form()
    editable = [*cfg.leaf_ids(), "comentario"]
    if cfg.effective_mode() == "manual":
        editable.append("total")
    raw = {col: str(form[col]) for col in editable if col in form}
    version = str(form.get("version", ""))
    new_version, errors = repo.save_grade_row(s, e, name, id, raw, version)
    sheet = repo.sheet(s, e, name)
    roster = repo.roster(s, e)
    entry = next(en for en in roster.entries if en.id == id)
    has_fb = id in _feedback_ids(repo.exam_dir(s, e), name)
    if errors:
        cells = dict(sheet.row(id) or {})
        cells.update(raw)
        row = render_str(
            request,
            "_fila_notas.html",
            **_grid_ctx(s, e, cfg, name),
            **_row_view(cfg, entry, cells, errors=errors, has_feedback=has_fb),
        )
        return HTMLResponse(row, headers={"HX-Retarget": f"#fila-{id}", "HX-Reswap": "outerHTML"})
    view = _row_view(cfg, entry, sheet.row(id), has_feedback=has_fb)
    oob = render_str(request, "_notas_oob.html", **_grid_ctx(s, e, cfg, name), **view)
    return fragment("", oob, estado_oob(request, repo.exam_dir(s, e), "version-hoja", new_version))


@router.get("/a/{s}/e/{e}/notas/{name}/{id}/feedback", response_class=HTMLResponse)
def feedback_form(request: Request, repo: RepoDep, s: str, e: str, name: str, id: str):
    texto, version = repo.feedback(s, e, name, id)
    entry = next((en for en in repo.roster(s, e).entries if en.id == id), None)
    return HTMLResponse(
        render_str(
            request,
            "_feedback.html",
            s=s,
            e=e,
            corrector=name,
            id=id,
            alumno=student_label(entry.apellidos, entry.nombre) if entry else id,
            texto=texto,
            version=version,
        )
    )


@router.post("/a/{s}/e/{e}/notas/{name}/{id}/feedback", response_class=HTMLResponse)
def save_feedback(
    request: Request,
    repo: RepoDep,
    s: str,
    e: str,
    name: str,
    id: str,
    texto: Annotated[str, Form()] = "",
    version: Annotated[str, Form()] = "",
):
    repo.save_feedback(s, e, name, id, texto, version)
    exam_dir = repo.exam_dir(s, e)
    has_fb = id in _feedback_ids(exam_dir, name)
    boton = render_str(
        request, "_boton_fb.html", s=s, e=e, corrector=name, id=id, lleno=has_fb, oob=True
    )
    mensaje = "Comentario largo guardado." if has_fb else "Comentario largo borrado."
    response = fragment("", boton, estado_oob(request, exam_dir), aviso_oob(request, "ok", mensaje))
    response.headers["HX-Trigger"] = "cerrar-feedback"
    return response


# --- comparison (T17) ------------------------------------------------------------


def _number_key(raw: str) -> object:
    try:
        return parse_number(raw)
    except ValueError:
        return ("texto", raw.strip())


@dataclass
class CompareRow:
    entry: RosterEntry
    p: str | None
    graders: dict[str, tuple[dict[str, str] | None, GradeResult | None]]
    final_row: dict[str, str] | None
    final_result: GradeResult | None
    delta: Decimal | None
    strong: bool
    discrepant_leaves: set[str] = field(default_factory=set)
    feedback: dict[str, bool] = field(default_factory=dict)

    @property
    def any_discrepancy(self) -> bool:
        return bool(self.discrepant_leaves) or self.strong


def _compare_row(
    cfg: ExamConfig,
    entry: RosterEntry,
    sheets: dict[str, GradeSheet],
    final: GradeSheet,
    feedback: dict[str, set[str]],
) -> CompareRow:
    per: dict[str, tuple[dict[str, str] | None, GradeResult | None]] = {}
    for name, sheet in sheets.items():
        row = sheet.row(entry.id)
        per[name] = (row, compute(cfg, row) if row is not None else None)
    totals = [res.total for _, res in per.values() if res is not None and res.total is not None]
    delta = max(totals) - min(totals) if len(totals) >= 2 else None
    strong = delta is not None and delta >= cfg.nota_maxima * Decimal("0.1")
    discrepant = set()
    for leaf in cfg.leaf_ids():
        values = {
            _number_key(row.get(leaf, ""))
            for row, _ in per.values()
            if row is not None and row.get(leaf, "").strip()
        }
        if len(values) > 1:
            discrepant.add(leaf)
    final_row = final.row(entry.id)
    return CompareRow(
        entry=entry,
        p=parse_presentado(entry.presentado),
        graders=per,
        final_row=final_row,
        final_result=compute(cfg, final_row) if final_row is not None else None,
        delta=delta,
        strong=strong,
        discrepant_leaves=discrepant,
        feedback={name: entry.id in ids for name, ids in feedback.items()},
    )


def _compare_data(repo: Repository, s: str, e: str):
    exam_dir = repo.exam_dir(s, e)
    graders = repo.graders(s, e)
    sheets = {g: repo.sheet(s, e, g) for g in graders}
    final = repo.sheet(s, e, FINAL)
    feedback = {name: _feedback_ids(exam_dir, name) for name in [*graders, FINAL]}
    return graders, sheets, final, feedback


def comparar_context(
    repo: Repository, s: str, e: str, cfg: ExamConfig | None, q: dict[str, str]
) -> dict[str, Any]:
    assert cfg is not None
    graders, sheets, final, feedback = _compare_data(repo, s, e)
    roster = repo.roster(s, e)
    rows = [_compare_row(cfg, entry, sheets, final, feedback) for entry in roster.entries]
    filtro = q.get("filtro", "")
    shown = [r for r in rows if r.any_discrepancy] if filtro == "discrepancias" else rows
    return {
        "correctores": graders,
        "filas": shown,
        "n_total": len(rows),
        "n_discrepancias": sum(1 for r in rows if r.any_discrepancy),
        "filtro": filtro,
    }


@router.post("/a/{s}/e/{e}/final/copiar")
def bulk_copy(
    repo: RepoDep, s: str, e: str, corrector: Annotated[str, Form()] = ""
) -> RedirectResponse:
    """Copy a grader's rows to final for present students without a final row."""
    cfg = _config(repo, s, e)
    if corrector not in repo.graders(s, e):
        raise NotFound(f"No existe el corrector «{corrector}».")
    roster = repo.roster(s, e)
    final = repo.sheet(s, e, FINAL)
    ids = [
        entry.id
        for entry in roster.entries
        if parse_presentado(entry.presentado) != "no" and final.row(entry.id) is None
    ]
    n = copy_to_final(repo.exam_dir(s, e), cfg, roster, corrector, ids)
    return RedirectResponse(f"/a/{s}/e/{e}?tab=comparar&ok=copiadas-{n}", status_code=303)


@router.post("/a/{s}/e/{e}/final/{id}/usar", response_class=HTMLResponse)
def use_grader(
    request: Request,
    repo: RepoDep,
    s: str,
    e: str,
    id: str,
    corrector: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Copy one grader's row (and feedback) to final (D23) and re-render the row."""
    cfg = _config(repo, s, e)
    if corrector not in repo.graders(s, e):
        raise NotFound(f"No existe el corrector «{corrector}».")
    roster = repo.roster(s, e)
    entry = next((en for en in roster.entries if en.id == id), None)
    if entry is None:
        raise NotFound(f"«{id}» no está en la lista del examen.")
    exam_dir = repo.exam_dir(s, e)
    if copy_to_final(exam_dir, cfg, roster, corrector, [id]) == 0:
        raise BadRequest(f"{corrector} no tiene nota para «{id}».")
    graders, sheets, final, feedback = _compare_data(repo, s, e)
    row = render_str(
        request,
        "_fila_comparar.html",
        s=s,
        e=e,
        cfg=cfg,
        decimales=cfg.decimales,
        correctores=graders,
        f=_compare_row(cfg, entry, sheets, final, feedback),
    )
    label = student_label(entry.apellidos, entry.nombre)
    return fragment(
        row,
        estado_oob(request, exam_dir),
        aviso_oob(request, "ok", f"Nota final de {label}: copiada de {corrector}."),
    )


# --- revisions (T18) --------------------------------------------------------------


def _revision_path(repo: Repository, s: str, e: str, rev: str) -> Path:
    for path in list_revisions(repo.exam_dir(s, e)):
        if path.name == rev:
            return path
    raise NotFound(f"No existe la revisión «{rev}».")


def _after_revision(
    cfg: ExamConfig, before: dict[str, str], table: Table, rev: str, student_id: str
) -> dict[str, str]:
    """`before` with this revision's row for the student applied."""
    cells, _ = merge_cells(cfg, before, [(rev, table)], student_id)
    return cells


def revisiones_context(
    repo: Repository,
    s: str,
    e: str,
    cfg: ExamConfig | None,
    q: dict[str, str],
    *,
    form_valores: dict[str, str] | None = None,
    form_errores: dict[str, str] | None = None,
) -> dict[str, Any]:
    assert cfg is not None
    exam_dir = repo.exam_dir(s, e)
    revs = [p.name for p in reversed(list_revisions(exam_dir))]
    rev = q.get("rev") or (revs[0] if revs else "")
    ctx: dict[str, Any] = {"revisiones": revs, "rev": rev}
    if not rev:
        return ctx
    path = _revision_path(repo, s, e, rev)
    table = read_table(path)
    roster = repo.roster(s, e)
    names = {en.id: student_label(en.apellidos, en.nombre) for en in roster.entries}
    leaf_ids = cfg.leaf_ids()
    filas = []
    for row in table.rows:
        sid = row.get("id", "")
        before = grade_before(exam_dir, cfg, sid, path)
        after = _after_revision(cfg, before, table, rev, sid)
        filas.append(
            {
                "id": sid,
                "alumno": names.get(sid) or row.get("alumno") or sid,
                "en_lista": sid in names,
                "cambios": [
                    (leaf, before.get(leaf, ""), after.get(leaf, ""))
                    for leaf in leaf_ids
                    if row.get(leaf, "").strip()
                ],
                "total_antes": before.get("total", ""),
                "total_despues": after.get("total", ""),
                "motivo": row.get("motivo", ""),
            }
        )
    alumno = q.get("alumno", "")
    candidates = [
        en for en in roster.entries if parse_presentado(en.presentado) != "no" or en.id == alumno
    ]
    ctx.update(
        filas=filas,
        rev_rel=f"{s}/{e}/revisiones/{rev}",
        rev_version=file_version(path),
        candidatos=candidates,
        alumno=alumno,
    )
    if alumno:
        before = grade_before(exam_dir, cfg, alumno, path)
        after = _after_revision(cfg, before, table, rev, alumno)
        existing = next((r for r in table.rows if r.get("id", "") == alumno), None)
        valores = {key: after.get(key, "") for key in [*leaf_ids, "total"]}
        valores["motivo"] = existing.get("motivo", "") if existing else ""
        valores.update(form_valores or {})
        ctx.update(
            antes=before,
            valores=valores,
            errores=form_errores or {},
            alumno_nombre=names.get(alumno, alumno),
            editando=existing is not None,
        )
    return ctx


@router.post("/a/{s}/e/{e}/revisiones")
def create_revision(repo: RepoDep, s: str, e: str) -> RedirectResponse:
    path = new_revision(repo.exam_dir(s, e), date.today())
    return RedirectResponse(f"/a/{s}/e/{e}?tab=revisiones&rev={path.name}", status_code=303)


@router.post("/a/{s}/e/{e}/revisiones/{rev}/{id}")
async def save_revision(request: Request, repo: RepoDep, s: str, e: str, rev: str, id: str):
    """Validate the revised cells and write the student's delta row."""
    from .routes_exam import exam_page  # routes_exam imports this module

    cfg = _config(repo, s, e)
    path = _revision_path(repo, s, e, rev)
    roster = repo.roster(s, e)
    if not any(en.id == id for en in roster.entries):
        raise NotFound(f"«{id}» no está en la lista del examen.")
    form = await request.form()
    columns = cfg.leaf_ids()
    if cfg.effective_mode() == "manual":
        columns = [*columns, "total"]
    submitted = {col: str(form.get(col, "")) for col in columns}
    motivo = str(form.get("motivo", "")).strip()
    version = str(form.get("version", ""))
    cells: dict[str, str] = {}
    errors: dict[str, str] = {}
    for col, raw in submitted.items():
        value, error = validate_cell(cfg, col, raw)
        if error:
            errors[col] = error
        else:
            cells[col] = value
    if not motivo:
        errors["motivo"] = "Escribe el motivo de la revisión."
    if errors:
        q = {"rev": rev, "alumno": id}
        return exam_page(
            request,
            repo,
            s,
            e,
            "revisiones",
            **revisiones_context(
                repo,
                s,
                e,
                cfg,
                q,
                form_valores={**submitted, "motivo": motivo},
                form_errores=errors,
            ),
        )
    save_revision_row(repo.exam_dir(s, e), cfg, roster, path, id, cells, motivo, version)
    return RedirectResponse(f"/a/{s}/e/{e}?tab=revisiones&rev={rev}&ok=1", status_code=303)
