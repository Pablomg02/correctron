"""Subject student lists and exam rosters (alumnos.csv)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .csvtable import CsvMalformed, Table, read_table, write_table
from .fsutil import file_version
from .models import Issue, RosterEntry, Student

STUDENT_COLUMNS = ["id", "apellidos", "nombre", "email", "observaciones"]
ROSTER_COLUMNS = ["id", "apellidos", "nombre", "presentado", "observaciones"]
REQUIRED_COLUMNS = ["id", "apellidos", "nombre"]
STUDENT_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_SI = {"si", "sí", "s", "x", "1", "true", "yes", "presentado"}
_NO = {"no", "n", "0", "false", "np", "no presentado"}


def parse_presentado(raw: str) -> Literal["si", "no", ""] | None:
    value = raw.strip().lower()
    if not value:
        return ""
    if value in _SI:
        return "si"
    if value in _NO:
        return "no"
    return None


@dataclass
class StudentList:
    students: list[Student] = field(default_factory=list)
    table: Table = field(default_factory=Table)
    version: str = ""
    issues: list[Issue] = field(default_factory=list)


@dataclass
class Roster:
    entries: list[RosterEntry] = field(default_factory=list)
    table: Table = field(default_factory=Table)
    version: str = ""
    issues: list[Issue] = field(default_factory=list)


def _common_issues(table: Table, file: str, exists: bool) -> list[Issue]:
    issues: list[Issue] = []
    if not exists:
        return issues
    for col in REQUIRED_COLUMNS:
        if col not in table.columns:
            issues.append(Issue("error", file, f"Falta la columna obligatoria «{col}»."))
    if table.malformed:
        lines = ", ".join(str(n) for n in table.malformed)
        issues.append(
            Issue("error", file, f"Filas con más celdas que la cabecera: líneas {lines}.")
        )
    seen: set[str] = set()
    reported: set[str] = set()
    blank = 0
    for row in table.rows:
        sid = row.get("id", "")
        if "id" not in table.columns:
            continue
        if not sid:
            blank += 1
        elif sid in seen and sid not in reported:
            issues.append(Issue("error", file, f"El id «{sid}» está repetido."))
            reported.add(sid)
        seen.add(sid)
    if blank:
        issues.append(Issue("error", file, f"Hay {blank} fila(s) con el id en blanco."))
    return issues


def load_students(path: Path, file: str) -> StudentList:
    table = read_table(path)
    version = file_version(path)
    issues = _common_issues(table, file, bool(version))
    students = []
    for row in table.rows:
        extra = {k: v for k, v in row.items() if k not in STUDENT_COLUMNS}
        students.append(
            Student(
                id=row.get("id", ""),
                apellidos=row.get("apellidos", ""),
                nombre=row.get("nombre", ""),
                email=row.get("email", ""),
                observaciones=row.get("observaciones", ""),
                extra=extra,
            )
        )
        sid = row.get("id", "")
        if sid and not STUDENT_ID_RE.match(sid):
            issues.append(
                Issue("aviso", file, f"El id «{sid}» no sigue el patrón apellidos-nombre.")
            )
    return StudentList(students=students, table=table, version=version, issues=issues)


def load_roster(path: Path, file: str) -> Roster:
    table = read_table(path)
    version = file_version(path)
    issues = _common_issues(table, file, bool(version))
    entries = []
    for row in table.rows:
        extra = {k: v for k, v in row.items() if k not in ROSTER_COLUMNS}
        entry = RosterEntry(
            id=row.get("id", ""),
            apellidos=row.get("apellidos", ""),
            nombre=row.get("nombre", ""),
            presentado=row.get("presentado", ""),
            observaciones=row.get("observaciones", ""),
            extra=extra,
        )
        entries.append(entry)
        if parse_presentado(entry.presentado) is None:
            issues.append(
                Issue(
                    "error",
                    file,
                    f"Valor de «presentado» no válido para «{entry.id}»: «{entry.presentado}».",
                )
            )
    return Roster(entries=entries, table=table, version=version, issues=issues)


def _columns(canonical: list[str], table: Table, extras: list[dict[str, str]]) -> list[str]:
    columns = list(canonical)
    for col in table.columns:
        if col not in columns:
            columns.append(col)
    for extra in extras:
        for col in extra:
            if col not in columns:
                columns.append(col)
    return columns


def _write(path: Path, source: Table, columns: list[str], rows: list[dict[str, str]]) -> None:
    if source.malformed:
        raise CsvMalformed(path, source.malformed)
    rows = sorted(rows, key=lambda r: r.get("id", ""))
    table = Table(
        columns=columns,
        rows=rows,
        delimiter=source.delimiter,
        bom=source.bom,
        encoding=source.encoding,
    )
    write_table(path, table)


def save_students(path: Path, sl: StudentList) -> None:
    columns = _columns(STUDENT_COLUMNS, sl.table, [s.extra for s in sl.students])
    rows = [
        {
            **{k: v.strip() for k, v in s.extra.items()},
            "id": s.id.strip(),
            "apellidos": s.apellidos.strip(),
            "nombre": s.nombre.strip(),
            "email": s.email.strip(),
            "observaciones": s.observaciones.strip(),
        }
        for s in sl.students
    ]
    _write(path, sl.table, columns, rows)


def save_roster(path: Path, r: Roster) -> None:
    columns = _columns(ROSTER_COLUMNS, r.table, [e.extra for e in r.entries])
    rows = [
        {
            **{k: v.strip() for k, v in e.extra.items()},
            "id": e.id.strip(),
            "apellidos": e.apellidos.strip(),
            "nombre": e.nombre.strip(),
            "presentado": e.presentado.strip(),
            "observaciones": e.observaciones.strip(),
        }
        for e in r.entries
    ]
    _write(path, r.table, columns, rows)


def parse_import_text(text: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Parse `Apellidos, Nombre[, email]` or tab-separated lines (D24)."""
    triples: list[tuple[str, str, str]] = []
    errors: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        sep = "\t" if "\t" in line else ","
        parts = [part.strip() for part in line.split(sep)]
        while len(parts) > 2 and not parts[-1]:
            parts.pop()
        if len(parts) < 2:
            errors.append(
                f"Línea {number}: se esperaba «Apellidos, Nombre[, email]» "
                f"y se leyó «{line.strip()}»."
            )
            continue
        if len(parts) > 3:
            errors.append(f"Línea {number}: demasiados campos ({len(parts)}); máximo 3.")
            continue
        apellidos, nombre = parts[0], parts[1]
        email = parts[2] if len(parts) == 3 else ""
        if not apellidos or not nombre:
            errors.append(f"Línea {number}: faltan los apellidos o el nombre.")
            continue
        triples.append((apellidos, nombre, email))
    return triples, errors
