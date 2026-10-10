"""Validation engine: every inconsistency of Appendix A §Validation, never raising."""

from __future__ import annotations

import re
from pathlib import Path

from .config_io import load_exam_config, load_subject_meta
from .csvtable import Table, read_table
from .effective import REVISION_RE, list_revisions, merge_cells
from .grades import FINAL, compute, list_graders, sheet_columns
from .models import ExamConfig, Issue
from .numbers import format_number, parse_number
from .roster import load_roster, load_students, parse_presentado

GRADER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _sorted(issues: list[Issue]) -> list[Issue]:
    return sorted(issues, key=lambda i: (i.file, i.level != "error", i.message))


def validate_subject(root: Path, subject: str) -> list[Issue]:
    """Issues of the subject-level files (asignatura.json and alumnos.csv)."""
    folder = root / subject
    _, issues = load_subject_meta(folder / "asignatura.json", subject)
    issues = list(issues)
    issues += load_students(folder / "alumnos.csv", f"{subject}/alumnos.csv").issues
    return _sorted(issues)


def validate_exam(root: Path, subject: str, exam: str) -> list[Issue]:
    """Issues of every file of one exam."""
    rel = f"{subject}/{exam}"
    exam_dir = root / subject / exam
    issues: list[Issue] = []

    cfg, cfg_issues = load_exam_config(exam_dir / "config.json", f"{rel}/config.json")
    issues += cfg_issues

    roster_file = f"{rel}/alumnos.csv"
    roster = load_roster(exam_dir / "alumnos.csv", roster_file)
    issues += roster.issues
    subject_ids = {s.id for s in load_students(root / subject / "alumnos.csv", "").students if s.id}
    for entry in roster.entries:
        if entry.id and entry.id not in subject_ids:
            issues.append(
                Issue(
                    "aviso",
                    roster_file,
                    f"«{entry.id}» está en el examen pero no en la lista de la asignatura.",
                )
            )
    roster_ids = {e.id for e in roster.entries if e.id}
    absent = {e.id for e in roster.entries if parse_presentado(e.presentado) == "no"}

    if cfg is not None:
        issues += _validate_sheets(exam_dir, rel, cfg, roster_ids, absent)

    entregas = exam_dir / "entregas"
    if entregas.is_dir():
        for child in sorted(entregas.iterdir()):
            if child.is_dir() and not child.name.startswith((".", "_")):
                if child.name not in roster_ids:
                    issues.append(
                        Issue(
                            "aviso",
                            f"{rel}/entregas/{child.name}",
                            f"La carpeta de entregas «{child.name}» no está en la lista "
                            "del examen.",
                        )
                    )
    return _sorted(issues)


def _validate_sheets(
    exam_dir: Path, rel: str, cfg: ExamConfig, roster_ids: set[str], absent: set[str]
) -> list[Issue]:
    issues: list[Issue] = []
    graders = list_graders(exam_dir)
    leaf_ids = cfg.leaf_ids()
    computed = cfg.effective_mode() != "manual"

    for name in graders:
        file = f"{rel}/notas/{name}.csv"
        if not GRADER_RE.match(name):
            issues.append(
                Issue(
                    "aviso",
                    file,
                    f"El nombre de corrector «{name}» no es válido "
                    "(minúsculas, cifras, «-» y «_»).",
                )
            )
        table = read_table(exam_dir / "notas" / f"{name}.csv")
        issues += _check_table(table, file, cfg, sheet_columns(cfg, name), roster_ids, absent)
        if computed and "id" in table.columns:
            for row in table.rows:
                issues += _total_mismatch(file, row, compute(cfg, row).total)

    final_path = exam_dir / "notas" / "final.csv"
    final_rows: dict[str, dict[str, str]] = {}
    if final_path.is_file():
        file = f"{rel}/notas/final.csv"
        table = read_table(final_path)
        issues += _check_table(table, file, cfg, sheet_columns(cfg, FINAL), roster_ids, absent)
        if "id" in table.columns:
            for row in table.rows:
                final_rows.setdefault(row["id"], row)
                if computed:
                    issues += _total_mismatch(file, row, compute(cfg, row).total)
                origen = row.get("origen", "")
                if origen != "manual" and origen not in graders:
                    issues.append(
                        Issue(
                            "aviso",
                            file,
                            f"«{row['id']}»: el origen «{origen}» no es «manual» "
                            "ni un corrector existente.",
                        )
                    )

    revision_columns = ["id", "alumno", *leaf_ids, "total", "motivo"]
    applied: list[tuple[str, Table]] = []
    for path in list_revisions(exam_dir):
        file = f"{rel}/revisiones/{path.name}"
        if not REVISION_RE.match(path.name):
            issues.append(
                Issue(
                    "aviso",
                    file,
                    f"El nombre «{path.name}» no sigue el formato NN-AAAA-MM-DD.csv.",
                )
            )
        table = read_table(path)
        applied.append((path.name, table))
        issues += _check_table(table, file, cfg, revision_columns, roster_ids, absent)
        if "id" not in table.columns:
            continue
        for row in table.rows:
            if not row.get("motivo", "").strip():
                issues.append(Issue("aviso", file, f"«{row['id']}»: el motivo está en blanco."))
            if computed:
                merged, _ = merge_cells(cfg, final_rows.get(row["id"]), applied, row["id"])
                issues += _total_mismatch(file, row, compute(cfg, merged).total)
    return issues


def _check_table(
    table: Table,
    file: str,
    cfg: ExamConfig,
    expected: list[str],
    roster_ids: set[str],
    absent: set[str],
) -> list[Issue]:
    issues: list[Issue] = []
    if table.malformed:
        lines = ", ".join(str(n) for n in table.malformed)
        issues.append(
            Issue("error", file, f"Filas con más celdas que la cabecera: líneas {lines}.")
        )
    if "id" not in table.columns:
        issues.append(Issue("error", file, "Falta la columna «id»."))
        return issues
    for col in table.columns:
        if col not in expected:
            issues.append(Issue("aviso", file, f"Columna desconocida «{col}»."))
    for leaf_id in cfg.leaf_ids():
        if leaf_id not in table.columns:
            issues.append(Issue("aviso", file, f"Falta la columna del apartado «{leaf_id}»."))
    value_columns = [*cfg.leaf_ids(), "total"]
    seen: set[str] = set()
    for row in table.rows:
        sid = row["id"]
        if sid in seen:
            issues.append(Issue("error", file, f"El id «{sid}» está repetido."))
        seen.add(sid)
        result = compute(cfg, row)
        for col in value_columns:
            if col in result.cell_errors:
                issues.append(
                    Issue("error", file, f"«{sid}», columna «{col}»: {result.cell_errors[col]}")
                )
        if sid not in roster_ids:
            issues.append(Issue("aviso", file, f"«{sid}» no está en la lista del examen."))
        elif sid in absent and any(row.get(col, "").strip() for col in value_columns):
            issues.append(
                Issue("aviso", file, f"«{sid}» tiene nota pero está marcado como no presentado.")
            )
    return issues


def _total_mismatch(file: str, row: dict[str, str], computed) -> list[Issue]:
    raw = row.get("total", "")
    try:
        value = parse_number(raw)
    except ValueError:
        return []
    if value is None or value == computed:
        return []
    shown = "incompleta" if computed is None else format_number(computed)
    return [
        Issue(
            "aviso",
            file,
            f"«{row.get('id', '')}»: el total del archivo ({raw}) no coincide con el "
            f"calculado ({shown}).",
        )
    ]
