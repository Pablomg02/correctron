"""Grade sheets (notas/<corrector>.csv, notas/final.csv) and total computation."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .csvtable import Table, read_table, write_table
from .fsutil import file_version
from .models import ExamConfig, Leaf
from .numbers import format_number, parse_number, round_grade
from .roster import Roster

FINAL = "final"


@dataclass
class GradeResult:
    leaves: dict[str, Decimal | None] = field(default_factory=dict)
    groups: dict[str, Decimal | None] = field(default_factory=dict)
    total: Decimal | None = None
    partial: Decimal | None = None
    complete: bool = False
    cell_errors: dict[str, str] = field(default_factory=dict)


def _check_value(raw: str, maximo: Decimal) -> tuple[Decimal | None, str | None]:
    """Parse a cell and check it lies in [0, maximo]."""
    try:
        value = parse_number(raw)
    except ValueError:
        return None, f"«{raw.strip()}» no es un número."
    if value is None:
        return None, None
    if value < 0 or value > maximo:
        return None, f"Fuera de rango: debe estar entre 0 y {format_number(maximo)}."
    return value, None


def compute(cfg: ExamConfig, cells: dict[str, str]) -> GradeResult:
    """Compute leaves, group subtotals and total (Appendix A §Total computation)."""
    result = GradeResult()
    valid = True
    for leaf in cfg.leaves():
        value, error = _check_value(cells.get(leaf.id, ""), leaf.maximo)
        if error:
            result.cell_errors[leaf.id] = error
            valid = False
        result.leaves[leaf.id] = value

    for crit in cfg.criterios:
        if crit.is_group:
            values = [result.leaves[leaf.id] for leaf in crit.subcriterios]
            result.groups[crit.id] = (
                None if any(v is None for v in values) else sum(values, Decimal(0))
            )

    total_value, total_error = _check_value(cells.get("total", ""), cfg.nota_maxima)
    if total_error:
        result.cell_errors["total"] = total_error

    mode = cfg.effective_mode()
    if mode == "manual":
        result.complete = total_value is not None
        result.total = total_value
        return result

    filled = [v for v in result.leaves.values() if v is not None]
    result.complete = valid and len(filled) == len(result.leaves)
    if not result.complete:
        if mode == "suma" and filled:
            result.partial = round_grade(sum(filled, Decimal(0)), cfg.decimales)
        return result

    if mode == "suma":
        raw_total = sum(filled, Decimal(0))
    else:
        raw_total = _weighted(cfg, result.leaves)
    result.total = round_grade(raw_total, cfg.decimales)
    return result


def _weighted(cfg: ExamConfig, leaves: dict[str, Decimal | None]) -> Decimal:
    weighted = Decimal(0)
    weights = Decimal(0)
    for crit in cfg.criterios:
        crit_leaves: list[Leaf] = crit.leaves()
        got = sum((leaves[leaf.id] or Decimal(0) for leaf in crit_leaves), Decimal(0))
        top = sum((leaf.maximo for leaf in crit_leaves), Decimal(0))
        weighted += crit.peso * got / top
        weights += crit.peso
    return cfg.nota_maxima * weighted / weights


@dataclass
class GradeSheet:
    name: str
    path: Path
    table: Table
    version: str

    def row(self, student_id: str) -> dict[str, str] | None:
        for row in self.table.rows:
            if row.get("id", "") == student_id:
                return row
        return None

    def set_row(self, student_id: str, cells: dict[str, str]) -> None:
        if "id" not in self.table.columns:
            self.table.columns.insert(0, "id")
        row = self.row(student_id)
        if row is None:
            row = {col: "" for col in self.table.columns}
            row["id"] = student_id
            self.table.rows.append(row)
        for col, value in cells.items():
            if col not in self.table.columns:
                self.table.columns.append(col)
            row[col] = value.strip()

    def remove_row(self, student_id: str) -> None:
        self.table.rows = [r for r in self.table.rows if r.get("id", "") != student_id]


def load_sheet(path: Path, name: str) -> GradeSheet:
    return GradeSheet(name=name, path=path, table=read_table(path), version=file_version(path))


def sheet_columns(cfg: ExamConfig, name: str) -> list[str]:
    """Canonical columns of a grade sheet (plus `origen` for final)."""
    columns = ["id", "alumno", *cfg.leaf_ids(), "total", "comentario"]
    if name == FINAL:
        columns.append("origen")
    return columns


def student_label(apellidos: str, nombre: str) -> str:
    return f"{apellidos}, {nombre}"


def save_sheet(sheet: GradeSheet, cfg: ExamConfig, roster: Roster) -> None:
    """Rewrite the sheet canonically (columns, alumno, computed total, order)."""
    columns = sheet_columns(cfg, sheet.name)
    columns += [c for c in sheet.table.columns if c not in columns]
    names = {e.id: student_label(e.apellidos, e.nombre) for e in roster.entries}
    computed = cfg.effective_mode() != "manual"
    rows = []
    for source in sheet.table.rows:
        row = {col: source.get(col, "") for col in columns}
        sid = row["id"]
        if sid in names:
            row["alumno"] = names[sid]
        if computed:
            total = compute(cfg, row).total
            row["total"] = "" if total is None else format_number(total)
        rows.append(row)
    rows.sort(key=lambda r: r["id"])
    table = Table(
        columns=columns,
        rows=rows,
        delimiter=sheet.table.delimiter,
        bom=sheet.table.bom,
        encoding=sheet.table.encoding,
        malformed=list(sheet.table.malformed),
    )
    write_table(sheet.path, table)
    sheet.table = table
    sheet.version = file_version(sheet.path)


def list_graders(exam_dir: Path) -> list[str]:
    notas = exam_dir / "notas"
    if not notas.is_dir():
        return []
    return sorted(
        p.stem
        for p in notas.glob("*.csv")
        if p.is_file() and p.stem != FINAL and not p.name.startswith((".", "_"))
    )


def validate_cell(cfg: ExamConfig, column: str, raw: str) -> tuple[str, str | None]:
    """Canonical value and error message for a value typed in the web."""
    if column == "total":
        maximo: Decimal | None = cfg.nota_maxima
    else:
        leaf = cfg.leaf(column)
        maximo = leaf.maximo if leaf else None
    if maximo is None:
        return raw.strip(), None
    value, error = _check_value(raw, maximo)
    if error:
        return raw.strip(), error
    return ("" if value is None else format_number(value)), None
