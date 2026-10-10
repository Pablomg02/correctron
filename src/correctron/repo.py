"""Repository façade: the only API the web layer calls.

Every mutation is atomic. Methods that take a `version` compare it with the
current version of the file being modified and raise `VersionConflict` on a
mismatch. Unknown subjects, exams, students or graders raise `NotFound`;
invalid input raises `BadRequest` (D28).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path

from .config_io import (
    RESERVED_COLUMNS,
    default_exam_config,
    load_exam_config,
    load_subject_meta,
    parse_exam_config,
    save_exam_config,
    save_subject_meta,
)
from .csvtable import CsvMalformed, Table, read_table, write_table
from .effective import list_revisions
from .fsutil import (
    PathOutsideData,
    VersionConflict,
    atomic_write_bytes,
    atomic_write_text,
    check_version,
    file_version,
    move_to_trash,
    safe_resolve,
    sanitize_filename,
    unique_path,
)
from .grades import (
    FINAL,
    GradeSheet,
    list_graders,
    load_sheet,
    save_sheet,
    sheet_columns,
    validate_cell,
)
from .models import ExamConfig, Issue, RosterEntry, Student
from .roster import (
    ROSTER_COLUMNS,
    STUDENT_COLUMNS,
    Roster,
    StudentList,
    load_roster,
    load_students,
    parse_import_text,
    parse_presentado,
    save_roster,
    save_students,
)
from .slug import slugify, student_slug

__all__ = [
    "AREA_RE",
    "BadRequest",
    "CsvMalformed",
    "ExamInfo",
    "FileInfo",
    "NotFound",
    "PathOutsideData",
    "Repository",
    "SubjectInfo",
    "VersionConflict",
]

AREA_RE = re.compile(r"^(enunciado|entregas/[a-z0-9][a-z0-9_-]*/(original|corregido))$")
EXAM_FOLDERS = ("enunciado", "entregas", "notas", "revisiones")
_TIPOS = ("examen", "trabajo")


class NotFound(KeyError):
    """Unknown subject, exam, student, grader or file."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


class BadRequest(ValueError):
    """Invalid input. The message is in Spanish and can be shown to the user."""


@dataclass
class SubjectInfo:
    slug: str
    nombre: str
    curso: str
    n_students: int
    n_exams: int


@dataclass
class ExamInfo:
    slug: str
    nombre: str
    tipo: str
    fecha: str
    n_roster: int
    n_presentados: int
    config_ok: bool


@dataclass
class FileInfo:
    name: str
    rel_path: str
    size: int
    is_pdf: bool


def _is_hidden(name: str) -> bool:
    return name.startswith((".", "_"))


def _plain_name(name: str) -> bool:
    """A single, non-hidden path component."""
    return bool(name) and "/" not in name and "\\" not in name and not _is_hidden(name)


def _valid_fecha(fecha: str) -> bool:
    if not fecha:
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
        return False
    try:
        date.fromisoformat(fecha)
    except ValueError:
        return False
    return True


def _unique_folder(parent: Path, base: str) -> str:
    candidate = base
    n = 2
    while (parent / candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _count_files(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))


class Repository:
    def __init__(self, root: Path):
        self.root = Path(root)

    # --- helpers ----------------------------------------------------------

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _subject_dir(self, slug: str) -> Path:
        if not _plain_name(slug) or slug in (".", ".."):
            raise NotFound(f"No existe la asignatura «{slug}».")
        path = self.root / slug
        if not path.is_dir():
            raise NotFound(f"No existe la asignatura «{slug}».")
        return path

    def _exam_slugs(self, subject_dir: Path) -> list[str]:
        return sorted(
            p.name
            for p in subject_dir.iterdir()
            if p.is_dir() and not _is_hidden(p.name) and (p / "config.json").is_file()
        )

    def _require_config(self, slug: str, exam: str) -> ExamConfig:
        cfg, _, _ = self.exam_config(slug, exam)
        if cfg is None:
            raise BadRequest("config.json tiene errores; corrígelo para continuar.")
        return cfg

    # --- root and subjects ------------------------------------------------

    def ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        leeme = self.root / "LEEME.md"
        if not leeme.exists():
            data = resources.files("correctron").joinpath("resources", "LEEME.md").read_bytes()
            atomic_write_bytes(leeme, data)

    def list_subjects(self) -> list[SubjectInfo]:
        if not self.root.is_dir():
            return []
        subjects = []
        for path in sorted(self.root.iterdir(), key=lambda p: p.name):
            if not path.is_dir() or _is_hidden(path.name):
                continue
            meta, _ = load_subject_meta(path / "asignatura.json", path.name)
            students = load_students(path / "alumnos.csv", f"{path.name}/alumnos.csv")
            subjects.append(
                SubjectInfo(
                    slug=path.name,
                    nombre=meta["nombre"],
                    curso=meta["curso"],
                    n_students=len(students.students),
                    n_exams=len(self._exam_slugs(path)),
                )
            )
        return subjects

    def subject_meta(self, slug: str) -> tuple[dict, list[Issue], str]:
        """(meta, issues, version of asignatura.json)."""
        path = self._subject_dir(slug) / "asignatura.json"
        meta, issues = load_subject_meta(path, slug)
        return meta, issues, file_version(path)

    def create_subject(self, nombre: str, curso: str) -> str:
        nombre = nombre.strip()
        if not nombre:
            raise BadRequest("El nombre de la asignatura no puede estar vacío.")
        self.root.mkdir(parents=True, exist_ok=True)
        slug = _unique_folder(self.root, slugify(nombre))
        folder = self.root / slug
        folder.mkdir()
        save_subject_meta(
            folder / "asignatura.json", {"nombre": nombre, "curso": curso.strip(), "codigo": ""}
        )
        write_table(folder / "alumnos.csv", Table(columns=list(STUDENT_COLUMNS)))
        return slug

    def update_subject_meta(
        self, slug: str, nombre: str, curso: str, codigo: str, version: str
    ) -> None:
        path = self._subject_dir(slug) / "asignatura.json"
        check_version(path, version)
        nombre = nombre.strip()
        if not nombre:
            raise BadRequest("El nombre de la asignatura no puede estar vacío.")
        meta, _ = load_subject_meta(path, slug)
        meta.update(nombre=nombre, curso=curso.strip(), codigo=codigo.strip())
        save_subject_meta(path, meta)

    # --- students ---------------------------------------------------------

    def _students_path(self, slug: str) -> Path:
        return self._subject_dir(slug) / "alumnos.csv"

    def students(self, slug: str) -> StudentList:
        return load_students(self._students_path(slug), f"{slug}/alumnos.csv")

    def _load_students_checked(self, slug: str, version: str) -> tuple[Path, StudentList]:
        path = self._students_path(slug)
        check_version(path, version)
        return path, load_students(path, f"{slug}/alumnos.csv")

    @staticmethod
    def _check_names(apellidos: str, nombre: str) -> tuple[str, str]:
        apellidos, nombre = apellidos.strip(), nombre.strip()
        if not apellidos or not nombre:
            raise BadRequest("Los apellidos y el nombre no pueden estar vacíos.")
        return apellidos, nombre

    def add_student(self, slug: str, apellidos: str, nombre: str, email: str, version: str) -> str:
        path, sl = self._load_students_checked(slug, version)
        apellidos, nombre = self._check_names(apellidos, nombre)
        new_id = student_slug(apellidos, nombre, {s.id for s in sl.students})
        sl.students.append(Student(new_id, apellidos, nombre, email.strip()))
        save_students(path, sl)
        return new_id

    def import_students(self, slug: str, text: str, version: str) -> tuple[list[str], list[str]]:
        path, sl = self._load_students_checked(slug, version)
        triples, errors = parse_import_text(text)
        if errors or not triples:
            return [], errors
        taken = {s.id for s in sl.students}
        new_ids = []
        for apellidos, nombre, email in triples:
            new_id = student_slug(apellidos, nombre, taken)
            taken.add(new_id)
            new_ids.append(new_id)
            sl.students.append(Student(new_id, apellidos, nombre, email))
        save_students(path, sl)
        return new_ids, []

    @staticmethod
    def _find_student(sl: StudentList, student_id: str) -> Student:
        for student in sl.students:
            if student.id == student_id:
                return student
        raise NotFound(f"No existe el alumno «{student_id}».")

    def update_student(
        self,
        slug: str,
        id: str,
        apellidos: str,
        nombre: str,
        email: str,
        observaciones: str,
        version: str,
    ) -> None:
        """Update a subject student and propagate the names to every exam roster (D17)."""
        path, sl = self._load_students_checked(slug, version)
        student = self._find_student(sl, id)
        apellidos, nombre = self._check_names(apellidos, nombre)
        subject_dir = self._subject_dir(slug)
        to_update: list[tuple[Path, Roster]] = []
        for exam in self._exam_slugs(subject_dir):
            roster_path = subject_dir / exam / "alumnos.csv"
            roster = load_roster(roster_path, self._rel(roster_path))
            entries = [e for e in roster.entries if e.id == id]
            if not entries or all((e.apellidos, e.nombre) == (apellidos, nombre) for e in entries):
                continue
            if roster.table.malformed:
                raise CsvMalformed(roster_path, roster.table.malformed)
            for entry in entries:
                entry.apellidos, entry.nombre = apellidos, nombre
            to_update.append((roster_path, roster))
        if sl.table.malformed:
            raise CsvMalformed(path, sl.table.malformed)
        student.apellidos, student.nombre = apellidos, nombre
        student.email, student.observaciones = email.strip(), observaciones.strip()
        save_students(path, sl)
        for roster_path, roster in to_update:
            save_roster(roster_path, roster)

    def remove_student(self, slug: str, id: str, version: str) -> list[str]:
        """Remove only the subject row; returns the exams whose roster still has the id."""
        path, sl = self._load_students_checked(slug, version)
        self._find_student(sl, id)
        sl.students = [s for s in sl.students if s.id != id]
        save_students(path, sl)
        return self.exams_containing(slug, id)

    def exams_containing(self, slug: str, id: str) -> list[str]:
        subject_dir = self._subject_dir(slug)
        result = []
        for exam in self._exam_slugs(subject_dir):
            roster_path = subject_dir / exam / "alumnos.csv"
            if any(e.id == id for e in load_roster(roster_path, "").entries):
                result.append(exam)
        return result

    # --- exams ------------------------------------------------------------

    def list_exams(self, slug: str) -> list[ExamInfo]:
        subject_dir = self._subject_dir(slug)
        exams = []
        for exam in self._exam_slugs(subject_dir):
            exam_dir = subject_dir / exam
            cfg, _ = load_exam_config(exam_dir / "config.json", f"{slug}/{exam}/config.json")
            roster = load_roster(exam_dir / "alumnos.csv", "")
            exams.append(
                ExamInfo(
                    slug=exam,
                    nombre=cfg.nombre if cfg else exam,
                    tipo=cfg.tipo if cfg else "",
                    fecha=cfg.fecha if cfg else "",
                    n_roster=len(roster.entries),
                    n_presentados=sum(
                        1 for e in roster.entries if parse_presentado(e.presentado) == "si"
                    ),
                    config_ok=cfg is not None,
                )
            )
        exams.sort(key=lambda e: (e.fecha, e.slug))
        return exams

    def create_exam(
        self, slug: str, nombre: str, tipo: str, fecha: str, copiar_alumnos: bool
    ) -> str:
        """Create an exam folder with the D25 defaults. Returns the exam slug."""
        subject_dir = self._subject_dir(slug)
        nombre, fecha = nombre.strip(), fecha.strip()
        if not nombre:
            raise BadRequest("El nombre del examen no puede estar vacío.")
        if tipo not in _TIPOS:
            raise BadRequest("El tipo debe ser «examen» o «trabajo».")
        if not _valid_fecha(fecha):
            raise BadRequest("La fecha debe tener la forma AAAA-MM-DD.")
        exam = _unique_folder(subject_dir, slugify(nombre))
        exam_dir = subject_dir / exam
        exam_dir.mkdir()
        save_exam_config(exam_dir / "config.json", default_exam_config(nombre, tipo, fecha))
        roster = Roster(table=Table(columns=list(ROSTER_COLUMNS)))
        if copiar_alumnos:
            for s in self.students(slug).students:
                if s.id:
                    roster.entries.append(RosterEntry(s.id, s.apellidos, s.nombre, ""))
        save_roster(exam_dir / "alumnos.csv", roster)
        for folder in EXAM_FOLDERS:
            (exam_dir / folder).mkdir()
        return exam

    def exam_dir(self, slug: str, exam: str) -> Path:
        subject_dir = self._subject_dir(slug)
        if not _plain_name(exam) or exam in (".", ".."):
            raise NotFound(f"No existe el examen «{exam}».")
        path = subject_dir / exam
        if not (path / "config.json").is_file():
            raise NotFound(f"No existe el examen «{exam}».")
        return path

    def exam_config(self, slug: str, exam: str) -> tuple[ExamConfig | None, list[Issue], str]:
        """(config or None, issues, version of config.json)."""
        path = self.exam_dir(slug, exam) / "config.json"
        cfg, issues = load_exam_config(path, f"{slug}/{exam}/config.json")
        return cfg, issues, file_version(path)

    def save_exam_config_json(self, slug: str, exam: str, text: str, version: str) -> list[Issue]:
        """Parse `text`; without errors, write it normalised. Returns the issues."""
        path = self.exam_dir(slug, exam) / "config.json"
        check_version(path, version)
        file = f"{slug}/{exam}/config.json"
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return [Issue("error", file, f"JSON no válido: {exc}")]
        cfg, issues = parse_exam_config(data, file)
        if cfg is None or any(i.level == "error" for i in issues):
            return issues
        save_exam_config(path, cfg)
        return issues

    def orphan_columns(self, slug: str, exam: str) -> list[str]:
        """Non-leaf, non-reserved columns holding data in any sheet or revision."""
        exam_dir = self.exam_dir(slug, exam)
        cfg, _, _ = self.exam_config(slug, exam)
        if cfg is None:
            return []
        known = set(cfg.leaf_ids()) | RESERVED_COLUMNS
        paths = [exam_dir / "notas" / f"{g}.csv" for g in list_graders(exam_dir)]
        paths.append(exam_dir / "notas" / "final.csv")
        paths += list_revisions(exam_dir)
        orphans: list[str] = []
        for path in paths:
            table = read_table(path)
            for col in table.columns:
                if col in known or col in orphans:
                    continue
                if any(row.get(col, "").strip() for row in table.rows):
                    orphans.append(col)
        return orphans

    # --- roster -----------------------------------------------------------

    def _roster_path(self, slug: str, exam: str) -> Path:
        return self.exam_dir(slug, exam) / "alumnos.csv"

    def roster(self, slug: str, exam: str) -> Roster:
        return load_roster(self._roster_path(slug, exam), f"{slug}/{exam}/alumnos.csv")

    def _load_roster_checked(self, slug: str, exam: str, version: str) -> tuple[Path, Roster]:
        path = self._roster_path(slug, exam)
        check_version(path, version)
        return path, load_roster(path, f"{slug}/{exam}/alumnos.csv")

    def roster_diff(self, slug: str, exam: str) -> tuple[list[Student], list[RosterEntry]]:
        """(in the subject but not in the exam, in the exam but not in the subject)."""
        students = self.students(slug).students
        entries = self.roster(slug, exam).entries
        roster_ids = {e.id for e in entries}
        subject_ids = {s.id for s in students}
        return (
            [s for s in students if s.id and s.id not in roster_ids],
            [e for e in entries if e.id and e.id not in subject_ids],
        )

    def add_to_roster(self, slug: str, exam: str, ids: list[str], version: str) -> None:
        path, roster = self._load_roster_checked(slug, exam, version)
        by_id = {s.id: s for s in self.students(slug).students}
        present = {e.id for e in roster.entries}
        added = False
        for sid in ids:
            student = by_id.get(sid)
            if student is None:
                raise NotFound(f"No existe el alumno «{sid}» en la asignatura.")
            if sid in present:
                continue
            roster.entries.append(RosterEntry(sid, student.apellidos, student.nombre, ""))
            present.add(sid)
            added = True
        if added:
            save_roster(path, roster)

    @staticmethod
    def _find_entry(roster: Roster, student_id: str) -> RosterEntry:
        for entry in roster.entries:
            if entry.id == student_id:
                return entry
        raise NotFound(f"«{student_id}» no está en la lista del examen.")

    def update_roster_entry(
        self, slug: str, exam: str, id: str, presentado: str, observaciones: str, version: str
    ) -> None:
        """Set `presentado` (stored canonically) and `observaciones`.

        A `presentado` equal to the current raw cell is kept as is, even when it
        does not parse, so the other field can still be edited.
        """
        path, roster = self._load_roster_checked(slug, exam, version)
        entry = self._find_entry(roster, id)
        parsed = parse_presentado(presentado)
        if parsed is None:
            if presentado.strip() != entry.presentado.strip():
                raise BadRequest(f"Valor de «presentado» no válido: «{presentado}».")
        else:
            entry.presentado = parsed
        entry.observaciones = observaciones.strip()
        save_roster(path, roster)

    def mark_present(self, slug: str, exam: str, version: str) -> int:
        """Set `presentado` to `si` for every unmarked entry. Returns how many changed."""
        path, roster = self._load_roster_checked(slug, exam, version)
        changed = 0
        for entry in roster.entries:
            if parse_presentado(entry.presentado) == "":
                entry.presentado = "si"
                changed += 1
        if changed:
            save_roster(path, roster)
        return changed

    def remove_from_roster(self, slug: str, exam: str, id: str, version: str) -> None:
        path, roster = self._load_roster_checked(slug, exam, version)
        self._find_entry(roster, id)
        roster.entries = [e for e in roster.entries if e.id != id]
        save_roster(path, roster)

    # --- graders, sheets and feedback -------------------------------------

    def graders(self, slug: str, exam: str) -> list[str]:
        return list_graders(self.exam_dir(slug, exam))

    def create_grader(self, slug: str, exam: str, name: str) -> str:
        exam_dir = self.exam_dir(slug, exam)
        if not name.strip():
            raise BadRequest("El nombre del corrector no puede estar vacío.")
        grader = slugify(name)
        if grader == FINAL:
            raise BadRequest("«final» es un nombre reservado.")
        path = exam_dir / "notas" / f"{grader}.csv"
        if grader in list_graders(exam_dir) or path.exists():
            raise BadRequest(f"Ya existe el corrector «{grader}».")
        cfg = self._require_config(slug, exam)
        write_table(path, Table(columns=sheet_columns(cfg, grader)))
        return grader

    def _check_sheet_name(self, exam_dir: Path, name: str) -> None:
        if name != FINAL and name not in list_graders(exam_dir):
            raise NotFound(f"No existe el corrector «{name}».")

    def sheet(self, slug: str, exam: str, name: str) -> GradeSheet:
        exam_dir = self.exam_dir(slug, exam)
        self._check_sheet_name(exam_dir, name)
        return load_sheet(exam_dir / "notas" / f"{name}.csv", name)

    def save_grade_row(
        self,
        slug: str,
        exam: str,
        name: str,
        id: str,
        raw_cells: dict[str, str],
        version: str,
    ) -> tuple[str, dict[str, str]]:
        """Validate and save one row. Keys of `raw_cells`: leaf ids, `total`, `comentario`.

        On validation errors nothing is written and the current version is
        returned with the errors (column → message).
        """
        sheet = self.sheet(slug, exam, name)
        roster = self.roster(slug, exam)
        if not any(e.id == id for e in roster.entries):
            raise NotFound(f"«{id}» no está en la lista del examen.")
        check_version(sheet.path, version)
        cfg = self._require_config(slug, exam)
        editable = {*cfg.leaf_ids(), "total", "comentario"}
        unknown = sorted(set(raw_cells) - editable)
        if unknown:
            raise BadRequest(f"Columnas no editables: {', '.join(unknown)}.")
        values: dict[str, str] = {}
        errors: dict[str, str] = {}
        for col, raw in raw_cells.items():
            value, error = validate_cell(cfg, col, raw)
            if error:
                errors[col] = error
            else:
                values[col] = value
        if errors:
            return sheet.version, errors
        if name == FINAL:
            values["origen"] = "manual"
        sheet.set_row(id, values)
        save_sheet(sheet, cfg, roster)
        return sheet.version, {}

    def _feedback_path(self, slug: str, exam: str, name: str, id: str) -> Path:
        exam_dir = self.exam_dir(slug, exam)
        self._check_sheet_name(exam_dir, name)
        if not _plain_name(id) or id in (".", ".."):
            raise NotFound(f"No existe el alumno «{id}».")
        return exam_dir / "notas" / name / f"{id}.md"

    def feedback(self, slug: str, exam: str, name: str, id: str) -> tuple[str, str]:
        """(text, version) of notas/<name>/<id>.md; ("", "") when it does not exist."""
        path = self._feedback_path(slug, exam, name, id)
        if not path.is_file():
            return "", ""
        return path.read_text(encoding="utf-8", errors="replace"), file_version(path)

    def save_feedback(
        self, slug: str, exam: str, name: str, id: str, text: str, version: str
    ) -> None:
        """Write the long feedback; an empty text moves the existing file to the trash."""
        path = self._feedback_path(slug, exam, name, id)
        check_version(path, version)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            if path.is_file():
                move_to_trash(self.root, path)
            return
        if not text.endswith("\n"):
            text += "\n"
        atomic_write_text(path, text)

    # --- files ------------------------------------------------------------

    def _area_dir(self, slug: str, exam: str, area: str) -> Path:
        if not AREA_RE.match(area):
            raise BadRequest(f"Destino no válido: «{area}».")
        exam_dir = self.exam_dir(slug, exam)
        folder = exam_dir / area
        safe_resolve(self.root, self._rel(folder))
        return folder

    def list_files(self, slug: str, exam: str, area: str) -> list[FileInfo]:
        folder = self._area_dir(slug, exam, area)
        if not folder.is_dir():
            return []
        files = []
        for path in sorted(folder.iterdir(), key=lambda p: p.name):
            if path.name.startswith(".") or not path.is_file():
                continue
            files.append(
                FileInfo(
                    name=path.name,
                    rel_path=self._rel(path),
                    size=path.stat().st_size,
                    is_pdf=path.suffix.lower() == ".pdf",
                )
            )
        return files

    def save_upload(self, slug: str, exam: str, area: str, filename: str, data: bytes) -> str:
        """Store an upload under a sanitised, unique name. Returns the path relative to root."""
        folder = self._area_dir(slug, exam, area)
        folder.mkdir(parents=True, exist_ok=True)
        target = unique_path(folder, sanitize_filename(filename))
        atomic_write_bytes(target, data)
        return self._rel(target)

    def trash_file(self, slug: str, exam: str, rel_path: str) -> None:
        """Move an uploaded file (in an AREA_RE folder of this exam) to the trash."""
        exam_dir = self.exam_dir(slug, exam).resolve()
        path = safe_resolve(self.root, rel_path)
        try:
            parent = path.parent.relative_to(exam_dir).as_posix()
        except ValueError:
            raise BadRequest("Solo se pueden borrar archivos subidos a este examen.") from None
        if not AREA_RE.match(parent):
            raise BadRequest("Solo se pueden borrar archivos del enunciado o de las entregas.")
        if not path.is_file():
            raise NotFound(f"No existe el archivo «{rel_path}».")
        move_to_trash(self.root, path)

    def _submission_dirs(self, exam_dir: Path) -> list[Path]:
        entregas = exam_dir / "entregas"
        if not entregas.is_dir():
            return []
        return sorted(
            (p for p in entregas.iterdir() if p.is_dir() and not _is_hidden(p.name)),
            key=lambda p: p.name,
        )

    def submission_counts(self, slug: str, exam: str) -> dict[str, tuple[int, int]]:
        """id → (#files in original/, #files in corregido/), for roster ids and folders."""
        exam_dir = self.exam_dir(slug, exam)
        counts = {e.id: (0, 0) for e in self.roster(slug, exam).entries if e.id}
        for folder in self._submission_dirs(exam_dir):
            counts[folder.name] = (
                _count_files(folder / "original"),
                _count_files(folder / "corregido"),
            )
        return counts

    def orphan_submission_dirs(self, slug: str, exam: str) -> list[str]:
        exam_dir = self.exam_dir(slug, exam)
        roster_ids = {e.id for e in self.roster(slug, exam).entries}
        return [p.name for p in self._submission_dirs(exam_dir) if p.name not in roster_ids]
