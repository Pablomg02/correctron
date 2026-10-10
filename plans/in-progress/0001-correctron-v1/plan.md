---
id: "0001"
title: "Correctron v1: file-first grading tool with local web UI"
type: plan
created: 2026-10-10
---

# 0001 — Correctron v1: file-first grading tool with local web UI

## Justification

The user is a university teacher who grades exams and assignments for several
subjects. Today the material for one exam (student list, statement, rubric,
each student's submission, the grades of each grader, later grade revisions)
is scattered, and nothing records who graded what or how a grade changed.
The user also wants to use an LLM as one more grader, which means the grades
must live in files an LLM can write without any special tool.

Correctron centralises everything in a plain folder tree (`data/`) made of
CSV, JSON, Markdown and PDF files that stay fully usable without the tool, and
adds a local web page to manage that tree comfortably. Every file the web
writes can also be edited by hand or by an LLM, and the web picks up those
edits.

### Goals

- G1. A documented, human- and LLM-friendly data format under `data/`
  (Appendix A), with a format guide `data/LEEME.md` written automatically.
- G2. A local web UI (Spanish) started with `uv run correctron` that lets the
  user:
  - create subjects and exams/assignments;
  - add, edit, remove and bulk-import students in a subject;
  - manage each exam's roster, including marking each student as present or
    absent (*presentado*);
  - edit the exam configuration, including criteria with one level of
    sub-criteria and three ways of computing the total;
  - upload and view PDFs (statement, rubric) and each student's original and
    corrected submission;
  - enter grades per grader, with the breakdown and short or long feedback;
  - compare graders and build the official `final.csv`;
  - record grade revisions as a history;
  - see the effective grades (final plus revisions, NP for absent students).
- G3. Files edited outside the web are read on every request; the web detects
  external changes and never silently overwrites them (version tokens plus
  atomic writes).
- G4. Validation reports every inconsistency in the files (unknown students,
  out-of-range grades, bad numbers, totals that do not add up) without
  refusing to show the data.
- G5. Test suite (`uv run pytest`) and lint (`uv run ruff check`) pass, with
  fictional sample data in `ejemplo/data/`.

### Non-goals

- LLM grader kit (template CSV, generated prompt, `correctron validar` CLI):
  ticket 0002.
- Exporting grades to CSV/XLSX for official records: ticket 0003.
- Importing a Moodle/MooVi submissions zip: ticket 0004.
- Subject final grade computed from weighted exams: ticket 0005.
- Deleting or renaming subjects and exams from the web (done in the file
  manager in v1).
- Rendering Markdown feedback as HTML (it is edited as plain text).
- Authentication, multi-user access, or serving on anything other than
  `127.0.0.1`.
- Calling any LLM API from the tool.
- Committing real student data: `data/` is git-ignored.

## Plan

### Context

- The repository is empty (no commits). Everything is new.
- Available on the user's machine: Python 3.14.4, `uv` (`~/.local/bin/uv`),
  Node 22 (not used).
- Commands once T1 is done:
  - run: `uv run correctron` (options in T11);
  - tests: `uv run pytest`;
  - lint: `uv run ruff check` and `uv run ruff format --check`.
- The user edits CSVs mainly in a text editor or VS Code, so the canonical
  CSV format is comma-separated with dot decimals (D9).
- The canonical data format is **Appendix A** of this plan. Every task that
  reads or writes data follows it. When a task and the appendix disagree, the
  appendix wins.

### Approach

**File-first, no database.** The folder tree is the only source of truth. The
server holds no state and no cache: each request reads the files it needs
(an exam has at most a few hundred rows, so this is cheap). This makes
external edits by the user or an LLM visible immediately and removes any
sync problem.

**Layers** (all under `src/correctron/`):

1. *Storage primitives*: `fsutil.py` (atomic writes, safe paths, trash,
   fingerprints, file versions), `csvtable.py` (tolerant CSV reader and
   writer that keeps the dialect and the unknown columns), `numbers.py`,
   `slug.py`.
2. *Domain*: `models.py` (dataclasses), `config_io.py` (`config.json` and
   `asignatura.json`), `roster.py` (students), `grades.py` (grade sheets and
   totals), `effective.py` (final plus revisions), `validation.py`.
3. *Repository façade*: `repo.py`, the only API the web layer calls.
4. *Web*: FastAPI + Jinja2 templates (server-rendered) + htmx for partial
   updates + Alpine.js for the criteria editor and small client
   interactions. Pico.css for styling. All three libraries are vendored into
   `static/vendor/`, so it works offline and needs no build step.

**Never lose data.** Cells are kept as raw strings. Parsing happens on
demand, so a value the tool does not understand is shown in red and written
back unchanged. Unknown columns are kept. A CSV with structural damage (a row
with more cells than the header) is shown read-only and the web refuses to
write it until it is fixed by hand. Removing a student from a list never
deletes their grades or files. Deleting an uploaded file moves it to
`data/.papelera/`.

**Concurrency with external editors.** Every page that edits a file embeds
that file's *version* (a short SHA-256 of its bytes). Every write sends the
version back. The server re-reads the file and answers `409` if it changed.
Each exam page also polls a fingerprint of the exam folder every 3 s and
shows a "files changed, reload" banner instead of reloading on its own (which
would lose what the user is typing). Writes are atomic: a temporary file in
the same folder, then `os.replace`.

**Discarded alternatives.**

- A SPA (Svelte/React): two languages and a build step. Rejected by the user
  (D1).
- SQLite with export: breaks the "files are the truth" principle.
- Markdown tables for lists: hard to parse safely on round trips and weaker
  in spreadsheets. CSV is what both people and LLMs handle best.
- Full snapshots per revision: duplication, and the change is hard to see
  (D5).
- Per-cell version checks: more complex. Whole-file versions are enough for
  a single user.

### Decisions

| # | Decision | Rationale | Source |
| --- | --- | --- | --- |
| D1 | Python ≥ 3.12, FastAPI + Jinja2 + htmx 2.0.4 + Alpine.js 3.14.8 + Pico.css 2.0.6, no frontend build; packaged with `uv` and `hatchling`. | One language, one command to run, easy to hack. | user |
| D2 | The student id is a slug `apellidos-nombre` (lowercase, accents stripped, non-alphanumerics → `-`). It is generated once when the student is created, stored in column `id`, and never changed automatically, even if the name is edited. Homonyms get `-2`, `-3`… | User chose the slug. Immutability and suffixes avoid its two failure modes. | user |
| D3 | Each grader writes `notas/<grader>.csv`. The official grade is `notas/final.csv`, built from the comparison view (copy one grader's row per student, or bulk copy) or edited directly. It has an `origen` column (grader name or `manual`). | Allows mixing graders while keeping one explicit official file. | user |
| D4 | Feedback: a short `comentario` column in the CSV plus optional long feedback in `notas/<grader>/<id>.md` (also `notas/final/<id>.md`), editable from the web as plain text. | Keeps CSVs readable while allowing an LLM's long justifications. | user |
| D5 | Revisions are delta files `revisiones/NN-YYYY-MM-DD.csv` holding only the revised students, with columns for the criteria, `total` and `motivo`. A blank criterion cell means unchanged. Effective grade = `final.csv` + revisions applied in file-name order. | Readable history, small files, clear diffs. | user |
| D6 | Criteria have at most two levels. A top-level criterion is either a leaf (has `maximo`) or a group (has `subcriterios`, a list of leaves). Only leaves are columns in CSVs. Group subtotals are computed, never stored. | Covers "Ejercicio 1 → a, b" without complicating the CSV. | user |
| D7 | `calculo_total` per exam: `suma` (total = sum of leaves), `ponderada` (top-level items weighted by `peso` and scaled to `nota_maxima`) or `manual` (total typed by hand, breakdown informative). With no criteria, the total is always manual. | User chose a configurable total. | user |
| D8 | Submissions live in `entregas/<id>/original/` and `entregas/<id>/corregido/`, each holding any number of files. | User wants both the uncorrected and the corrected PDF, possibly with several files. | user |
| D9 | CSV canonical format: UTF-8, comma delimiter, dot decimals, header row, minimal quoting, `\n` line endings. The reader sniffs `,`, `;` or tab, accepts `7,5` as a number, and strips a BOM. When rewriting an existing file, the delimiter, encoding and BOM it had are kept. The delimiter is the candidate that appears most often in the header line. | The user edits in VS Code; Excel files keep working. | user |
| D10 | v1 scope excludes the LLM kit, export, Moodle import and subject final grade. They are tickets 0002–0005. | User decision. | user |
| D11 | Folder and file names are in Spanish without accents: `enunciado/`, `entregas/`, `notas/`, `revisiones/`, `alumnos.csv`, `config.json`, `asignatura.json`, `LEEME.md`. The UI is in Spanish; code identifiers, comments and tests are in English. | The user works in Spanish; English code is conventional. | plan |
| D12 | `data/` is git-ignored. The data directory is chosen by `--data`, then the env var `CORRECTRON_DATA`, then `./data`. Fictional sample data lives in `ejemplo/data/` and is committed. | Student data is personal (GDPR) and must not reach a code repository. | plan |
| D13 | A subject is any non-hidden directory directly in the data root. An exam is any subdirectory of a subject that contains `config.json`. Other subdirectories are ignored, so the user can keep their own folders. Names starting with `.` or `_` are hidden. | Lets the user organise freely; detection is unambiguous. | plan |
| D14 | The server re-reads files on every request (no cache). Writes carry a version token (first 16 hex chars of the SHA-256 of the file's bytes, `""` for a missing file), and a mismatch answers 409. Exam and subject pages poll a fingerprint every 3 s and show a reload banner. Every htmx mutation response refreshes, out of band, the page's current fingerprint (`#huella-actual`) and version (`#version-lista` / `#version-hoja`), so the web's own writes never trigger the banner or a 409. | External edits always win and are never overwritten silently. | plan, review |
| D15 | When the web writes a CSV, rows are sorted by `id`, the header is lowercased, cells are stripped, and the `alumno` column of grade sheets is refreshed as `Apellidos, Nombre` from the exam roster (kept as is for ids not in the roster). | Deterministic diffs and readable files. | plan |
| D16 | Invalid values typed in the web (not a number, out of range) are rejected with an inline error and not saved. Invalid values found in files are kept, shown in red, and reported by validation. | The web never produces bad data and never destroys data it did not write. | plan |
| D17 | Removing a student from a subject or roster deletes only that row. Grades, feedback and submissions stay and show up as "fuera de la lista" warnings. Editing a subject student's `apellidos`/`nombre` updates the same id in every exam roster of that subject. | No implicit data loss; names stay consistent. | plan |
| D18 | Deleted uploads go to `data/.papelera/<YYYYMMDD-HHMMSS>/<relative path>`. There is no delete for subjects or exams in v1. | Cheap undo; dangerous operations stay in the file manager. | plan |
| D19 | `GET /archivo/...` serves PDFs and images inline. Any other type is served as an attachment with `X-Content-Type-Options: nosniff`, so uploaded HTML cannot run scripts in the app's origin. Only paths inside the data root are served. | Basic safety for a local server. | plan |
| D20 | Grader names: `[a-z0-9][a-z0-9_-]*`, created through `slugify`. `final` is reserved. | They are file names and CSV keys. | plan |
| D21 | Numbers: `decimal.Decimal` everywhere. Totals are rounded to `decimales` (default 2) with `ROUND_HALF_UP`. Written without trailing zeros (`7.50` → `7.5`, `8.00` → `8`). | Avoids float artefacts in grades. | plan |
| D22 | In the comparison view, a leaf cell is a discrepancy when the non-blank grader values are not all equal. A total is a strong discrepancy when max − min ≥ 10 % of `nota_maxima`. | Simple, predictable highlighting. | plan |
| D23 | Saving a final row from the grades grid sets `origen` to `manual`. "Usar <grader>" copies that grader's leaves, `total` and `comentario`, plus `notas/<grader>/<id>.md` to `notas/final/<id>.md` if it exists, and sets `origen=<grader>`. Every cell copied or compared across files is canonicalised: a valid number is written as `format_number(parse_number(raw))`, and an invalid raw value is copied as it is. | `origen` always tells where the official grade came from; decimal commas from LLM files never leak into comma-delimited files. | plan, review |
| D24 | Bulk student import is a textarea, one student per line: `Apellidos, Nombre[, email]` or tab-separated `Apellidos<TAB>Nombre[<TAB>email]` (pasted from a spreadsheet). Blank lines are skipped. A line that cannot be parsed is reported, and nothing is written if any line fails. | Covers copying from MooVi/Excel without a full import wizard. | plan |
| D26 | Inline edits (one cell or row) answer with `hx-swap="none"` plus out-of-band swaps of computed values and state only, so the input the user moved to is never replaced. Structural changes (add, import, remove, bulk actions) re-render a whole wrapper `<div id="panel-…">` with `outerHTML`, never a bare `tbody`. Notices go out of band into `#avisos`. | Prevents losing keystrokes and the htmx `<tr>`-parsing pitfall. | review |
| D27 | Fixed-path actions never share a path shape with `{id}` routes: `/a/{s}/importar-alumnos`, `/a/{s}/e/{e}/marcar-presentados`. | Starlette matches routes in order; a fixed segment would be captured as an id. | review |
| D28 | The repository raises `repo.NotFound(KeyError)` and `repo.BadRequest(ValueError)`. Only these (plus `VersionConflict`, `CsvMalformed`, `PathOutsideData`) have HTTP handlers, so real bugs still show a traceback. | Debuggability. | review |
| D25 | A new exam gets a default `config.json` (`tipo` as chosen, `nota_maxima` 10, `decimales` 2, `calculo_total` `suma`, `criterios` `[]`), a roster copied from the subject with `presentado` blank (when the "copiar alumnos" box is checked, the default), and empty `enunciado/`, `entregas/`, `notas/`, `revisiones/` folders. | Ready to use in one click. | plan |

### Tasks

Conventions for every task: tests go in `tests/`, use the `sample_data`
fixture from T3 when data is needed, and `uv run pytest` and
`uv run ruff check` pass when the task ends. Signatures written here are
binding. Private helpers are up to the implementer. Dataclass fields with
mutable defaults always use `field(default_factory=…)` (for example
`extra: dict[str, str] = field(default_factory=dict)`), even where a
signature below abbreviates it as `= {}` or `= []`.

#### T1 — Project scaffold

- **Objective:** An installable `uv` project with an empty package, a CLI
  entry point, test and lint tooling, and `data/` git-ignored.
- **Files:** `pyproject.toml`, `.gitignore`, `.python-version` (`3.14`, the installed interpreter),
  `README.md` (stub: one paragraph plus run, test and lint commands),
  `src/correctron/__init__.py` (`__version__ = "0.1.0"`),
  `src/correctron/cli.py`, `tests/test_cli.py`.
- **Depends on:** —
- **Details:** `pyproject.toml` sets `[project] name = "correctron"`,
  `requires-python = ">=3.12"`, dependencies `fastapi>=0.115`,
  `uvicorn>=0.30`, `jinja2>=3.1`, `python-multipart>=0.0.9`, and
  `[project.scripts] correctron = "correctron.cli:main"`. It uses build
  backend `hatchling` with `[tool.hatch.build.targets.wheel] packages =
  ["src/correctron"]`. The dev group (`[dependency-groups] dev`) has
  `pytest>=8`, `httpx>=0.27` and `ruff>=0.6`. Ruff settings: `line-length =
  100`, `select = ["E","F","I","UP","B"]`. `.gitignore`: `/data/` (anchored, so `ejemplo/data/` stays tracked), `.venv/`,
  `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `dist/`.
  `cli.main(argv=None)` uses argparse with `--data`, `--host` (default
  `127.0.0.1`), `--port` (default `8765`) and `--no-abrir`. In this task it
  only parses the arguments and prints them. T11 starts the server.
- **Acceptance criteria:**
  - [ ] `uv sync` succeeds and `uv run correctron --help` prints usage with the four options.
  - [ ] `uv run pytest` passes (`tests/test_cli.py` checks that `main(["--help"])` raises `SystemExit(0)`).
  - [ ] `uv run ruff check` and `uv run ruff format --check` exit 0.
  - [ ] `git check-ignore data/x` prints `data/x`.

#### T2 — Data format guide (LEEME.md)

- **Objective:** The Spanish format guide that is copied into every data root
  and is the reference for the user and for LLM graders.
- **Files:** `src/correctron/resources/LEEME.md`.
- **Depends on:** T1
- **Details:** A faithful Spanish rendering of Appendix A, covering every file
  and column, the rules, and one complete example of each file type. It ends
  with a section *"Instrucciones para un corrector LLM"* that says: write
  `notas/<nombre>.csv` with the exact header `id,alumno,<hojas en orden de
  config.json>,total,comentario`; one row per present student; dot decimals;
  values within each `maximo`; leave a cell blank if not graded; long
  feedback goes in `notas/<nombre>/<id>.md`; never edit `final.csv`,
  `alumnos.csv` or `config.json`.
- **Acceptance criteria:**
  - [ ] The file contains the headings `## Estructura`, `## asignatura.json`, `## alumnos.csv (asignatura)`, `## config.json`, `## alumnos.csv (examen)`, `## notas/<corrector>.csv`, `## notas/final.csv`, `## revisiones/`, `## entregas/`, `## Instrucciones para un corrector LLM` (check with `grep -c '^## ' src/correctron/resources/LEEME.md` ≥ 10 and grep for each heading).
  - [ ] Every column name and JSON key of Appendix A appears in the file (check with grep for `presentado`, `calculo_total`, `subcriterios`, `peso`, `origen`, `motivo`, `decimales`, `nota_maxima`).

#### T3 — Sample data and test fixture

- **Objective:** Committed fictional data that exercises every feature, plus
  a pytest fixture that copies it to a temporary directory.
- **Files:** `scripts/make_sample_pdf.py`, everything under `ejemplo/data/`
  (exact contents in Appendix B), `tests/conftest.py`,
  `tests/test_sample_data.py`.
- **Depends on:** T2
- **Details:** `scripts/make_sample_pdf.py OUT TEXT` writes a valid one-page
  PDF with the text in Helvetica, using only the standard library (build the
  objects and compute the xref offsets). Run it to create the PDFs listed in
  Appendix B. `conftest.py` defines a fixture `sample_data(tmp_path) -> Path`
  that copies `ejemplo/data` to `tmp_path / "data"` and returns that path.
- **Acceptance criteria:**
  - [ ] Every file listed in Appendix B exists with the exact content given there.
  - [ ] `python3 -c "print(open('ejemplo/data/mecanica-de-vuelo/parcial-1/enunciado/enunciado.pdf','rb').read(5))"` prints `b'%PDF-'`, and the file opens in a PDF viewer (check `file <path>` reports `PDF document`).
  - [ ] `tests/test_sample_data.py` uses `sample_data` and asserts that `config.json` of `parcial-1` parses as JSON, and that the copy does not modify `ejemplo/data`.

#### T4 — Storage primitives

- **Objective:** Safe, tested building blocks for every file operation.
- **Files:** `src/correctron/fsutil.py`, `src/correctron/csvtable.py`,
  `src/correctron/numbers.py`, `src/correctron/slug.py`,
  `tests/test_fsutil.py`, `tests/test_csvtable.py`, `tests/test_numbers.py`,
  `tests/test_slug.py`.
- **Depends on:** T1
- **Binding interfaces:**
  - `fsutil.atomic_write_text(path: Path, text: str, *, bom: bool = False, encoding: str = "utf-8") -> None`
    and `atomic_write_bytes(path: Path, data: bytes) -> None`: these create
    the parent directories, write `path.name + ".tmp-<pid>"` in the same
    directory, call `fsync`, then `os.replace`.
  - `fsutil.PathOutsideData(Exception)`;
    `safe_resolve(root: Path, rel: str) -> Path`: resolves `root / rel` and
    raises `PathOutsideData` if the result is not inside `root.resolve()`
    (covers `..`, absolute paths and symlinks pointing outside).
  - `fsutil.file_version(path: Path) -> str`: the first 16 hex chars of the
    SHA-256 of the bytes, or `""` if the file is missing.
  - `fsutil.tree_fingerprint(path: Path) -> str`: SHA-256 (16 hex chars) over
    the sorted `(relative path, mtime_ns, size)` of every file under `path`,
    skipping `.papelera` and `*.tmp-*` files.
  - `fsutil.move_to_trash(root: Path, path: Path, *, now: datetime | None = None) -> Path`:
    moves the file to `root/.papelera/<YYYYMMDD-HHMMSS>/<path relative to root>`
    and returns the new path.
  - `fsutil.sanitize_filename(name: str) -> str`: keeps only the last path
    component (splitting on both `/` and `\`), removes control characters,
    strips spaces and dots at both ends, and returns `"archivo"` if nothing
    is left.
    `fsutil.unique_path(directory: Path, name: str) -> Path`: if the name is
    taken, inserts ` (2)`, ` (3)`… before the extension.
  - `csvtable.Table` dataclass: `columns: list[str]`,
    `rows: list[dict[str, str]]`, `delimiter: str = ","`, `bom: bool = False`,
    `encoding: str = "utf-8"` (`"utf-8"` or `"cp1252"`),
    `malformed: list[int]` (1-based line numbers of rows with more cells than
    the header).
  - `csvtable.read_table(path: Path) -> Table`: a missing file gives an empty
    `Table()`. Decoding is UTF-8 (BOM stripped and remembered), with fallback
    to cp1252 (remembered in `Table.encoding`). The delimiter is whichever of
    `,`, `;` and `\t` appears most often in the header line (ties and zero
    counts → `,`); do not use `csv.Sniffer`. Header names are
    stripped and lowercased, and cells stripped. Fully blank rows are
    skipped. Short rows are padded with `""`. Long rows go into `malformed`
    and only their first `len(columns)` cells are kept.
  - `csvtable.CsvMalformed(Exception)`;
    `csvtable.write_table(path: Path, table: Table) -> None`: raises
    `CsvMalformed` if `table.malformed` is non-empty. Otherwise it writes the
    header plus rows in `table.columns` order with `csv.QUOTE_MINIMAL`, the
    table's delimiter, `\n` line endings, the BOM if `table.bom` and `table.encoding`, through
    `atomic_write_text`.
  - `numbers.parse_number(raw: str) -> Decimal | None`: blank gives `None`.
    It accepts `7.5`, `7,5`, ` 7 ` and `-0`. If both `,` and `.` appear, or
    the text is not numeric, it raises `ValueError`.
    `numbers.format_number(d: Decimal) -> str` (no exponent, no trailing
    zeros). `numbers.round_grade(d: Decimal, decimales: int) -> Decimal`
    (`ROUND_HALF_UP`).
  - `slug.slugify(text: str) -> str`: NFKD, drops combining marks,
    lowercases, turns runs of non-`[a-z0-9]` into `-`, strips `-` at both
    ends, and returns `"x"` if empty.
    `slug.student_slug(apellidos: str, nombre: str, taken: set[str]) -> str`
    gives `slugify(apellidos + " " + nombre)`, with `-2`, `-3`… appended while
    the result is in `taken`.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_fsutil.py tests/test_csvtable.py tests/test_numbers.py tests/test_slug.py` passes.
  - [ ] Tests cover: `safe_resolve` rejects `../x`, `/etc/passwd` and a symlink to outside; a round trip of a `;`-delimited BOM file keeps `;` and the BOM; a file with an extra cell sets `malformed == [3]` and `write_table` raises `CsvMalformed`; unknown columns survive a read/write round trip; `parse_number("7,5") == Decimal("7.5")`; `parse_number("1,234.5")` raises; `format_number(Decimal("8.00")) == "8"`, `format_number(Decimal("10")) == "10"` (not `1E+1`), `format_number(Decimal("100.50")) == "100.5"`; a cp1252 file with `Pérez` round-trips byte-identically and keeps `encoding == "cp1252"`; a header `id;alumno;ej1` with a cell `"Pérez, Ana"` is read with `;`; `round_grade(Decimal("6.125"), 2) == Decimal("6.13")`; `student_slug("Álvarez López", "Ana", {"alvarez-lopez-ana"}) == "alvarez-lopez-ana-2"`; `move_to_trash` puts the file under `.papelera/<ts>/` with its relative path; `tree_fingerprint` changes after a file is modified.

#### T5 — Models and configuration files

- **Objective:** Parse, validate and serialise `config.json` and
  `asignatura.json` into dataclasses, without ever raising on bad input.
- **Files:** `src/correctron/models.py`, `src/correctron/config_io.py`,
  `tests/test_config.py`.
- **Depends on:** T4
- **Binding interfaces:**
  - `models.Issue(level: Literal["error","aviso"], file: str, message: str)`
    (frozen dataclass; `file` is relative to the data root; `message` in
    Spanish).
  - `models.Leaf(id: str, nombre: str, maximo: Decimal)`.
  - `models.Criterion(id: str, nombre: str, peso: Decimal, maximo: Decimal | None, subcriterios: list[Leaf])`,
    with property `is_group` (`bool(subcriterios)`) and method
    `leaves() -> list[Leaf]` (a leaf criterion returns
    `[Leaf(id, nombre, maximo)]`).
  - `models.ExamConfig(nombre: str, tipo: Literal["examen","trabajo"], fecha: str, nota_maxima: Decimal, decimales: int, calculo_total: Literal["suma","ponderada","manual"], criterios: list[Criterion], extra: dict)`,
    with methods `leaves() -> list[Leaf]` (config order), `leaf_ids() -> list[str]`,
    `leaf(id) -> Leaf | None` and `effective_mode() -> str` (`"manual"` if
    there are no criteria, else `calculo_total`).
  - `config_io.RESERVED_COLUMNS = {"id","alumno","total","comentario","origen","motivo"}`.
  - `config_io.parse_exam_config(data: object, file: str) -> tuple[ExamConfig | None, list[Issue]]`:
    applies every rule of Appendix A §config.json. It returns `None` plus
    errors when the config cannot be used, and a config plus *avisos* for
    soft problems (sum of leaf `maximo` ≠ `nota_maxima` in `suma`, only
    when `criterios` is non-empty). Unknown
    top-level keys go to `extra`.
  - `config_io.load_exam_config(path: Path, file: str) -> tuple[ExamConfig | None, list[Issue]]`:
    invalid JSON gives `(None, [Issue("error", file, "JSON no válido: <detalle>")])`.
  - `config_io.exam_config_to_dict(cfg) -> dict` (key order as in Appendix A,
    `extra` keys at the end, Decimals as JSON numbers: int when integral,
    else float of `format_number`).
    `save_exam_config(path, cfg) -> None` (2-space indent,
    `ensure_ascii=False`, trailing newline, atomic).
  - `config_io.default_exam_config(nombre: str, tipo: str, fecha: str) -> ExamConfig` (D25).
  - `config_io.load_subject_meta(path: Path, default_name: str) -> tuple[dict, list[Issue]]`
    (missing file → `{"nombre": default_name, "curso": "", "codigo": ""}`).
    `save_subject_meta(path: Path, meta: dict) -> None`.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_config.py` passes.
  - [ ] Tests cover: the sample `parcial-1` config parses with 4 leaves `["ej1a","ej1b","ej2","ej3"]` and no issues; duplicate ids, a reserved id (`total`), a group with `maximo`, a leaf without `maximo`, `maximo <= 0`, `peso < 0`, an invalid `tipo` or `calculo_total` and `decimales` outside 0–4 each give an `error`; `suma` with leaf maxima summing to 9 and `nota_maxima` 10 gives one `aviso`; `ponderada` with all `peso` 0 gives an `error`; `default_exam_config("X","examen","")` round-tripped through `parse_exam_config` gives no issues; invalid JSON gives `None` plus one error; `parse → to_dict → parse` round-trips the sample configs exactly, including an unknown key.

#### T6 — Student lists (subject and exam roster)

- **Objective:** Load and save both kinds of `alumnos.csv` with
  unknown-column preservation, and parse `presentado`.
- **Files:** `src/correctron/roster.py`, `tests/test_roster.py`.
- **Depends on:** T4, T5
- **Binding interfaces:**
  - `models.Student(id: str, apellidos: str, nombre: str, email: str = "", observaciones: str = "", extra: dict[str,str] = field(default_factory=dict))`
    and `models.RosterEntry(id: str, apellidos: str, nombre: str, presentado: str, observaciones: str = "", extra: dict[str,str] = field(default_factory=dict))`.
    Add both to `models.py`; `presentado` holds the raw cell.
  - `roster.parse_presentado(raw: str) -> Literal["si","no",""] | None`:
    case-insensitive and stripped. `si`, `sí`, `s`, `x`, `1`, `true`, `yes`
    and `presentado` give `"si"`; `no`, `n`, `0`, `false`, `np` and
    `no presentado` give `"no"`; blank gives `""`; anything else gives `None`.
  - `roster.StudentList` dataclass: `students: list[Student]`,
    `table: Table` (the source table, kept for dialect, extra columns and
    `malformed`), `version: str`, `issues: list[Issue]`. Same shape for
    `roster.Roster` with `entries: list[RosterEntry]`.
  - `roster.load_students(path: Path, file: str) -> StudentList` and
    `roster.load_roster(path: Path, file: str) -> Roster`: issues for missing
    required columns (`id`, `apellidos`, `nombre`), duplicate ids, blank ids,
    and (roster only) invalid `presentado`.
  - `roster.save_students(path: Path, sl: StudentList) -> None` and
    `roster.save_roster(path: Path, r: Roster) -> None`: rebuild the table
    from the dataclasses. Column order is the canonical columns (Appendix A),
    then any extra columns in their original order. Rows are sorted by `id`.
    Delimiter and BOM come from the source table. These functions raise
    `CsvMalformed` if the source table is malformed.
  - `roster.parse_import_text(text: str) -> tuple[list[tuple[str,str,str]], list[str]]`:
    returns `(apellidos, nombre, email)` triples and error messages
    (`"Línea N: …"`) per D24.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_roster.py` passes.
  - [ ] Tests cover: the sample subject list loads 6 students; the `parcial-1` roster loads 6 entries with `parse_presentado` giving `"no"` for `martinez-souto-diego`; an extra column `grupo` survives a save; `parse_presentado("Sí") == "si"`, `parse_presentado("NP") == "no"`, `parse_presentado("tal vez") is None`; `parse_import_text("Pérez, Ana\nRuiz\tLuis\tl@x.org\n\n")` gives two triples and no errors; a line `"SoloUnaPalabra"` gives an error naming line 1.

#### T7 — Grade sheets and total computation

- **Objective:** Read and write grader sheets and compute totals for the
  three modes, with groups, partial grading and rounding.
- **Files:** `src/correctron/grades.py`, `tests/test_grades.py`.
- **Depends on:** T5, T6
- **Binding interfaces:**
  - `grades.GradeResult` dataclass: `leaves: dict[str, Decimal | None]`,
    `groups: dict[str, Decimal | None]` (group id → sum of its leaves, `None`
    if any leaf is blank), `total: Decimal | None` (rounded; `None` when
    incomplete), `partial: Decimal | None` (`suma` only: rounded sum of the
    filled leaves when incomplete), `complete: bool`,
    `cell_errors: dict[str, str]` (column → Spanish message for unparsable
    or out-of-range cells).
  - `grades.compute(cfg: ExamConfig, cells: dict[str, str]) -> GradeResult`:
    follows Appendix A §Total computation exactly. In `manual` mode, `total`
    comes from the `total` cell, validated within `[0, nota_maxima]`. A cell
    error on a leaf makes the result incomplete.
  - `grades.GradeSheet` dataclass: `name: str` (grader name or `"final"`),
    `path: Path`, `table: Table`, `version: str`.
    Methods: `row(student_id) -> dict[str,str] | None`;
    `set_row(student_id, cells: dict[str,str]) -> None` (creates the row if
    missing and only updates the given columns);
    `remove_row(student_id) -> None`.
  - `grades.load_sheet(path: Path, name: str) -> GradeSheet`.
  - `grades.save_sheet(sheet: GradeSheet, cfg: ExamConfig, roster: Roster) -> None`:
    sets the columns to `id, alumno, <leaf ids>, total, comentario` (plus
    `origen` when `name == "final"`), then unknown existing columns in their
    original order. It refreshes `alumno` (D15), and in `suma`/`ponderada`
    writes `total` as `format_number(compute(...).total)` or `""` when
    incomplete. Rows are sorted by `id`. Atomic write.
  - `grades.list_graders(exam_dir: Path) -> list[str]`: stems of
    `notas/*.csv` except `final`, sorted.
  - `grades.validate_cell(cfg: ExamConfig, column: str, raw: str) -> tuple[str, str | None]`:
    returns `(canonical_value, error)` for web input. It parses with
    `parse_number`, checks `[0, maximo]` for leaves and `[0, nota_maxima]`
    for `total`, and returns `format_number` of the value. `comentario`
    passes through stripped.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_grades.py` passes.
  - [ ] Tests cover: the sample `pablo.csv` row for `alvarez-lopez-ana` computes total `9`, group `ej1` = `3.5`; `garcia-perez-lucia` in `pablo.csv` is incomplete with `partial == Decimal("4")` and `total is None`; ponderada `memoria=8, presentacion=5` (weights 2 and 1, `nota_maxima` 10) gives `7`; a leaf `"abc"` gives a `cell_errors` entry and `complete == False`; `ej1a = 2.5` with `maximo` 2 gives an out-of-range error; manual mode with `total = "6,75"` gives `6.75`; rounding with `decimales=1` of a 6.25 sum gives `6.3`; `save_sheet` writes the canonical header order, keeps an unknown column `revisado_por`, recomputes a wrong `total` and refreshes `alumno`; `validate_cell(cfg,"ej2","2,5") == ("2.5", None)`.

#### T8 — Final grade, revisions and effective grades

- **Objective:** Compute each roster student's effective grade from
  `final.csv` and the revision files, and provide the operations to write
  revisions and copy grader rows to final.
- **Files:** `src/correctron/effective.py`, `tests/test_effective.py`.
- **Depends on:** T7
- **Binding interfaces:**
  - `effective.REVISION_RE = re.compile(r"^(\d{2})-(\d{4}-\d{2}-\d{2})\.csv$")`.
  - `effective.list_revisions(exam_dir: Path) -> list[Path]`: every
    `revisiones/*.csv`, sorted by file name.
  - `effective.new_revision(exam_dir: Path, today: date) -> Path`: creates
    `revisiones/<NN+1>-<today>.csv` (NN = highest existing NN, or 0), with
    header `id,alumno,<leaf ids>,total,motivo` and no rows.
  - `effective.grade_before(exam_dir, cfg, student_id, revision: Path | None) -> dict[str,str]`:
    the student's leaf, `total` and `comentario` cells from `final.csv` with
    every revision strictly before `revision` applied (all revisions when
    `revision` is `None`). Non-blank revision cells replace values; blank
    cells inherit. In computed modes, the `total` cell is recomputed after
    merging.
  - `effective.save_revision_row(exam_dir, cfg, roster, revision: Path, student_id, cells: dict[str,str], motivo: str, version: str) -> str`:
    writes only the leaf cells whose value differs numerically
    (`parse_number`) from `grade_before(...)`, canonicalised (D23), plus the
    recomputed `total` (or the typed one in manual mode) and `motivo`.
    It replaces the student's row if present, checks the version (raises
    `VersionConflict`), and returns the new file version.
  - `effective.copy_to_final(exam_dir, cfg, roster, grader: str, student_ids: list[str]) -> int`:
    implements D23 for each id that has a row in the grader sheet. Returns
    the number of rows copied.
  - `effective.EffectiveGrade` dataclass: `id`, `alumno`, `presentado`
    (`"si"|"no"|""`), `status: Literal["np","sin_nota","incompleta","ok"]`,
    `cells: dict[str,str]`, `result: GradeResult | None`,
    `revised_in: list[str]` (revision file names that touched this student).
  - `effective.effective_grades(exam_dir, cfg, roster) -> list[EffectiveGrade]`:
    one per roster entry, in roster order. `presentado == "no"` gives `np`.
    No final row and no revision row gives `sin_nota`. An incomplete result
    gives `incompleta`. Otherwise `ok`.
  - `fsutil.VersionConflict(Exception)`: add it to `fsutil.py`. Every
    `save_*` operation in `effective.py` and `repo.py` that takes a
    `version` raises it when `file_version(path) != version`.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_effective.py` passes.
  - [ ] Tests on the sample data: `fernandez-rey-carlos` is `ok` with total `6` and `revised_in == ["01-2026-11-20.csv"]`; `alvarez-lopez-ana` is `ok` with `9`; `martinez-souto-diego` is `np`; `garcia-perez-lucia`, `otero-vidal-sara` and `ramos-gil-irene` are `sin_nota`; `new_revision` on the sample creates `02-<today>.csv`; `save_revision_row` that changes only `ej2` writes a row whose `ej1a`, `ej1b` and `ej3` cells are blank; a stale `version` raises `VersionConflict` and leaves the file unchanged; `copy_to_final(..., "claude", ["garcia-perez-lucia"])` adds the literal line `garcia-perez-lucia,"García Pérez, Lucía",2,2,3,3,10,,claude` to `final.csv`; copying from a `;`-delimited grader sheet holding `7,5` writes `7.5`; copying `alvarez-lopez-ana` from `claude` also copies `notas/claude/alvarez-lopez-ana.md` to `notas/final/alvarez-lopez-ana.md`.

#### T9 — Validation engine

- **Objective:** One function per level that lists every inconsistency of
  Appendix A §Validation, never raising.
- **Files:** `src/correctron/validation.py`, `tests/test_validation.py`.
- **Depends on:** T8
- **Binding interfaces:** `validation.validate_subject(root: Path, subject: str) -> list[Issue]`
  and `validation.validate_exam(root: Path, subject: str, exam: str) -> list[Issue]`.
  `file` in each issue is relative to `root`. Issues are sorted by
  `(file, level != "error", message)`.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_validation.py` passes.
  - [ ] On the sample data: `validate_exam(root, "mecanica-de-vuelo", "parcial-1")` returns exactly one issue, an `aviso` on `mecanica-de-vuelo/parcial-1/alumnos.csv` mentioning `ramos-gil-irene`; `trabajo-1` returns `[]`; `validate_subject` returns `[]`.
  - [ ] After injecting each problem into a copy, there is one test per check listed in Appendix A §Validation, each asserting the level and file of the issue.

#### T10 — Repository façade

- **Objective:** The single API the web uses: discovery, creation and every
  mutation, each one atomic and version-checked.
- **Files:** `src/correctron/repo.py`, `tests/test_repo.py`.
- **Depends on:** T9
- **Binding interfaces:** class `Repository(root: Path)` with these methods
  (all names and paths per Appendix A; a `version` argument is the version
  of the file being modified; a mismatch raises `VersionConflict`; unknown
  subject, exam, student or grader raises `repo.NotFound(KeyError)`; invalid
  input raises `repo.BadRequest(ValueError)`, D28):
  - `ensure_root() -> None`: creates the root if missing and writes
    `LEEME.md` from `correctron/resources/LEEME.md` (via
    `importlib.resources`) if it is missing.
  - `list_subjects() -> list[SubjectInfo]` (`slug`, `nombre`, `curso`,
    `n_students`, `n_exams`); `subject_meta(slug)`;
    `create_subject(nombre, curso) -> str` (folder = `slugify(nombre)`, made
    unique with `-2`…; writes `asignatura.json` and an `alumnos.csv` with
    header only); `update_subject_meta(slug, nombre, curso, codigo, version)`.
  - `students(slug) -> StudentList`;
    `add_student(slug, apellidos, nombre, email, version) -> str` (returns
    the new id); `import_students(slug, text, version) -> tuple[list[str], list[str]]`
    (new ids, errors; writes nothing if errors);
    `update_student(slug, id, apellidos, nombre, email, observaciones, version)`
    (propagates names per D17);
    `remove_student(slug, id, version) -> list[str]` (returns the exam
    folders whose roster still contains the id);
    `exams_containing(slug, id) -> list[str]`.
  - `list_exams(slug) -> list[ExamInfo]` (`slug`, `nombre`, `tipo`, `fecha`,
    `n_roster`, `n_presentados`, `config_ok: bool`), sorted by `fecha` then
    `slug`; `create_exam(slug, nombre, tipo, fecha, copiar_alumnos: bool) -> str` (D25);
    `exam_dir(slug, exam) -> Path`; `exam_config(slug, exam)`
    (returns `load_exam_config` output plus the file version);
    `save_exam_config_json(slug, exam, text: str, version) -> list[Issue]`
    (parses the text; if there are no errors, writes it normalised through
    `save_exam_config(parse_exam_config(...))`, never verbatim; returns the
    issues);
    `orphan_columns(slug, exam) -> list[str]` (columns in any grade sheet,
    final or revision that are neither leaf ids nor reserved and hold at
    least one non-blank cell).
  - `roster(slug, exam) -> Roster`;
    `roster_diff(slug, exam) -> tuple[list[Student], list[RosterEntry]]`
    (in the subject but not in the exam; in the exam but not in the subject);
    `add_to_roster(slug, exam, ids: list[str], version)` (copies names from
    the subject, `presentado` blank);
    `update_roster_entry(slug, exam, id, presentado, observaciones, version)`;
    `remove_from_roster(slug, exam, id, version)`.
  - `graders(slug, exam) -> list[str]`;
    `create_grader(slug, exam, name) -> str` (slugified; rejects `final` and
    existing names with `BadRequest`; writes the header-only sheet);
    `sheet(slug, exam, name) -> GradeSheet` (`name` may be `"final"`);
    `save_grade_row(slug, exam, name, id, raw_cells: dict[str,str], version) -> tuple[str, dict[str,str]]`
    (validates every cell with `validate_cell`; if any fails, returns the
    current version plus the errors and writes nothing; otherwise sets the
    cells, sets `origen=manual` when `name == "final"`, saves, and returns
    the new version plus `{}`);
    `feedback(slug, exam, name, id) -> tuple[str, str]` (text, version);
    `save_feedback(slug, exam, name, id, text, version)` (an empty text
    moves an existing file to the trash).
  - `AREA_RE = re.compile(r"^(enunciado|entregas/[a-z0-9][a-z0-9_-]*/(original|corregido))$")`.
    `list_files(slug, exam, area: str) -> list[FileInfo]` where `area` must
    match `AREA_RE` (otherwise `BadRequest`); `FileInfo(name, rel_path, size, is_pdf)`;
    `save_upload(slug, exam, area, filename, data: bytes) -> str` (area
    checked with `AREA_RE`; sanitised, unique name; returns the relative path);
    `trash_file(slug, exam, rel_path) -> None` (`rel_path` is relative to the
    data root, as in `FileInfo.rel_path`; it must resolve inside the data
    root (`PathOutsideData`) and its parent, relative to the exam folder,
    must match `AREA_RE`, otherwise `BadRequest`, so `config.json` or
    `notas/` can never be trashed this way); `submission_counts(slug, exam) -> dict[str, tuple[int,int]]`
    (id → (#original, #corregido)); `orphan_submission_dirs(slug, exam) -> list[str]`.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_repo.py` passes.
  - [ ] Tests cover: `ensure_root` writes `LEEME.md` once and does not overwrite an edited one; `create_subject("Mecánica de Vuelo", …)` on a root that already has it returns `mecanica-de-vuelo-2`; `add_student` with a homonym returns `…-2`; `import_students` with one bad line writes nothing; `update_student` renaming `garcia-perez-lucia` updates `parcial-1/alumnos.csv` and `trabajo-1/alumnos.csv` but keeps the id; `remove_student("mecanica-de-vuelo","alvarez-lopez-ana", v)` returns `["parcial-1","trabajo-1"]` and leaves `notas/pablo.csv` untouched; `create_exam` creates the D25 tree; `roster_diff` on `parcial-1` returns `([perez-castro-hugo], [ramos-gil-irene])`; `save_grade_row` with `ej1a="5"` returns an error and leaves the file byte-identical; `save_grade_row` on `final` sets `origen=manual`; `save_upload` with name `../../evil.pdf` lands inside the area as `evil.pdf`; a second upload with the same name becomes `evil (2).pdf`; `trash_file` moves into `.papelera`; `trash_file` on `…/parcial-1/config.json` raises `BadRequest`; `list_files` with area `entregas/../notas/original` raises `BadRequest`; each version-checked method raises `VersionConflict` with a stale version.

#### T11 — Web skeleton, file serving and change detection

- **Objective:** A running FastAPI app with layout, vendored assets, safe file
  serving, conflict and error handling, the change banner, and the real CLI.
- **Files:** `src/correctron/web/__init__.py`, `src/correctron/web/app.py`,
  `src/correctron/web/deps.py`, `src/correctron/web/routes_files.py`,
  `src/correctron/web/templates/base.html`,
  `src/correctron/web/templates/_banner.html`,
  `src/correctron/web/templates/_visor.html`,
  `src/correctron/web/static/app.css`, `src/correctron/web/static/app.js`,
  `src/correctron/web/static/vendor/htmx.min.js`,
  `src/correctron/web/static/vendor/alpine.min.js`,
  `src/correctron/web/static/vendor/pico.min.css`,
  `src/correctron/web/templates/_estado_oob.html`,
  `src/correctron/web/templates/_aviso_oob.html`,
  `src/correctron/cli.py` (modify), `tests/conftest.py` (modify),
  `tests/test_web_files.py`.
- **Depends on:** T10
- **Details:**
  - Vendor files are downloaded once and committed:
    `https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js`,
    `https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js` (saved as
    `alpine.min.js`) and `https://unpkg.com/@picocss/pico@2.0.6/css/pico.min.css`.
  - `create_app(data_dir: Path) -> FastAPI`: stores `Repository(data_dir)`
    in `app.state.repo` and calls `ensure_root()`. It mounts `/static`, sets
    up `Jinja2Templates` with filter `nota(value, decimales)` (rounds a
    `Decimal` with `round_grade(value, decimales)`, formats it with
    `format_number` (no trailing zeros) and replaces `.` with `,` for display:
    `Decimal("9.50")` → `9,5`, `Decimal("6")` → `6`; `None` → `"—"`), and
    registers exception handlers: `VersionConflict` → 409, `CsvMalformed` →
    409, `repo.NotFound` → 404, `PathOutsideData` → 404 and `repo.BadRequest`
    → 400 (D28; no handlers for plain `KeyError`/`ValueError`). Each returns a short Spanish HTML message
    (`_banner.html` in error style).
  - `deps.py`: `get_repo(request) -> Repository` and
    `render(request, template, **ctx)`, which adds `repo`, the current path
    and the breadcrumbs.
  - `base.html`: `lang="es"`, Pico + `app.css`, htmx and Alpine (`defer`),
    a header with breadcrumbs (Inicio / Asignatura / Examen), a `#avisos`
    container, and `{% block content %}`.
  - `app.js`: on `htmx:responseError`, inserts the response body into
    `#avisos` (status 409 adds a "Recargar" button that calls
    `location.reload()`). On `keydown` Enter inside an `input` in
    `table.rejilla`, it moves the focus to the same column in the next row.
  - `routes_files.py`:
    - `GET /archivo/{ruta:path}`: resolved with `safe_resolve`. `.pdf`,
      `.png`, `.jpg`, `.jpeg`, `.gif` and `.webp` are served inline with the
      proper type. `.md`, `.csv` and `.txt` are served inline as
      `text/plain; charset=utf-8`. Everything else is sent as an attachment.
      The response always carries `X-Content-Type-Options: nosniff` (D19).
    - `GET /api/huella?ruta=<rel dir>&huella=<current>`: computes
      `tree_fingerprint` of the resolved directory. If it equals `huella`, it
      returns `204`. Otherwise it returns `_banner.html` saying "Hay cambios
      en los archivos hechos fuera de la web." with a "Recargar" button.
    - Page state (D14): every subject or exam page renders
      `<input type="hidden" id="huella-actual" name="huella" value="<fingerprint>">`
      and `<div id="sondeo" hx-get="/api/huella?ruta=<rel dir>"
      hx-include="#huella-actual" hx-trigger="every 3s" hx-swap="outerHTML">`.
      htmx does not swap a 204, so polling continues until the banner
      replaces the div and stops it. The watched directory is the subject
      folder on subject pages and the exam folder on exam pages.
    - `_estado_oob.html(huella, version_id=None, version=None)` renders
      `<input type="hidden" id="huella-actual" name="huella" value="…" hx-swap-oob="true">`
      and, when `version_id` is given,
      `<input type="hidden" id="{{ version_id }}" name="version" value="…" hx-swap-oob="true">`.
      Every htmx mutation response in T12–T18 ends with it, computed
      **after** the write. `deps.estado_oob(request, watched_dir, version_id=None, version=None) -> str`
      renders it.
    - `_aviso_oob.html(nivel, mensaje)` renders
      `<div id="avisos" hx-swap-oob="beforeend"><article class="aviso-{{nivel}}">…</article></div>`.
      It is used for every notice in an htmx response.
  - `_visor.html`: `<iframe src="/archivo/{{ ruta }}" class="visor">` (CSS
    height `80vh`, width 100%) for PDFs, with a download link for other
    files.
  - `cli.main`: resolves the data dir (D12), prints
    `Correctron en http://<host>:<port> — datos: <path>`, opens the browser
    with `webbrowser.open` unless `--no-abrir` (via a 1-second
    `threading.Timer`), and runs `uvicorn.run(create_app(data_dir), host=host, port=port)`.
  - `tests/conftest.py` gains two helpers used by every web test:
    `oob_value(html: str, element_id: str) -> str` (finds the `<input …>`
    tag whose `id` is `element_id`, with any attribute order, and returns
    its `value`) and `row_html(html: str, student_id: str) -> str` (returns
    the `<tr id="fila-<student_id>" …>…</tr>` fragment; it fails the test if
    it is missing). Every table row that shows a student, in every template,
    has `id="fila-<id>"`.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_web_files.py` passes, using `fastapi.testclient.TestClient(create_app(sample_data))`.
  - [ ] Tests: `GET /archivo/mecanica-de-vuelo/parcial-1/enunciado/enunciado.pdf` → 200, `content-type: application/pdf`, no `attachment` in `content-disposition`; an uploaded `x.html` → `content-disposition` contains `attachment`; `/archivo/%2e%2e/%2e%2e/etc/passwd` → 404; a symlink created inside the data root pointing at a file outside it → 404 (this is the case that actually reaches `safe_resolve`, because httpx normalises a plain `../..`); `GET /archivo/…/notas/claude/alvarez-lopez-ana.md` → `text/plain; charset=utf-8`, inline; `/api/huella` with the current fingerprint → 204, and after modifying a file → 200 containing `Recargar`; `GET /static/vendor/htmx.min.js` → 200.
  - [ ] `uv run correctron --data /tmp/claude-ct-test --no-abrir --port 8799` (run in background) creates `/tmp/claude-ct-test/LEEME.md`, and `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8799/static/app.css` prints `200`. Stop the server and delete the folder afterwards.

#### T12 — Home and subject pages

- **Objective:** List and create subjects. Manage a subject's metadata,
  students (add, inline edit, remove, bulk import) and exams (list, create).
- **Files:** `src/correctron/web/routes_home.py`,
  `src/correctron/web/routes_subject.py`,
  `src/correctron/web/templates/index.html`,
  `src/correctron/web/templates/asignatura.html`,
  `src/correctron/web/templates/_fila_alumno.html`,
  `src/correctron/web/app.py` (register routers), `tests/test_web_subject.py`.
- **Depends on:** T11
- **Details (routes):**
  - `GET /`: a table of subjects (name, year, #students, #exams, link) and a
    form "Nueva asignatura" (`nombre` required, `curso`) posting to
    `POST /asignaturas` → 303 redirect to `/a/{slug}`.
  - `GET /a/{s}?tab=alumnos|examenes|datos|problemas` (default `alumnos`).
    Tabs are links. Each tab is rendered server-side, and the fingerprint
    poll watches the whole subject folder.
    - `alumnos`: everything sits inside `<div id="panel-alumnos">`, which
      holds `<input type="hidden" id="version-lista" name="version">`, the
      table `rejilla` (one `_fila_alumno.html` per student, `id="fila-<id>"`),
      the add form and the import `<details>` (D26).
      - Row edits: inputs for apellidos, nombre, email and observaciones
        (ids `c-<id>-<campo>`) with `hx-post="/a/{s}/alumnos/{id}"
        hx-trigger="change" hx-include="closest tr, #version-lista"
        hx-swap="none"`. The response holds only `_estado_oob` (new
        `version-lista` and huella), plus an `_aviso_oob` error if
        apellidos/nombre were blank (nothing written then).
      - Structural actions are htmx forms with
        `hx-include="#version-lista" hx-target="#panel-alumnos"
        hx-swap="outerHTML"`. The response is the re-rendered panel (which
        carries the new version) plus `_estado_oob` (huella only) and any
        `_aviso_oob`:
        - add: `POST /a/{s}/alumnos`;
        - import: a textarea `texto` posting to `POST /a/{s}/importar-alumnos`
          (D27); the notice says the number imported or lists the per-line
          errors;
        - remove: "Quitar" posting to `POST /a/{s}/alumnos/{id}/borrar` with
          `hx-confirm` "¿Quitar a <nombre> de la asignatura? Sus notas y
          entregas no se borran."; if the student is still in exam rosters,
          an info notice lists those exams.
    - `examenes`: a table from `list_exams` (name, type, date, roster size,
      presentados, a ⚠ if `config_ok` is false, link) and a form "Nuevo
      examen o trabajo" (`nombre`, `tipo` select examen/trabajo, `fecha`
      date input, `copiar_alumnos` checkbox checked) posting to
      `POST /a/{s}/examenes` → 303 to `/a/{s}/e/{exam}?tab=config`.
    - `datos`: a form for `nombre`, `curso` and `codigo` posting to
      `POST /a/{s}/datos`.
    - `problemas`: `validate_subject` issues, plus one line per exam with
      its error and warning counts linking to that exam's `resumen` tab.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_web_subject.py` passes.
  - [ ] Tests: `GET /` lists "Mecánica de Vuelo"; `POST /asignaturas` with `nombre=Física` → 303 to `/a/fisica`, and `data/fisica/asignatura.json` exists; `POST /a/mecanica-de-vuelo/alumnos` adds a row to `alumnos.csv`; the same post with a stale `version` → 409 with the file unchanged; the import (`POST /a/mecanica-de-vuelo/importar-alumnos`) with two good lines adds two students; the import with a bad line → the response contains `Línea` and the file is unchanged; editing a row then adding a student with `oob_value(resp, "version-lista")` from the edit response succeeds (no 409); after editing a row, `GET /api/huella?ruta=mecanica-de-vuelo&huella=<oob_value(resp,"huella-actual")>` → 204; removing `alvarez-lopez-ana` returns a panel in which `row_html` finds the other five students, plus a notice naming `parcial-1`; `POST …/alumnos/garcia-perez-lucia` with a new `nombre` updates both exam rosters; `POST /a/mecanica-de-vuelo/examenes` creates the folder and redirects to `?tab=config`; `GET /a/mecanica-de-vuelo?tab=problemas` → 200 and contains `parcial-1`.

#### T13 — Exam page shell: summary and roster tabs

- **Objective:** The exam page with its tab bar, a summary showing the
  effective grades and the problems, and full roster management including
  *presentado*.
- **Files:** `src/correctron/web/routes_exam.py`,
  `src/correctron/web/templates/examen.html`,
  `src/correctron/web/templates/examen_resumen.html`,
  `src/correctron/web/templates/examen_alumnos.html`,
  `src/correctron/web/templates/_fila_roster.html`,
  `src/correctron/web/app.py` (register router), `tests/test_web_exam.py`.
- **Depends on:** T12
- **Details:**
  - `GET /a/{s}/e/{e}?tab=<t>` where `t` ∈ `resumen` (default), `alumnos`,
    `config`, `enunciado`, `notas`, `comparar`, `entregas` and `revisiones`.
    `examen.html` renders the header (name, type, date, `nota_maxima`), the
    tab links, the fingerprint poll over the exam folder, and includes
    `examen_<t>.html`. Tabs T14–T18 add their templates. Until then, a
    missing tab template renders "Próximamente". If the config is invalid,
    every tab except `resumen`, `alumnos`, `config`, `enunciado` and
    `entregas` shows "Corrige config.json para continuar" with a link to
    `?tab=config`.
  - `resumen`: counts (roster, presentados, no presentados, sin marcar,
    rows per grader sheet, final rows, number of revisions); a "Notas
    vigentes" table from `effective_grades` (alumno, presentado, nota
    vigente formatted with `nota` or `NP`/`Sin nota`/`Incompleta (parcial
    X)`, and a "revisada" marker linking to `?tab=revisiones&rev=<file>`);
    and the `validate_exam` issues (errors first, red; avisos amber).
  - `alumnos`: same pattern as T12 (D26): `<div id="panel-roster">` holds
    `#version-lista`, the roster table `rejilla` and both side panels. Each
    row has a 3-state `presentado` select (`""` "Sin marcar", `si`
    "Presentado", `no` "No presentado") and an `observaciones` input posting
    to `POST /a/{s}/e/{e}/alumnos/{id}` with `hx-swap="none"` (response:
    `_estado_oob` only), and "Quitar" (`hx-confirm`) posting to
    `POST /a/{s}/e/{e}/alumnos/{id}/borrar`, which re-renders the panel. A raw `presentado` value that does not parse is shown as an
    extra selected option marked "(no válido: X)". A side panel "En la
    asignatura pero no en el examen" has checkboxes, an "Añadir
    seleccionados" button and an "Añadir todos" button
    (`POST /a/{s}/e/{e}/alumnos` with `ids` repeated, or `todos=1`; re-renders
    the panel). A panel "En el examen pero no en la asignatura" lists those
    entries with a warning style. A "Marcar todos los sin marcar como
    presentados" button posts to `POST /a/{s}/e/{e}/marcar-presentados`
    (D27) and re-renders the panel. All structural forms use
    `hx-include="#version-lista" hx-target="#panel-roster" hx-swap="outerHTML"`.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_web_exam.py` passes.
  - [ ] Tests: `GET …/e/parcial-1` → 200; `row_html(resp, "martinez-souto-diego")` contains `NP`, `row_html(resp, "fernandez-rey-carlos")` contains `6` and the revised marker, and the page contains the `ramos-gil-irene` warning; `GET …?tab=alumnos` lists `perez-castro-hugo` in the "no en el examen" panel; posting `presentado=no` for `alvarez-lopez-ana` writes `no` in the roster CSV; `POST …/alumnos` with `todos=1` adds `perez-castro-hugo` with blank `presentado`; `POST …/marcar-presentados` turns every blank `presentado` into `si`; setting `presentado` on a row then posting "Añadir todos" with the version returned by the first response succeeds; an exam whose `config.json` is broken JSON still renders `resumen` (200) with the JSON error listed.

#### T14 — Exam configuration tab

- **Objective:** Edit the exam metadata and the two-level criteria from the
  web, plus a raw JSON mode that also works when the file is broken.
- **Files:** `src/correctron/web/templates/examen_config.html`,
  `src/correctron/web/static/criterios.js`,
  `src/correctron/web/routes_exam.py` (modify), `tests/test_web_config.py`.
- **Depends on:** T13
- **Details:**
  - With a valid config, the page renders
    `<script type="application/json" id="config-datos">{{ exam_config_to_dict(cfg)|tojson }}</script>`
    (never JSON inside an attribute), and an Alpine component
    `x-data="editorCriterios()"`, defined in `criterios.js` and loaded
    before Alpine, that reads its initial state with
    `JSON.parse(document.getElementById("config-datos").textContent)`. It
    has:
    - fields `nombre`, `tipo`, `fecha`, `nota_maxima`, `decimales` and
      `calculo_total` (select with an explanation of each mode);
    - a criteria list where each top-level item has `id`, `nombre`,
      `maximo` (hidden when it has subcriteria), `peso` (shown only in
      `ponderada`), buttons ↑ ↓ ✕, and "Añadir subapartado" (which turns it
      into a group). Each subcriterion has `id`, `nombre`, `maximo` and
      ↑ ↓ ✕. There is an "Añadir criterio" button;
    - a live line "Suma de máximos: X / nota máxima Y" (amber when they
      differ in `suma`).
    On submit, the component serialises the full config (keeping `extra`
    keys) into a hidden `config_json` field and posts it with `version` to
    `POST /a/{s}/e/{e}/config`.
  - A `<details>` "Editar JSON directamente" holds a textarea named
    `config_json` with the exact file text, posting to the same route with
    `version`. Both editors post the same field `config_json`. The server
    always writes the result normalised (T10), so hand formatting from the
    raw editor is not kept. When the config is invalid or
    missing, only this raw editor is shown, opened, with the errors above
    it.
  - The route calls `save_exam_config_json`. With errors it re-renders the
    tab with the errors and the submitted text (nothing written). On
    success it redirects 303 to `?tab=config` with a "Guardado" notice
    (`&ok=1`). The config tab GET always shows the current config's
    *avisos* and, computed on each GET with `orphan_columns`, an aviso "Las
    columnas X siguen en los CSV de notas y se conservan como columnas
    desconocidas" when that list is non-empty. The data stays (Appendix A).
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_web_config.py` passes.
  - [ ] Tests: posting a valid modified config JSON (adding leaf `ej4` with `maximo` 1) writes `config.json` with `ej4` and redirects 303; posting a config with a duplicate id → 200 with the error text and the file byte-identical; posting with a stale version → 409; with `config.json` replaced by `{` the tab renders the raw editor (contains `<textarea`) and the JSON error; removing `ej3` from the config while `pablo.csv` has `ej3` values and following the redirect shows the aviso naming `ej3`, and `pablo.csv` still has the `ej3` column after a later `save_grade_row`.
  - [ ] Manual check in a browser (sample data): add a group with two subcriteria, reorder, switch to `ponderada` and see the `peso` fields, save, and confirm `config.json` matches the screen.

#### T15 — Statement and submissions tabs (uploads and PDF viewer)

- **Objective:** Upload, list, view and delete files in `enunciado/` and in
  each student's `original/` and `corregido/`.
- **Files:** `src/correctron/web/templates/examen_enunciado.html`,
  `src/correctron/web/templates/examen_entregas.html`,
  `src/correctron/web/templates/_lista_archivos.html`,
  `src/correctron/web/routes_files.py` (modify),
  `src/correctron/web/routes_exam.py` (modify), `tests/test_web_uploads.py`.
- **Depends on:** T13
- **Details:**
  - `_lista_archivos.html(area, files, selected)`: the file list (name,
    size, "Ver" link setting `&archivo=<rel>`, "Descargar" link to
    `/archivo/<rel>`, and "Borrar", which posts to
    `POST /a/{s}/e/{e}/borrar-archivo` with `ruta` and an `hx-confirm`
    saying it goes to the trash), plus an upload form
    (`POST /a/{s}/e/{e}/subir`, `enctype=multipart/form-data`, `destino` =
    area, `archivos` multiple). Uploads redirect 303 back to the same tab
    and student.
  - `enunciado`: the list on the left (`grid` layout) and `_visor.html` on
    the right for `archivo` (default: the first PDF).
  - `entregas`: a student table (alumno, presentado, #original,
    #corregido, link `&alumno=<id>`), with absent students greyed out. With
    `alumno` set, two sub-tabs "Original" and "Corregido" (`&parte=original|corregido`)
    show `_lista_archivos` plus `_visor`, and "← anterior / siguiente →"
    links walk the roster order. Orphan folders (`orphan_submission_dirs`)
    are listed as warnings.
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_web_uploads.py` passes.
  - [ ] Tests: uploading two files to `enunciado` stores both and redirects; uploading to `entregas/perez-castro-hugo/original` creates that folder; `destino=../../x` → 400 (`list_files`/`save_upload` raise `BadRequest` for any area not matching `AREA_RE`, mapped to 400 in T11); `borrar-archivo` with `ruta=../../../etc/passwd` → 404 (`PathOutsideData`); `borrar-archivo` moves the file into `.papelera`; `borrar-archivo` with `ruta=mecanica-de-vuelo/parcial-1/config.json` → 400 and the file stays; `GET …?tab=entregas&alumno=alvarez-lopez-ana&parte=corregido` contains an `<iframe` pointing at `examen-corregido.pdf`.
  - [ ] Manual check: the sample `enunciado.pdf` displays inside the page in Firefox or Chrome.

#### T16 — Grades tab (grid per grader and feedback)

- **Objective:** Enter and edit grades per grader or in `final`, with the
  breakdown, live totals and feedback, saving each row immediately.
- **Files:** `src/correctron/web/routes_grades.py`,
  `src/correctron/web/templates/examen_notas.html`,
  `src/correctron/web/templates/_fila_notas.html`,
  `src/correctron/web/templates/_feedback.html`,
  `src/correctron/web/app.py` (register router), `tests/test_web_grades.py`.
- **Depends on:** T13
- **Details:**
  - The tab top has a selector of sheets: buttons for each grader in
    `graders()`, then `final` (highlighted), plus a form "Nuevo corrector"
    (`POST /a/{s}/e/{e}/correctores`, `nombre`) → 303 to
    `?tab=notas&corrector=<name>`. Default sheet: `final` if it exists,
    else the first grader, else only the form.
  - The grid (`table.rejilla`, horizontally scrollable wrapper, sticky first
    column) has a two-row header: groups span their leaves (top row), and
    each leaf shows `id` with `/maximo` (bottom row). Columns: alumno,
    presentado chip, one input per leaf, the group subtotal after the last
    leaf of each group (read-only), total (an input in manual mode,
    read-only otherwise; showing `partial` in grey with "parcial" when
    incomplete), comentario (input), and feedback (a "📝" button, filled
    style when the `.md` exists). For `final`, it also shows `origen`.
  - Rows: every roster entry in roster order. `presentado == "no"` rows are
    rendered disabled with "NP". Below them, a section "Fuera de la lista"
    shows read-only the sheet rows whose id is not in the roster.
  - Saving (D26): every input has a stable id `c-<id>-<col>`; computed cells
    have ids `sub-<id>-<grupo>`, `total-<id>` and (final) `origen-<id>`, and
    each row has an error slot `err-<id>`. Each row's inputs use
    `hx-post="/a/{s}/e/{e}/notas/{name}/{id}"` `hx-trigger="change"`
    `hx-include="closest tr, #version-hoja"` `hx-swap="none"`, and the
    table has `hx-sync="this:queue all"`.
    - On success, the response holds only out-of-band swaps: the group
      subtotals, `total-<id>`, `origen-<id>` (final), an empty `err-<id>`,
      and `_estado_oob(version_id="version-hoja")`. The inputs are never
      replaced, so typing in the next cell is not lost. `app.js` removes
      `aria-invalid` from the row's inputs after a successful request.
    - On a validation error (from `save_grade_row`), the response sets the
      headers `HX-Retarget: #fila-<id>` and `HX-Reswap: outerHTML` and
      returns the full row re-rendered with the submitted values, with
      `aria-invalid="true"` on bad inputs and the messages in `err-<id>`.
      The old version is kept and nothing is written.
    - Cells holding unparsable file values render the raw value with
      `aria-invalid="true"`.
  - Feedback: the 📝 button `hx-get`s
    `/a/{s}/e/{e}/notas/{name}/{id}/feedback` into a `<dialog id="feedback">`
    showing a textarea (monospace, 20 rows) and a hidden version. Saving
    `hx-post`s to the same URL and closes the dialog; the row's 📝 state
    updates through an out-of-band swap of the button.
  - When `name == "final"` and revisions exist, a notice says "Hay
    revisiones posteriores; la nota vigente puede diferir (ver
    Revisiones)".
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_web_grades.py` passes.
  - [ ] Tests: `GET …?tab=notas&corrector=pablo` contains the group header `ej1` and the subtotal `3,5` for Ana; posting `ej2=3`, `ej3=2,5` for `garcia-perez-lucia` to `pablo` with the right version → 200, the response contains an out-of-band `total-garcia-perez-lucia` with `9,5`, contains no `<input id="c-garcia-perez-lucia-ej2"`, and `pablo.csv` row `garcia-perez-lucia,"García Pérez, Lucía",2,2,3,2.5,9.5,`; posting `ej2=7` → 200 with header `HX-Retarget: #fila-garcia-perez-lucia`, a row containing `aria-invalid`, and `pablo.csv` byte-identical; two consecutive posts, each using `oob_value(prev, "version-hoja")`, both succeed; a stale version → 409; `POST …/correctores` with `nombre=Claude Opus` creates `notas/claude-opus.csv` with the canonical header; `nombre=final` → 400 (`BadRequest`); saving feedback for `pablo/alvarez-lopez-ana` creates `notas/pablo/alvarez-lopez-ana.md`; posting a row to `final` sets `origen` to `manual`; a sheet row for an id not in the roster appears under "Fuera de la lista".
  - [ ] Manual check: typing grades with Tab/Enter navigation updates totals without reloading the page.

#### T17 — Compare tab and building final.csv

- **Objective:** See all graders side by side, spot discrepancies, and fill
  `final.csv` per student or in bulk.
- **Files:** `src/correctron/web/templates/examen_comparar.html`,
  `src/correctron/web/routes_grades.py` (modify), `tests/test_web_compare.py`.
- **Depends on:** T16
- **Details:**
  - The main table has one row per roster entry (NP greyed) with columns:
    alumno, the total per grader (blank when missing, `parcial` style when
    incomplete), final total + `origen`, and Δ = max − min of the **complete** grader
    totals (`GradeResult.total is not None`; partial totals never count; Δ
    is blank when fewer than two complete totals exist), strong red when
    ≥ 10 % of `nota_maxima` (D22). Actions per
    grader: "Usar <grader>"
    (`POST /a/{s}/e/{e}/final/{id}/usar`, `corrector=<g>`, with
    `hx-confirm` when the student already has a final row; it re-renders
    the row).
  - Each row has a `<details>` holding a per-leaf table: rows = leaves
    (grouped), columns = graders + final, discrepant cells highlighted
    (D22), and the `comentario` of each grader with a link to their
    feedback `.md` (opens `/archivo/...` in a new tab).
  - Bulk form: "Copiar <grader ▼> a final para los alumnos sin nota final"
    (`POST /a/{s}/e/{e}/final/copiar`, `corrector`) → 303 back with a notice
    "N filas copiadas". Only presentado ≠ `no` students without a final row
    are copied.
  - Filter links: "Todos" and "Solo discrepancias" (`&filtro=discrepancias`:
    rows with any discrepant leaf or a strong Δ).
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_web_compare.py` passes.
  - [ ] Tests: `GET …?tab=comparar`: `row_html(resp, "alvarez-lopez-ana")` contains `9` (pablo), `8,5` (claude) and Δ `0,5` without the strong class; Lucía's row has a blank Δ; `filtro=discrepancias` includes Ana (ej2 differs) and Carlos, and excludes Lucía (pablo is incomplete: blank cells are ignored, and ej1a/ej1b agree); `POST …/final/garcia-perez-lucia/usar` with `corrector=claude` adds her to `final.csv` with `origen=claude`; after appending a row for `martinez-souto-diego` to the copied `claude.csv`, bulk copy from `claude` adds `garcia-perez-lucia` and `otero-vidal-sara` (not Diego, who is NP, nor the existing rows) and reports `2`.

#### T18 — Revisions tab

- **Objective:** Create revision sessions and revise individual grades with
  a reason, keeping the history visible.
- **Files:** `src/correctron/web/templates/examen_revisiones.html`,
  `src/correctron/web/templates/_form_revision.html`,
  `src/correctron/web/routes_grades.py` (modify),
  `tests/test_web_revisions.py`.
- **Depends on:** T16
- **Details:**
  - The left column lists the revision files, newest first, each linking
    to `&rev=<file>` (default: newest). There is a button "Nueva sesión de
    revisión" (`POST /a/{s}/e/{e}/revisiones` → `new_revision(today)` →
    303 to `&rev=<new>`).
  - The selected revision shows a table, one row per student in the file:
    alumno, the changes as `ej1b: 1 → 1,5` (from `grade_before(revision)`
    to the merged value), total `5,5 → 6`, motivo, and an "Editar" button.
  - Form `_form_revision.html`: a student select (presentado ≠ `no`; the
    selected one comes from `&alumno=`), inputs for each leaf prefilled with
    the value after merging this revision's row onto `grade_before`, a total
    input in manual mode, `motivo` (required), and the hidden version.
    `POST /a/{s}/e/{e}/revisiones/{rev}/{id}` validates each cell with
    `validate_cell` (errors re-render the form, nothing written) and then
    calls `save_revision_row` → 303 back to `&rev=<rev>`.
  - A note under the list: "La nota vigente = final.csv + revisiones en
    orden. Puedes editar estos CSV a mano."
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_web_revisions.py` passes.
  - [ ] Tests: `row_html(resp, "fernandez-rey-carlos")` shows `ej1b: 1 → 1,5` and `5,5 → 6` in `01-2026-11-20.csv`; `POST …/revisiones` creates `02-<today>.csv` and redirects; revising Ana in it with `ej2=2,5` and motivo `Recontado` writes a row with only `ej2=2.5`, `total=8.5`, motivo; the `resumen` tab then shows `8,5` in `row_html(resp, "alvarez-lopez-ana")`; a blank motivo → 200 with an error and nothing written; `ej2=9` → error, nothing written.

#### T19 — README, end-to-end check and polish

- **Objective:** The user can install, run and understand the tool, and the
  whole flow is verified in a real browser.
- **Files:** `README.md`, `src/correctron/web/static/app.css` (polish only),
  `tests/test_e2e_flow.py`.
- **Depends on:** T14, T15, T17, T18
- **Details:** The README (Spanish) covers: what it is; install
  (`uv sync`); run (`uv run correctron`, `--data`, `CORRECTRON_DATA`); try
  it with `cp -r ejemplo/data /tmp/correctron-demo && uv run correctron --data /tmp/correctron-demo`
  (never run it directly on `ejemplo/data`: the tests depend on those exact
  files); the folder structure (a
  short version plus a link to `src/correctron/resources/LEEME.md`); how to
  use an LLM as a grader (point it at `data/LEEME.md`, section
  "Instrucciones para un corrector LLM"); safety notes (local only, `data/`
  git-ignored, trash folder); tests and lint. `test_e2e_flow.py` drives the
  whole flow through `TestClient` on an empty tmp root, threading the
  versions returned by each response (`oob_value`, or a fresh GET after a
  redirect):
  1. Create subject `Prueba` (→ `prueba`).
  2. Import `Gómez Ruiz, Marta` / `López Díaz, Pedro` / `Sanz Mora, Julia`.
  3. Create exam `Examen final` (`examen`, `2027-01-20`, copying students;
     → `examen-final`).
  4. Set presentado: Marta `si`, Pedro `si`, Julia `no`.
  5. Post config `suma`, `nota_maxima` 10, criteria `p1` group (`p1a` max 3,
     `p1b` max 2), `p2` max 5.
  6. Create grader `pablo`. Marta: `p1a=3`, `p1b=1,5`, `p2=4`. Pedro:
     `p1a=2`, `p1b=2`, `p2=2,5`.
  7. Write `notas/llm.csv` directly to disk:
     `id;alumno;p1a;p1b;p2;total;comentario` /
     `gomez-ruiz-marta;Gómez Ruiz, Marta;3;2;4;9;Bien` /
     `lopez-diaz-pedro;López Díaz, Pedro;2;1,5;2,5;6;`.
  8. In the compare tab, Marta's row shows `8,5` and `9`.
  9. Bulk copy `pablo` to final (reports 2), then "Usar llm" for Marta.
  10. Create a revision and revise Pedro with `p2=3`, motivo `Recontado`.
  11. Assert `resumen`: Marta `9`, Pedro `7` with the revised marker, Julia
      `NP`.
  12. Assert the files byte for byte. `notas/final.csv`:
      ```
      id,alumno,p1a,p1b,p2,total,comentario,origen
      gomez-ruiz-marta,"Gómez Ruiz, Marta",3,2,4,9,Bien,llm
      lopez-diaz-pedro,"López Díaz, Pedro",2,2,2.5,6.5,,pablo
      ```
      The revision file (`revisiones/01-<today>.csv`):
      ```
      id,alumno,p1a,p1b,p2,total,motivo
      lopez-diaz-pedro,"López Díaz, Pedro",,,3,7,Recontado
      ```
  13. `llm.csv` is untouched (still `;`-delimited with `1,5`).
- **Acceptance criteria:**
  - [ ] `uv run pytest` (whole suite) passes and `uv run ruff check && uv run ruff format --check` exit 0.
  - [ ] `tests/test_e2e_flow.py` passes and asserts the file contents described above.
  - [ ] The manual scenario in *Verification* is executed and its result is written in *Implementation*.

### Execution

Mode: single agent

The tasks form a mostly linear chain (each layer builds on the previous one).
After T13, T14–T18 touch different templates but share `routes_exam.py`,
`routes_grades.py` and `app.py`, so they are not disjoint packages. One agent
keeps the data format and the naming consistent across the 19 tasks.
Recommended order: T1 → T19 as numbered.

### Verification

1. `uv run pytest` passes completely. `uv run ruff check` and
   `uv run ruff format --check` exit 0.
2. Manual scenario (record the result in *Implementation*):
   1. `cp -r ejemplo/data /tmp/ct-manual && uv run correctron --data /tmp/ct-manual`.
      The browser opens on the subject list.
   2. In "Mecánica de Vuelo", add a student, rename one, and import two
      lines. Check `alumnos.csv` in a text editor.
   3. In `parcial-1` → Alumnos, add Hugo and mark presentados.
   4. Config: add `ej4` (max 1) and save. Open `config.json` and check it.
   5. Enunciado: the PDF displays. Upload another PDF and delete it; it
      appears in `.papelera/`.
   6. Notas → pablo: complete Lucía. The total updates without reloading.
      Write long feedback.
   7. **External edit:** with the page open, edit `notas/pablo.csv` in an
      editor (change one of Ana's grades). Within ~3 s the banner appears.
      Edit a cell in the web before reloading: a 409 notice with "Recargar"
      appears and the external edit is not lost.
   8. **LLM file:** create `notas/llm.csv` by hand with `;` and decimal
      commas. It appears as a grader and in Comparar.
   9. Comparar: use claude for Lucía; bulk copy. Revisiones: new session,
      revise Ana. Resumen shows the new effective grade with the "revisada"
      marker.
   10. Entregas: upload an original and a corrected PDF for Hugo and view
       both.
3. `git status` shows no files under `data/`.

### Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| The user saves a CSV in an editor while the web writes the same file. | Lost edit. | Version tokens on every write (409), fingerprint banner, atomic `os.replace`. Accepted residual: a write in the same millisecond window. |
| Excel re-saves CSVs with `;`, a BOM or cp1252. | Parsing failures. | Tolerant reader (header-count delimiter detection, BOM, cp1252 fallback, `7,5`); delimiter, encoding and BOM kept on rewrite. |
| Malformed rows from hand edits. | Data corruption on rewrite. | `Table.malformed` blocks writes (409 with the line numbers); the page stays readable. |
| Real student data committed to git. | GDPR breach. | `data/` git-ignored from T1; sample data is fictional; README warns. |
| Uploaded HTML/SVG executes in the app origin. | XSS on localhost. | Non-PDF/image files served as attachments with `nosniff` (D19); SVG is not in the inline list. |
| Renaming a criterion id orphans CSV columns. | Grades appear lost. | Unknown columns kept; the config tab and validation warn. |
| Scope (19 tasks) causes fatigue or drift in the implementer. | Inconsistent names or half-features. | Binding interfaces in this plan; each task leaves the suite green; the e2e test in T19. |
| Dependency wheels on Python 3.14. | Install failure. | `requires-python >=3.12`; if `uv sync` fails on 3.14, pin `.python-version` to 3.12/3.13 (uv downloads it). |
| htmx swaps lose keystrokes or break on table fragments. | Grades typed in the wrong place or lost. | D26: inline edits use `hx-swap="none"` + out-of-band computed cells; structural changes swap whole `<div>` panels. |
| Browser PDF viewer differences. | PDF not shown inline. | Native `<iframe>` works in Firefox and Chrome; a download link is always present. |

### Open questions

## Appendix A — Data format specification (canonical)

### Layout

```
<data root>/
├── LEEME.md                         written if missing (copy of resources/LEEME.md)
├── .papelera/<YYYYMMDD-HHMMSS>/…    deleted uploads (hidden)
└── <asignatura>/                    any non-hidden directory = a subject
    ├── asignatura.json              optional
    ├── alumnos.csv
    └── <examen>/                    a subdirectory containing config.json = an exam
        ├── config.json
        ├── alumnos.csv              the exam roster
        ├── enunciado/               any files (statement, rubric, solutions…)
        ├── entregas/<id>/original/  the student's original submission (any files)
        ├── entregas/<id>/corregido/ the corrected version (any files)
        ├── notas/<corrector>.csv    one sheet per grader
        ├── notas/<corrector>/<id>.md  optional long feedback
        ├── notas/final.csv          official grades
        ├── notas/final/<id>.md      optional official feedback
        └── revisiones/NN-YYYY-MM-DD.csv
```

Hidden means the name starts with `.` or `_`. Folder names created by the web
are `slugify(nombre)`, made unique with `-2`, `-3`…

### Common CSV rules

UTF-8, header row, comma delimiter, dot decimals (D9). The reader is tolerant
(`;`, tab, BOM, cp1252, `7,5`), and a rewrite keeps the file's delimiter,
encoding and BOM. A value copied from one file to another is canonicalised
(D23). Header names are case-insensitive and
written lowercase. Columns not listed below are kept as they are. Blank rows
are ignored. `id` is the key in every CSV.

### asignatura.json

```json
{ "nombre": "Mecánica de Vuelo", "curso": "2026-2027", "codigo": "" }
```

All keys are optional. `nombre` defaults to the folder name. Unknown keys are
kept.

### alumnos.csv (subject)

Columns: `id,apellidos,nombre,email,observaciones`. Required: `id`,
`apellidos`, `nombre`. `id` per D2 (`[a-z0-9]+(-[a-z0-9]+)*`). Ids that do not
match are an *aviso*, not an error, because the user may hand-write other ids.

### config.json (exam)

```json
{
  "nombre": "Primer parcial",
  "tipo": "examen",
  "fecha": "2026-11-03",
  "nota_maxima": 10,
  "decimales": 2,
  "calculo_total": "suma",
  "criterios": [
    { "id": "ej1", "nombre": "Ejercicio 1", "peso": 1, "subcriterios": [
        { "id": "ej1a", "nombre": "Apartado a", "maximo": 2 },
        { "id": "ej1b", "nombre": "Apartado b", "maximo": 2 } ] },
    { "id": "ej2", "nombre": "Ejercicio 2", "maximo": 3, "peso": 1 },
    { "id": "ej3", "nombre": "Ejercicio 3", "maximo": 3, "peso": 1 }
  ]
}
```

Rules:

- `nombre`: string, default the folder name.
- `tipo`: `examen` | `trabajo`, default `examen`.
- `fecha`: `YYYY-MM-DD` or `""`.
- `nota_maxima`: number > 0, default 10.
- `decimales`: integer 0–4, default 2.
- `calculo_total`: `suma` | `ponderada` | `manual`, default `suma`.
- `criterios`: list, default `[]`. Each top-level item has `id` and `nombre`
  (default = `id`), plus either `maximo` (> 0; a leaf) or `subcriterios` (a
  non-empty list of leaves `{id, nombre, maximo}`; a group), never both and
  never neither. `peso` (≥ 0, default 1) is only allowed on top-level items
  and only used in `ponderada`.
- Every `id` (all levels) matches `^[a-z0-9][a-z0-9_]*$`, is unique, and is
  not in `RESERVED_COLUMNS`.
- Unknown top-level keys are kept. Unknown keys inside criteria are an
  *aviso* and are dropped on save.
- *Aviso*: `suma` with non-empty `criterios` and the sum of leaf `maximo` ≠ `nota_maxima`.
  *Error*: `ponderada` with the sum of `peso` = 0.

### Total computation

Leaves are the CSV columns, in config order. Each leaf value must lie in
`[0, maximo]`.

- `suma`: total = sum of the leaves. No scaling.
- `ponderada`: for each top-level item `i`, `frac_i = value/maximo` for a
  leaf or `Σ group leaves / Σ group maximo` for a group;
  total = `nota_maxima · Σ(peso_i · frac_i) / Σ peso_i`.
- `manual` (or no criteria): total = the `total` cell, in `[0, nota_maxima]`.
  Leaves are informative.
- Complete = every leaf is non-blank and valid (computed modes) or `total`
  is valid (manual). Incomplete means total = none. In `suma`,
  `partial` = the sum of the valid filled leaves.
- Group subtotal = the sum of its leaves (none if any is blank). It is
  displayed, never stored.
- Rounding: `round_grade(total, decimales)` with `ROUND_HALF_UP`.
  Written without trailing zeros.

### alumnos.csv (exam roster)

Columns: `id,apellidos,nombre,presentado,observaciones`. `presentado`
canonical values `si` | `no` | `""` (not marked). The tolerant values are
listed in T6. Names are copies of the subject list for readability (D17
keeps them in sync).

### notas/<corrector>.csv

Columns: `id,alumno,<leaf ids in config order>,total,comentario`. `alumno` =
`Apellidos, Nombre`, informative and ignored on read. One row per student
graded. A blank cell means not graded. In computed modes `total` is written
by the web for readability; if a file's `total` disagrees with the computed
one, it is an *aviso* and the computed value wins. `<corrector>` matches
D20, and `final` is reserved. Long feedback goes in
`notas/<corrector>/<id>.md` (free Markdown).

Example:

```csv
id,alumno,ej1a,ej1b,ej2,ej3,total,comentario
alvarez-lopez-ana,"Álvarez López, Ana",2,1.5,3,2.5,9,Muy bien
```

### notas/final.csv

Same as a grader sheet, plus `origen` (grader name or `manual`) after
`comentario`. It is the official grade before revisions.

### revisiones/NN-YYYY-MM-DD.csv

Columns: `id,alumno,<leaf ids>,total,motivo`. `NN` = two digits from `01`.
Only revised students appear. A non-blank leaf cell is the new value; a blank
one is unchanged. `total`: manual mode = the new total (blank = unchanged);
computed modes = informative (recomputed). `motivo` is free text and should
not be blank.

Effective grade per roster entry: `presentado = no` gives NP. Otherwise take
the `final.csv` row, apply the revisions in file-name order, and compute.
With no row anywhere, the status is "sin nota".

### Validation

Each check gives an issue with its level. These are the checks T9 must
implement and test:

| Level | File | Check |
| --- | --- | --- |
| error | asignatura.json | invalid JSON or not an object |
| error | subject alumnos.csv | missing required column; duplicate id; blank id; malformed row |
| aviso | subject alumnos.csv | id not matching the slug pattern |
| error | config.json | any rule of §config.json (invalid JSON, types, ids, structure) |
| aviso | config.json | sum of maxima ≠ nota_maxima in `suma` (only with non-empty `criterios`); unknown key inside a criterion |
| error | exam alumnos.csv | missing required column; duplicate id; blank id; invalid `presentado`; malformed row |
| aviso | exam alumnos.csv | id not in the subject list |
| error | grade sheet / final / revision | missing `id` column; duplicate id; non-numeric cell; out-of-range value; malformed row |
| aviso | grade sheet / final / revision | id not in the roster; grade for a `presentado = no` student; unknown column; missing leaf column; `total` ≠ computed (computed modes; for a revision row, computed on the merged result `final.csv` + revisions up to and including that file, never on the delta row alone); invalid grader file name (D20) |
| aviso | final.csv | `origen` not `manual` and not an existing grader |
| aviso | revision | file name not matching `NN-YYYY-MM-DD.csv`; blank `motivo` |
| aviso | entregas/ | folder name not in the roster |

## Appendix B — Sample data (`ejemplo/data/`)

`mecanica-de-vuelo/asignatura.json`:

```json
{ "nombre": "Mecánica de Vuelo", "curso": "2026-2027", "codigo": "" }
```

`mecanica-de-vuelo/alumnos.csv`:

```csv
id,apellidos,nombre,email,observaciones
alvarez-lopez-ana,Álvarez López,Ana,ana@example.org,
fernandez-rey-carlos,Fernández Rey,Carlos,carlos@example.org,
garcia-perez-lucia,García Pérez,Lucía,lucia@example.org,
martinez-souto-diego,Martínez Souto,Diego,diego@example.org,
otero-vidal-sara,Otero Vidal,Sara,sara@example.org,Repetidora
perez-castro-hugo,Pérez Castro,Hugo,hugo@example.org,
```

`mecanica-de-vuelo/parcial-1/config.json`: exactly the example in Appendix A
§config.json.

`mecanica-de-vuelo/parcial-1/alumnos.csv`:

```csv
id,apellidos,nombre,presentado,observaciones
alvarez-lopez-ana,Álvarez López,Ana,si,
fernandez-rey-carlos,Fernández Rey,Carlos,si,
garcia-perez-lucia,García Pérez,Lucía,si,
martinez-souto-diego,Martínez Souto,Diego,no,
otero-vidal-sara,Otero Vidal,Sara,si,
ramos-gil-irene,Ramos Gil,Irene,si,Erasmus
```

`mecanica-de-vuelo/parcial-1/notas/pablo.csv`:

```csv
id,alumno,ej1a,ej1b,ej2,ej3,total,comentario
alvarez-lopez-ana,"Álvarez López, Ana",2,1.5,3,2.5,9,Muy bien
fernandez-rey-carlos,"Fernández Rey, Carlos",1,1,2,1.5,5.5,
garcia-perez-lucia,"García Pérez, Lucía",2,2,,,,
```

`mecanica-de-vuelo/parcial-1/notas/claude.csv`:

```csv
id,alumno,ej1a,ej1b,ej2,ej3,total,comentario
alvarez-lopez-ana,"Álvarez López, Ana",2,1.5,2.5,2.5,8.5,Error menor en ej2
fernandez-rey-carlos,"Fernández Rey, Carlos",1,0.5,2,1.5,5,
garcia-perez-lucia,"García Pérez, Lucía",2,2,3,3,10,
otero-vidal-sara,"Otero Vidal, Sara",1,1,1,1,4,
```

`mecanica-de-vuelo/parcial-1/notas/claude/alvarez-lopez-ana.md`:

```markdown
# Álvarez López, Ana

- Ej. 1: correcto.
- Ej. 2: el planteamiento es correcto, pero hay un error de signo en el resultado final (-0,5).
- Ej. 3: falta justificar la hipótesis de pequeñas perturbaciones.
```

`mecanica-de-vuelo/parcial-1/notas/final.csv`:

```csv
id,alumno,ej1a,ej1b,ej2,ej3,total,comentario,origen
alvarez-lopez-ana,"Álvarez López, Ana",2,1.5,3,2.5,9,Muy bien,pablo
fernandez-rey-carlos,"Fernández Rey, Carlos",1,1,2,1.5,5.5,,pablo
```

`mecanica-de-vuelo/parcial-1/revisiones/01-2026-11-20.csv`:

```csv
id,alumno,ej1a,ej1b,ej2,ej3,total,motivo
fernandez-rey-carlos,"Fernández Rey, Carlos",,1.5,,,6,Apartado 1b mal sumado
```

PDFs, generated with `scripts/make_sample_pdf.py`:

- `mecanica-de-vuelo/parcial-1/enunciado/enunciado.pdf` ("Enunciado de ejemplo — Primer parcial")
- `mecanica-de-vuelo/parcial-1/enunciado/rubrica.pdf` ("Rúbrica de ejemplo")
- `mecanica-de-vuelo/parcial-1/entregas/alvarez-lopez-ana/original/examen.pdf` ("Examen de Ana (original)")
- `mecanica-de-vuelo/parcial-1/entregas/alvarez-lopez-ana/corregido/examen-corregido.pdf` ("Examen de Ana (corregido)")
- `mecanica-de-vuelo/parcial-1/entregas/fernandez-rey-carlos/original/examen.pdf` ("Examen de Carlos (original)")

Use ASCII-only text inside the PDFs if the standard Helvetica encoding makes
accents awkward: "Rubrica de ejemplo" is acceptable.

`mecanica-de-vuelo/trabajo-1/config.json`:

```json
{
  "nombre": "Trabajo de estabilidad",
  "tipo": "trabajo",
  "fecha": "2026-12-15",
  "nota_maxima": 10,
  "decimales": 2,
  "calculo_total": "ponderada",
  "criterios": [
    { "id": "memoria", "nombre": "Memoria", "maximo": 10, "peso": 2 },
    { "id": "presentacion", "nombre": "Presentación", "maximo": 10, "peso": 1 }
  ]
}
```

`mecanica-de-vuelo/trabajo-1/alumnos.csv`: the six subject students, in the
same order as the subject list, with blank `presentado`. Empty folders
`enunciado/`, `entregas/`, `notas/` and `revisiones/` each get a `.gitkeep`
(T3 only; the app never creates `.gitkeep`). `tree_fingerprint` and
`list_files` ignore names starting with `.`.

## Implementation

Baseline (2026-10-10): empty repository, no tests exist yet.

Execution as run: two sequential implementer subagents instead of one agent
(user asked to launch subagents), then one UI QA subagent.

- P1 (T1–T10): scaffold, format guide, sample data, storage, domain, repository façade.
- P2 (T11–T19): web layer, README, e2e test, manual scenario. Starts after P1;
  consumes `repo.py` exactly as T10 defines it; may append helpers to
  `tests/conftest.py`.
- P3: UI QA in a real browser over the manual scenario; fixes UI/UX defects
  without changing the data format or decisions.

Ledger:

- [x] T1–T10 — P1 done: `uv run pytest` 259 passed; `ruff check` / `ruff format --check` exit 0; `git check-ignore data/x` → `data/x`; all criteria checked by P1 with evidence
- [x] T11–T19 — P2 done: `uv run pytest` 361 passed (incl. `tests/test_e2e_flow.py` byte-for-byte); ruff clean; server smoke run with curl (15 pages 200, assets 200, OOB total, 409, huella 204); headless-browser checks of T14 editor, T15 PDF iframe, T16 grid. Manual scenario handed to P3
- [x] UI QA + manual scenario — P3 done (2026-10-10, second pass): `uv run pytest` 369 passed; ruff clean; full manual scenario re-run in a real browser with evidence below

Deviations:
- Execution: split into sequential packages P1/P2 plus a QA pass (user request, 2026-10-10).
- T1: `.gitignore` uses `/data/` instead of `data/`; the unanchored pattern also ignored `ejemplo/data/`, contradicting D12. Plan text fixed.
- T13: `Repository.mark_present(slug, exam, version) -> int` added (one versioned atomic write for `marcar-presentados`; the binding interface had no bulk operation).
- T11–T18: the web calls `effective.py` and `validation.py` directly (via `repo.exam_dir()` / `repo.root`) for effective grades, copy-to-final, revisions and validation, since `Repository` has no wrappers for them.
- T5: criterion id `version` is reserved (`RESERVED_IDS` in `config_io.py`, LEEME updated): it would clash with the `version` form field of grade and revision posts.
- T10: `Repository.subject_meta(slug)` returns `(meta, issues, version)` (shape of `exam_config`); `save_grade_row` rejects keys other than leaf ids, `total`, `comentario` (BadRequest) and ids not in the roster (NotFound).

## Results

P3 QA pass (2026-10-10, Playwright 1.63, Chromium + Firefox, data copy of
`ejemplo/data` under `/tmp/claude-1000/correctron-qa/data`, port 8830;
`ejemplo/data` untouched, `git status` shows no `data/`):

- Verification 2.1–2.10 re-run step by step in a real browser, checking the
  files on disk each time: 2.2 add/rename/import in `alumnos.csv` (rename
  propagates to exam rosters); 2.3 Hugo added, all marked presentados; 2.4
  `ej4` (max 1) added, `config.json` matches the screen; 2.5 PDF inline,
  upload + delete to `.papelera/`; 2.6 keyboard flow (Tab/Enter/ArrowUp,
  NP rows skipped), totals without reload, invalid values flagged, long
  feedback saved; 2.7 external edit → banner in ~3 s → web edit gives a 409
  notice with "Recargar" and the external edit is kept; 2.8 hand-made
  `notas/llm.csv` (`;`, decimal commas) appears as grader and in Comparar,
  untouched on disk; 2.9 "Usar" per grader, bulk copy, new revision session,
  Ana revised (resumen shows 10 with "revisada" link); 2.10 original +
  corrected PDFs uploaded for Hugo and viewed.
- Verification 3: full-page screenshots of every page/tab at 1366 and 900
  px plus `prefers-color-scheme: dark`, all looked at; no JS pageerrors and
  no HTTP 500 anywhere. The only console noise is htmx logging the
  intentional 409 of step 2.7 and the browser noting the 404 of the error
  pages themselves — both expected, not product errors.
- Fixes from this pass (each with a failing test first): dark mode was
  locked to light by `data-theme="light"` — removed so Pico follows the OS,
  plus a `prefers-color-scheme: dark` block in `app.css` (verified in
  screenshots); new `GET /favicon.ico` route serving the check-mark SVG
  (was a 404 in the server log).
- Checked and left as-is: totals above `nota_maxima` after adding `ej4`
  without raising it are correctly reported as errors (validation doing
  its job, G4); the rejected-edit row re-render keeps the stored values by
  design (D26); headless Firefox does not render PDFs in the `<iframe>`
  (shows blank, offers download) — Chromium renders them and the response
  is `inline; application/pdf`, so T15 ("Firefox or Chrome") holds via
  Chrome; grids scroll horizontally inside `.tabla-scroll` at 900 px.

## Closure
