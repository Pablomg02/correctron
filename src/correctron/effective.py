"""Final grades, revisions and effective grades."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from .config_io import load_exam_config
from .csvtable import Table, read_table, write_table
from .fsutil import atomic_write_bytes, check_version, file_version
from .grades import FINAL, GradeResult, compute, load_sheet, save_sheet, student_label
from .models import ExamConfig
from .numbers import format_number, parse_number
from .roster import Roster, parse_presentado

REVISION_RE = re.compile(r"^(\d{2})-(\d{4}-\d{2}-\d{2})\.csv$")


def canonical(raw: str) -> str:
    """D23: a valid number as format_number(parse_number(raw)); anything else as is."""
    try:
        value = parse_number(raw)
    except ValueError:
        return raw
    return "" if value is None else format_number(value)


def _same_number(a: str, b: str) -> bool:
    try:
        return parse_number(a) == parse_number(b)
    except ValueError:
        return a.strip() == b.strip()


def list_revisions(exam_dir: Path) -> list[Path]:
    folder = exam_dir / "revisiones"
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.glob("*.csv") if p.is_file() and not p.name.startswith(".")),
        key=lambda p: p.name,
    )


def revision_columns(cfg: ExamConfig) -> list[str]:
    return ["id", "alumno", *cfg.leaf_ids(), "total", "motivo"]


def new_revision(exam_dir: Path, today: date) -> Path:
    """Create revisiones/<NN+1>-<today>.csv with the header only."""
    cfg, _ = load_exam_config(exam_dir / "config.json", "config.json")
    highest = 0
    for path in list_revisions(exam_dir):
        match = REVISION_RE.match(path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    path = exam_dir / "revisiones" / f"{highest + 1:02d}-{today.isoformat()}.csv"
    columns = revision_columns(cfg) if cfg else ["id", "alumno", "total", "motivo"]
    write_table(path, Table(columns=columns))
    return path


def _find_row(table: Table, student_id: str) -> dict[str, str] | None:
    for row in table.rows:
        if row.get("id", "") == student_id:
            return row
    return None


def merge_cells(
    cfg: ExamConfig,
    final_row: dict[str, str] | None,
    revisions: list[tuple[str, Table]],
    student_id: str,
) -> tuple[dict[str, str], list[str]]:
    """Merge the final row with the given revision tables (in order).

    Returns the merged leaf/total/comentario cells and the names of the
    revisions that hold a row for the student.
    """
    keys = [*cfg.leaf_ids(), "total"]
    source = final_row or {}
    cells = {key: canonical(source.get(key, "")) for key in keys}
    cells["comentario"] = source.get("comentario", "")
    touched: list[str] = []
    for name, table in revisions:
        row = _find_row(table, student_id)
        if row is None:
            continue
        touched.append(name)
        for key in keys:
            value = row.get(key, "")
            if value.strip():
                cells[key] = canonical(value)
    if cfg.effective_mode() != "manual":
        total = compute(cfg, cells).total
        cells["total"] = "" if total is None else format_number(total)
    return cells, touched


def revision_tables(exam_dir: Path, before: Path | None) -> list[tuple[str, Table]]:
    tables = []
    for path in list_revisions(exam_dir):
        if before is not None and path.name >= before.name:
            continue
        tables.append((path.name, read_table(path)))
    return tables


def grade_before(
    exam_dir: Path, cfg: ExamConfig, student_id: str, revision: Path | None
) -> dict[str, str]:
    """Final row plus every revision strictly before `revision` (all if None)."""
    final_row = load_sheet(exam_dir / "notas" / "final.csv", FINAL).row(student_id)
    cells, _ = merge_cells(cfg, final_row, revision_tables(exam_dir, revision), student_id)
    return cells


def save_revision_row(
    exam_dir: Path,
    cfg: ExamConfig,
    roster: Roster,
    revision: Path,
    student_id: str,
    cells: dict[str, str],
    motivo: str,
    version: str,
) -> str:
    """Write the student's delta row into `revision`. Returns the new file version."""
    check_version(revision, version)
    before = grade_before(exam_dir, cfg, student_id, revision)
    merged = dict(before)
    row: dict[str, str] = {"id": student_id}
    for leaf_id in cfg.leaf_ids():
        raw = cells.get(leaf_id, "")
        if raw.strip() and not _same_number(raw, before.get(leaf_id, "")):
            row[leaf_id] = canonical(raw.strip())
            merged[leaf_id] = row[leaf_id]
        else:
            row[leaf_id] = ""
    if cfg.effective_mode() == "manual":
        row["total"] = canonical(cells.get("total", "").strip())
    else:
        total = compute(cfg, merged).total
        row["total"] = "" if total is None else format_number(total)
    row["motivo"] = motivo.strip()

    table = read_table(revision)
    columns = revision_columns(cfg)
    columns += [c for c in table.columns if c not in columns]
    existing = _find_row(table, student_id)
    if existing is not None:
        row = {**existing, **row}
        table.rows = [r for r in table.rows if r.get("id", "") != student_id]
    table.rows.append(row)
    names = {e.id: student_label(e.apellidos, e.nombre) for e in roster.entries}
    rows = []
    for source in table.rows:
        out = {col: source.get(col, "") for col in columns}
        if out["id"] in names:
            out["alumno"] = names[out["id"]]
        rows.append(out)
    rows.sort(key=lambda r: r["id"])
    write_table(
        revision,
        Table(
            columns=columns,
            rows=rows,
            delimiter=table.delimiter,
            bom=table.bom,
            encoding=table.encoding,
            malformed=list(table.malformed),
        ),
    )
    return file_version(revision)


def copy_to_final(
    exam_dir: Path, cfg: ExamConfig, roster: Roster, grader: str, student_ids: list[str]
) -> int:
    """D23: copy grader rows (and feedback) into final.csv with origen=<grader>."""
    notas = exam_dir / "notas"
    source = load_sheet(notas / f"{grader}.csv", grader)
    final = load_sheet(notas / "final.csv", FINAL)
    copied = 0
    for sid in student_ids:
        row = source.row(sid)
        if row is None:
            continue
        cells = {key: canonical(row.get(key, "")) for key in [*cfg.leaf_ids(), "total"]}
        cells["comentario"] = row.get("comentario", "")
        cells["origen"] = grader
        final.set_row(sid, cells)
        feedback = notas / grader / f"{sid}.md"
        if feedback.is_file():
            atomic_write_bytes(notas / FINAL / f"{sid}.md", feedback.read_bytes())
        copied += 1
    if copied:
        save_sheet(final, cfg, roster)
    return copied


@dataclass
class EffectiveGrade:
    id: str
    alumno: str
    presentado: Literal["si", "no", ""]
    status: Literal["np", "sin_nota", "incompleta", "ok"]
    cells: dict[str, str] = field(default_factory=dict)
    result: GradeResult | None = None
    revised_in: list[str] = field(default_factory=list)


def effective_grades(exam_dir: Path, cfg: ExamConfig, roster: Roster) -> list[EffectiveGrade]:
    """One effective grade per roster entry, in roster order."""
    final = load_sheet(exam_dir / "notas" / "final.csv", FINAL)
    revisions = revision_tables(exam_dir, None)
    grades = []
    for entry in roster.entries:
        presentado = parse_presentado(entry.presentado) or ""
        final_row = final.row(entry.id)
        cells, touched = merge_cells(cfg, final_row, revisions, entry.id)
        has_grade = final_row is not None or bool(touched)
        result = compute(cfg, cells) if has_grade else None
        if presentado == "no":
            status = "np"
        elif result is None:
            status = "sin_nota"
        elif not result.complete:
            status = "incompleta"
        else:
            status = "ok"
        grades.append(
            EffectiveGrade(
                id=entry.id,
                alumno=student_label(entry.apellidos, entry.nombre),
                presentado=presentado,
                status=status,
                cells=cells if has_grade else {},
                result=result,
                revised_in=touched,
            )
        )
    return grades
