---
id: "0006"
title: "PDF tools web: split and anonymize"
type: plan
created: 2026-10-11
---

# 0006 — PDF tools web: split and anonymize

## Justification

The teacher scans all the exams of a sitting in one go, so they arrive as a
single PDF holding every student's pages. Correctron expects one file per
student (`entregas/<id>/original/`), and today there is no way to cut the big
PDF without an external tool. Before graders (people or LLMs) see an exam, the
student's name should also be hidden, and there is no tool for that either.

### Goals

- A second local web, launched with `uv run correctron-pdf`, that works on PDFs
  dropped into its own data folder (default `./pdfs`).
- **Dividir**: show every page of a PDF as a grid of thumbnails (left to
  right, top to bottom); select a contiguous range by clicking; "Seccionar"
  gives that range a name; sections are listed, renamable and removable;
  pages can be rotated 180° and zoomed; "Exportar" writes one PDF per section
  named after it.
- **Anonimizar**: open a PDF, draw filled rectangles on any page, pick their
  colour with a colour picker or an eyedropper that samples the page, copy a
  rectangle to every page, and export a flattened copy where the covered area
  is really gone. A second export applies the same rectangles to every PDF in
  the same folder.
- Work in progress (sections, rectangles) is saved in plain JSON files next to
  the PDF, so closing the browser loses nothing and the files stay readable.

### Non-goals

- Sending sections straight into an exam's `entregas/` (user chose a plain
  output folder; possible follow-up ticket).
- Automatic splitting (every N pages, blank-page or QR detection).
- Moving or resizing a drawn rectangle (delete and redraw instead).
- Rotations other than 180°, reordering pages, deleting pages (pages that are
  in no section are simply not exported).
- OCR, text redaction, compression tuning.
- Any change to the existing grading web (`src/correctron/web/`) beyond
  reusing its static files read-only.

## Plan

### Context

- Python ≥ 3.12, FastAPI + Jinja2, no frontend build. Libraries are vendored
  in `src/correctron/web/static/vendor/` (`alpine.min.js`, `htmx.min.js`,
  `pico.min.css`); the house style is `src/correctron/web/static/app.css`
  (tokens, `.barra`, `.ancho`, `.tarjeta`, `.vacio`, `aviso-*` classes).
- The grading web: app factory `create_app(data_dir)` in
  `src/correctron/web/app.py`; CLI in `src/correctron/cli.py`
  (`build_parser`, `resolve_data_dir`, `main`, opens the browser with
  `threading.Timer` + `webbrowser.open`, runs `uvicorn.run`). The new CLI
  mirrors it.
- Reusable helpers in `src/correctron/fsutil.py`: `atomic_write_bytes`,
  `atomic_write_text`, `safe_resolve(root, rel)` (raises `PathOutsideData`),
  `file_version(path)` (16-hex SHA-256 or `""`), `check_version(path, v)`
  (raises `VersionConflict`), `move_to_trash(root, path)` (to
  `root/.papelera/<stamp>/…`).
- Project conventions (plan 0001): UI text in Spanish, code, comments and tests
  in English; file names in Spanish without accents; files are the only source
  of truth and external edits are never overwritten silently (version tokens,
  409 on mismatch); deleted/overwritten files go to `.papelera/`.
- Tests: `tests/conftest.py` has `sample_data`/`client` fixtures for the
  grading web; `tests/test_cli.py` shows how the CLI is tested with a fake
  `uvicorn.run`.
- Commands: `uv sync`, `uv run pytest`, `uv run ruff check`,
  `uv run ruff format --check`. `.gitignore` already ignores `/data/`.
- Verified in a throwaway env (pypdfium2 5.14.0, Pillow 12.3.0):
  `PdfDocument.new()`, `doc.import_pages(src, [indices])`,
  `page.get_rotation()/set_rotation(deg)`, `page.render(scale=…).to_pil()`
  (render honours `/Rotate`), `doc.save(path)`; and Pillow
  `img.save(f, "PDF", resolution=200, quality=85)` gives a page of the
  original size in points (595×842 in → 595.08×842.04 out).

### Approach

A new sibling package `src/correctron/pdfweb/` holds the second web, and a pure
module `src/correctron/pdftools.py` holds all PDF logic (no FastAPI), so it is
unit-testable. One new dependency, **pypdfium2** (Apache-2.0/BSD, wheels for
all platforms, no system libraries), does page counting, thumbnail rendering,
lossless page extraction and rotation; **Pillow** draws the rectangles and
writes the flattened pages.

Thumbnails are rendered by the server as JPEG on demand
(`GET /pagina?pdf=…&n=…&ancho=…`) and shown with `<img loading="lazy">`; the
browser never parses PDFs, so no pdf.js is vendored. Because the images are
same-origin, the anonymize page can draw the displayed page on a hidden
`<canvas>` and read pixels for the eyedropper, which works in every browser
(the native `EyeDropper` API is Chromium-only and is not used).

The two pages are client-heavy (selection, drawing), so they use Alpine.js
components that talk to small JSON endpoints, not htmx fragments. Every change
autosaves the sidecar JSON with the project's version-token rule.

Splitting copies pages losslessly (`import_pages`), applying a 180° rotation
where marked. Anonymizing renders each page at 200 dpi, paints the rectangles,
saves it as a one-page JPEG-in-PDF in memory and appends it to the output one
page at a time, so a 100-page scan never holds 100 bitmaps in memory.

Discarded: drawing a vector rectangle over the original page (user chose real
removal: the name would still be under it); PyMuPDF (AGPL licence); pypdf
(cannot render thumbnails); a section in the grading web (user wants a
separate web); subcommand `correctron pdf` (user chose a separate command).

### Decisions

| # | Decision | Rationale | Source |
| --- | --- | --- | --- |
| D1 | Separate web in a sibling package `src/correctron/pdfweb/`; `src/correctron/web/` is not moved or modified. | User choice. | user |
| D2 | Command `correctron-pdf` (`[project.scripts]`), options `--data`, `--host` (127.0.0.1), `--port` (**8766**), `--no-abrir`. Data folder: `--data`, then `$CORRECTRON_PDF_DATA`, then `./pdfs`. `/pdfs/` added to `.gitignore`. | User choice; different port so both webs run at once. | user |
| D3 | Section export goes to a folder next to the PDF named after its stem: `pdfs/<dir>/<stem>.pdf` → `pdfs/<dir>/<stem>/<section file name>.pdf`. | User choice: plain output folder. | user |
| D4 | Anonymization flattens: each page rendered at 200 dpi (`ANON_DPI = 200`), rectangles painted with Pillow, saved as JPEG quality 85 (`ANON_JPEG_QUALITY = 85`) inside the PDF at `resolution=200` so the page keeps its size. | User chose real removal. | user |
| D5 | Anonymizer works on one PDF, with an extra action "Aplicar a todos los PDFs de esta carpeta": same rectangles on every `*.pdf` directly in the same folder (not recursive). A rectangle on page N is skipped for PDFs with fewer pages, and that is reported. | User choice. | user |
| D6 | Anonymized output: `<dir>/anonimizados/<file name>.pdf` (same file name as the source). The original is never modified. | Keeps originals; `anonimizados/` is a subfolder so the non-recursive "all PDFs" action never re-processes outputs. | plan |
| D7 | Split extras: rotate a page 180° (toggle, applied at export) and zoom (double-click a thumbnail opens it large in a `<dialog>`). No "every N pages". | User choice. | user |
| D8 | Work in progress lives in sidecars next to the PDF: `<file>.pdf` → `<file>.secciones.json` and `<file>.recuadros.json` (formats below). They are written atomically with a version token; a mismatch answers 409 and the page asks to reload. | File-first project rule (plan 0001 D14). | plan |
| D9 | Section rules: pages are 1-based; a section is `desde ≤ hasta` within the page count; sections never overlap; names are unique case-insensitively after `section_filename`; sections are kept sorted by `desde`. Pages in no section are not exported. | Unambiguous export. | plan |
| D10 | Selection: first click on a page sets the anchor and selects it; a second click selects anchor…clicked page (either direction); a third click starts a new anchor. `Esc` clears. Clicking a page that already belongs to a section selects that section in the list instead. "Seccionar" is disabled when the selection is empty or overlaps a section. | Matches "select contiguous ranges by clicking". | plan |
| D11 | `section_filename(name)`: strip; replace each of `/ \ : * ? " < > \|` and control characters with `-`; collapse runs of spaces; strip leading/trailing `.` and spaces; accents and spaces are kept; empty result is an error; the file is `<that>.pdf`. | User wants the exact name they typed. | plan |
| D12 | Re-exporting over an existing output file first moves the old one to `<data>/.papelera/` with `fsutil.move_to_trash`. | Project rule (plan 0001 D18). | plan |
| D13 | Rectangle coordinates are fractions (0–1) of the page as displayed (after `/Rotate`), origin top-left: `x`, `y`, `ancho`, `alto`. `pagina` is an int ≥ 1 or the string `"todas"`. "Copiar a todas las páginas" turns the selected rectangle into one with `pagina: "todas"`. | Resolution-independent; "todas" also works for PDFs of other lengths (D5). | plan |
| D14 | Eyedropper: "Pipeta" button enters pick mode; the next click on the large page sets the colour to the average of the 5×5 pixels around the click, read from a canvas of the displayed image; then pick mode ends. Plus a standard `<input type="color">`. The chosen colour applies to new rectangles and to the selected one. Default colour `#ffffff`. | Works in all browsers; averaging avoids scan noise. | plan |
| D15 | Rectangles are drawn by dragging on the large page (minimum 0.5 % of width and height, smaller drags are ignored), selected by clicking, removed with a button or the `Supr`/`Delete` key. No move or resize. | Keeps the editor small. | plan |
| D16 | Thumbnails: `GET /pagina` renders JPEG (quality 80) at `ancho` px wide, clamped to 100–2000; the grid uses 220 px, the zoom and anonymize page 1200 px. Response header `Cache-Control: no-cache`; no server cache. | Simple; pypdfium2 renders a scan page in tens of ms. | plan |
| D17 | Frontend: Alpine.js components in `pdfweb/static/dividir.js` and `anonimizar.js` with JSON endpoints; the pdfweb app mounts the grading web's `static/` folder read-only at `/comun` (for Pico, Alpine and `app.css`) and its own at `/static`. | No duplicated vendor files; same look. | plan |
| D18 | The home page lists every `*.pdf` under the data folder recursively, skipping names starting with `.`, grouped by folder, with its page count and links "Dividir" and "Anonimizar". | Lets the user drop PDFs anywhere, including exported sections. | plan |
| D19 | Dependencies: `pypdfium2>=4.30` and `pillow>=10` added to `[project].dependencies`. | Permissive licences, no system libs, verified API. | research |

**Sidecar formats** (written with `json.dumps(…, ensure_ascii=False, indent=2) + "\n"`):

```json
// examenes.secciones.json
{
  "secciones": [
    {"nombre": "Álvarez López, Ana", "desde": 1, "hasta": 4},
    {"nombre": "Fernández Rey, Carlos", "desde": 5, "hasta": 8}
  ],
  "girar": [6]
}
```

```json
// examen.recuadros.json
{
  "recuadros": [
    {"pagina": "todas", "x": 0.05, "y": 0.02, "ancho": 0.45, "alto": 0.06, "color": "#ffffff"},
    {"pagina": 3, "x": 0.6, "y": 0.9, "ancho": 0.3, "alto": 0.05, "color": "#000000"}
  ]
}
```

A missing sidecar means `{"secciones": [], "girar": []}` / `{"recuadros": []}`.
`color` must match `^#[0-9a-f]{6}$` (lowercase; the server lowercases input).
Fractions must satisfy `0 ≤ x`, `0 ≤ y`, `ancho > 0`, `alto > 0`,
`x + ancho ≤ 1`, `y + alto ≤ 1` (allow 1e-6 slack, then clamp).

### Tasks

#### T1 — PDF logic module and dependencies

- **Objective:** All PDF operations exist as tested pure functions.
- **Files:** `pyproject.toml`, `uv.lock` (via `uv add`), `src/correctron/pdftools.py`, `tests/test_pdftools.py`
- **Depends on:** —
- **Details:** `uv add "pypdfium2>=4.30" "pillow>=10"`. In `pdftools.py` define
  `class PdfError(ValueError)` (Spanish user-facing message) and:
  - `ANON_DPI = 200`, `ANON_JPEG_QUALITY = 85`, `THUMB_JPEG_QUALITY = 80`
  - `list_pdfs(root: Path) -> list[Path]` (D18, sorted by relative path)
  - `page_count(pdf: Path) -> int`
  - `render_page_jpeg(pdf: Path, n: int, width: int) -> bytes` (n 1-based; width clamped 100–2000; `PdfError` if n out of range)
  - `section_filename(name: str) -> str` (D11, returns name with `.pdf`)
  - `sections_path(pdf) / boxes_path(pdf) -> Path` (D8 naming)
  - `load_sections(pdf) -> tuple[dict, str]` and `load_boxes(pdf) -> tuple[dict, str]` (data, version)
  - `validate_sections(data: dict, n_pages: int) -> dict` (D9; returns normalised dict, sorted; `girar` deduplicated, sorted, each in 1..n)
  - `validate_boxes(data: dict) -> dict` (D13 rules; lowercases colours)
  - `save_sections(pdf, data, version) -> str` / `save_boxes(pdf, data, version) -> str` (validate, `check_version`, `atomic_write_text`, return new version)
  - `export_sections(root: Path, pdf: Path) -> list[Path]` (reads the saved sidecar, writes D3 outputs, applies `girar` as `(rotation + 180) % 360`, D12 trash; `PdfError` "No hay secciones" when empty)
  - `anonymize(root: Path, pdf: Path, boxes: list[dict]) -> tuple[Path, list[str]]` (D4/D6/D12; streaming page by page as in *Approach*; returns output path and warnings like «examen.pdf no tiene página 3»)
  - Every pypdfium2 call is made while holding one module-level `threading.Lock` (`_PDFIUM_LOCK`), because pdfium is not thread-safe and FastAPI runs sync routes in a thread pool.
  - `anonymize_folder(root: Path, pdf: Path) -> tuple[list[Path], list[str]]` (D5: uses `pdf`'s saved rectangles on every `*.pdf` in `pdf.parent`)
- **Acceptance criteria:**
  - [ ] `uv run pytest tests/test_pdftools.py` passes. Tests build PDFs in `tmp_path` with `pypdfium2.PdfDocument.new()` + `new_page(595, 842)` (no fixture files) and cover: `list_pdfs` skips `.papelera`; `page_count`; `render_page_jpeg` returns bytes starting with `b"\xff\xd8"` and width 220 for `width=220`, and `PdfError` for n=0 and n>count; `section_filename("Ana / López: 1")` == `"Ana - López- 1.pdf"`, `section_filename(" Álvarez López, Ana ")` == `"Álvarez López, Ana.pdf"`, and `PdfError` for `"  "`; `validate_sections` rejects overlap, out-of-range, `desde > hasta`, duplicate names (case-insensitive); `save_sections` with a stale version raises `VersionConflict`; `export_sections` on a 6-page PDF with sections 1–2 and 3–6 and `girar: [3]` writes two files with 2 and 4 pages and the first page of the second file has rotation 180; re-export moves the old file into `.papelera/`; `anonymize` with a `#ff0000` rectangle covering the top-left quarter on `"todas"` produces a PDF with the same page count and page size within 1 pt, where rendering page 2 and sampling the centre of that quarter gives a colour within 20 of (255, 0, 0) per channel, and a pixel outside it stays near white; `anonymize_folder` on a folder with a 1-page and a 3-page PDF and a rectangle on page 3 writes both outputs and returns one warning.
  - [ ] `uv run ruff check` and `uv run ruff format --check` pass.

#### T2 — App skeleton, CLI and home page

- **Objective:** `uv run correctron-pdf` starts a web that lists the PDFs of its data folder.
- **Files:** `pyproject.toml`, `.gitignore`, `src/correctron/pdf_cli.py`, `src/correctron/pdfweb/__init__.py`, `src/correctron/pdfweb/app.py`, `src/correctron/pdfweb/routes.py`, `src/correctron/pdfweb/templates/base.html`, `src/correctron/pdfweb/templates/index.html`, `src/correctron/pdfweb/templates/error.html`, `src/correctron/pdfweb/static/pdf.css`, `tests/test_pdf_cli.py`, `tests/test_pdfweb.py`
- **Depends on:** T1
- **Details:**
  - `pyproject.toml`: `correctron-pdf = "correctron.pdf_cli:main"`. `.gitignore`: add `/pdfs/`.
  - `pdf_cli.py` mirrors `cli.py` with D2 defaults; `resolve_data_dir` reads `CORRECTRON_PDF_DATA`; prints `Correctron PDF en {url} — datos: {dir}`; creates the data folder if missing.
  - `pdfweb/app.py`: `create_app(data_dir: Path) -> FastAPI` stores `app.state.root`, Jinja2 templates with `trim_blocks`/`lstrip_blocks`, mounts `/comun` → `correctron/web/static` and `/static` → `pdfweb/static` (D17), includes `routes.router`, and maps `PdfError` → 400, `VersionConflict` → 409, `PathOutsideData` → 404. For paths starting with `/api/` the error body is JSON `{"error": "<mensaje>"}`; otherwise `error.html`. The 409 message: «El archivo ha cambiado fuera de esta página. No se ha guardado nada: recarga para ver la versión actual.»
  - `base.html`: same skeleton as `web/templates/base.html` (barra with logo, `#avisos`, `main.ancho`), title suffix «Correctron PDF», links `/comun/vendor/pico.min.css`, `/comun/app.css`, `/static/pdf.css`, script `/comun/vendor/alpine.min.js` (defer); nav links «PDFs» (`/`).
  - Routes: `GET /` (D18 list with page count and links `/dividir?pdf=<rel>` and `/anonimizar?pdf=<rel>`; empty state text «No hay PDFs. Copia el PDF escaneado en <code>{root}</code> y recarga.»); `GET /archivo/{ruta:path}` serves a PDF inside the root inline (only `.pdf`, 404 otherwise); `GET /pagina?pdf=&n=&ancho=` (D16). Every `pdf` parameter goes through a helper `resolve_pdf(root, rel) -> Path` that uses `safe_resolve`, requires an existing `.pdf` file, else `PdfError("No existe el PDF «…».")`.
- **Acceptance criteria:**
  - [ ] `tests/test_pdf_cli.py` (copying the fake-server pattern of `tests/test_cli.py`) checks `--help` lists the four options, default port 8766, env var and `./pdfs` fallback.
  - [ ] `tests/test_pdfweb.py` with a `pdf_client` fixture (temp root holding `examenes.pdf` with 3 pages and `.papelera/x.pdf`): `GET /` is 200 and contains `examenes.pdf`, `3` and `/dividir?pdf=examenes.pdf` but not `x.pdf`; `GET /pagina?pdf=examenes.pdf&n=1&ancho=220` is 200 `image/jpeg`; `n=4` is 400; `pdf=../x.pdf` is 404; `/comun/vendor/alpine.min.js` and `/static/pdf.css` are 200.
  - [ ] `uv run correctron-pdf --no-abrir --data /tmp/x` prints the URL with port 8766 (check manually, then stop it).
  - [ ] Full `uv run pytest` still passes.

#### T3 — Split page (Dividir)

- **Objective:** The user can create named sections over a grid of pages, rotate and zoom pages, and export them.
- **Files:** `src/correctron/pdfweb/routes.py`, `src/correctron/pdfweb/templates/dividir.html`, `src/correctron/pdfweb/static/dividir.js`, `src/correctron/pdfweb/static/pdf.css`, `tests/test_pdfweb.py`
- **Depends on:** T2
- **Details:**
  - `GET /dividir?pdf=` renders `dividir.html` with the page count, the relative path and the sidecar data + version embedded as `<script type="application/json" id="estado">` (`tojson`).
  - `PUT /api/secciones?pdf=` body `{"version": "...", "secciones": [...], "girar": [...]}` → `save_sections` → `{"version": "<new>"}`.
  - `POST /api/secciones/exportar?pdf=` → `export_sections` → `{"archivos": ["<rel path>", …]}`.
  - Layout: header with the PDF name and page count; a sticky toolbar with the selection text («Páginas 3–6» or «Ninguna página seleccionada»), a name input and «Seccionar» button, and «Exportar»; a two-column body: left a CSS grid of thumbnails (`grid-template-columns: repeat(auto-fill, minmax(160px, 1fr))`, images `/pagina?…&ancho=220`, `loading="lazy"`, page number under each); right the sections list (name as an editable input saved on `change`, range «págs. 1–4», «Quitar» button).
  - Each thumbnail shows: a coloured left border and a badge with its section name when it belongs to one (colour cycles through 6 fixed CSS colours by section index); a highlighted outline when selected; a small «↻» button (stops click propagation) toggling 180° rotation, shown as `transform: rotate(180deg)` on the image; double-click opens a `<dialog>` with the page at `ancho=1200` (rotated if marked), closed by a «Cerrar» button, `Esc` or clicking the backdrop.
  - Selection follows D10. «Seccionar» with an empty name shows «Escribe un nombre.»; after a successful section the name input is cleared and focused, and the selection is cleared.
  - Every change (add, rename, remove section, rotate) sends the PUT; the returned version replaces the stored one. On a 400 show the server message in `#avisos` (as `<article class="aviso-error">`) and restore the previous state; on 409 show the message with a «Recargar» button.
  - «Exportar» is disabled with no sections; on success shows «Exportadas N secciones en <carpeta>/» with links to each file under `/archivo/…`.
- **Acceptance criteria:**
  - [ ] New tests in `tests/test_pdfweb.py`: `GET /dividir?pdf=examenes.pdf` contains `id="estado"` and `dividir.js`; PUT with valid sections returns a new version and writes `examenes.secciones.json` matching the D8 format; PUT with overlapping sections returns 400 JSON with an `error` key and leaves the file unchanged; PUT with a stale version returns 409; POST exportar writes `examenes/<name>.pdf` files and returns their relative paths.
  - [ ] Manual check (see *Verification*, steps 1–6) passes in Firefox and in a Chromium browser.

#### T4 — Anonymize page (Anonimizar)

- **Objective:** The user can cover areas of pages with coloured rectangles and export flattened copies of one PDF or of its whole folder.
- **Files:** `src/correctron/pdfweb/routes.py`, `src/correctron/pdfweb/templates/anonimizar.html`, `src/correctron/pdfweb/static/anonimizar.js`, `src/correctron/pdfweb/static/pdf.css`, `tests/test_pdfweb.py`
- **Depends on:** T2 (T3 not required; it may be done after T3 to reuse the notice helper pattern)
- **Details:**
  - `GET /anonimizar?pdf=` renders with page count, path and `#estado` JSON (rectangles + version), plus the number of PDFs in the same folder for the button label «Aplicar a los N PDFs de esta carpeta».
  - `PUT /api/recuadros?pdf=` body `{"version", "recuadros"}` → `save_boxes` → `{"version"}`.
  - `POST /api/anonimizar?pdf=&todos=0|1` → `anonymize` (todos=0, using the saved rectangles) or `anonymize_folder` (todos=1) → `{"archivos": [...], "avisos": [...]}`. With no rectangles: 400 «No hay recuadros.»
  - Layout: left a vertical strip of thumbnails (`ancho=220`) with the page number and a badge with the count of rectangles that apply to it (own + `"todas"`); right the current page at `ancho=1200` inside a `position: relative` container, rectangles as absolutely positioned divs in % (D13), the selected one outlined. Toolbar: `<input type="color">`, «Pipeta», «Copiar a todas las páginas», «Quitar recuadro», page navigation «‹ Anterior» / «Siguiente ›» (also arrow keys), «Exportar este PDF», «Aplicar a los N PDFs de esta carpeta».
  - Drawing follows D15 (pointer events on the container; a dashed preview while dragging). Eyedropper follows D14; while in pick mode the cursor is `crosshair` and drawing is disabled. Rectangles with `pagina: "todas"` are drawn on every page with a small «todas» label.
  - Saving, errors and 409 behave as in T3. Export success shows the output links and each warning as `aviso-aviso`.
- **Acceptance criteria:**
  - [ ] New tests: `GET /anonimizar?pdf=examenes.pdf` contains `id="estado"` and `anonimizar.js`; PUT with a valid rectangle writes `examenes.recuadros.json`; PUT with `x + ancho > 1` or colour `"red"` returns 400; POST `/api/anonimizar?pdf=examenes.pdf&todos=0` writes `anonimizados/examenes.pdf` with 3 pages; `todos=1` with a second 1-page PDF in the folder and a rectangle on page 2 returns 2 files and 1 warning; POST with no rectangles returns 400.
  - [ ] Manual check (see *Verification*, steps 7–12) passes in Firefox and in a Chromium browser.

#### T5 — Documentation

- **Objective:** The README explains the new tool.
- **Files:** `README.md`
- **Depends on:** T3, T4
- **Details:** Add a section «Herramienta de PDFs (dividir y anonimizar)» after «Usar un LLM como corrector»: how to launch (`uv run correctron-pdf`, options, port 8766, folder `./pdfs`), the workflow (copy the scan into `pdfs/`, Dividir → sections → Exportar into `pdfs/<nombre>/`, then Anonimizar one exported PDF, «Copiar a todas las páginas», «Aplicar a los N PDFs»; outputs in `anonimizados/`), the sidecar files and their meaning, and that anonymizing flattens pages to images at 200 ppp so covered content is really removed. Mention `/pdfs/` is git-ignored.
- **Acceptance criteria:**
  - [ ] `grep -n "correctron-pdf" README.md` finds the launch command; the section mentions `.secciones.json`, `.recuadros.json` and `anonimizados/`.

### Execution

Mode: single agent. The tasks are sequential (T2 needs T1's functions; T3 and
T4 both edit `routes.py`, `pdf.css` and `tests/test_pdfweb.py`), and the whole
change is moderate in size.

### Verification

1. `uv run pytest`, `uv run ruff check`, `uv run ruff format --check` pass.
2. Manual scenario with a real or generated multi-page PDF (e.g. 12 pages built
   with pypdfium2 or a real scan) copied to `./pdfs/examenes.pdf`, then
   `uv run correctron-pdf`:
   1. The home page lists `examenes.pdf` with 12 pages and both links.
   2. «Dividir»: the grid shows the 12 pages in order, left to right, top to bottom.
   3. Click page 1 then page 4: pages 1–4 highlighted, toolbar says «Páginas 1–4». Type «Álvarez López, Ana», «Seccionar»: pages 1–4 get the badge and appear in the list. Selecting 4–6 disables «Seccionar».
   4. Make a second section 5–8; rotate page 6 with «↻»; double-click page 6 shows it large and rotated.
   5. Reload the page: sections and rotation are still there; `pdfs/examenes.secciones.json` holds them.
   6. «Exportar»: `pdfs/examenes/Álvarez López, Ana.pdf` (4 pages) and the second file (4 pages, page 2 upside-down relative to the original) exist; pages 9–12 were not exported.
   7. Open «Anonimizar» on `examenes/Álvarez López, Ana.pdf`; drag a rectangle over the name area on page 1; it appears white.
   8. «Pipeta» then click on a dark area: the colour input and the selected rectangle change to that colour.
   9. «Copiar a todas las páginas»: the rectangle shows on pages 2–4 with the «todas» label and the strip badges update.
   10. «Exportar este PDF»: `anonimizados/Álvarez López, Ana.pdf` opens with the area covered on every page; selecting text/images in a PDF viewer cannot reveal what was under it (the page is a single image).
   11. «Aplicar a los 2 PDFs de esta carpeta»: both files appear in `anonimizados/`.
   12. Edit `examenes.recuadros.json` by hand while the page is open, then add a rectangle in the web: the 409 notice with «Recargar» appears and the file keeps the hand edit.
3. The grading web (`uv run correctron`) still works and `tests/test_web_files.py` is unchanged and passing.

### Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Rendering many thumbnails of a large scan is slow | Grid fills slowly | `loading="lazy"` images; small width; accepted for v1. |
| Flattened PDFs are larger than lossless ones | Bigger files | JPEG quality 85 at 200 dpi (~200–400 KB/page); accepted, constants in `pdftools.py` if tuning is needed. |
| Scanner PDFs with odd page boxes or `/Rotate` values | Rectangle lands in the wrong place | Coordinates are relative to the rendered (rotated) page, and the output is built from that same render; T1 test covers page size. |
| pypdfium2 is not thread-safe | Concurrent renders could crash | FastAPI runs sync routes in a thread pool: guard every pypdfium2 call in `pdftools.py` with one module-level `threading.Lock`. |
| Names with characters invalid on Windows | Export fails on another OS | D11 replaces them. |

### Open questions

None.

## Implementation

Baseline (2026-10-11): `uv run pytest` 369 passed, 0 failing; ruff check and format clean.

Executed with sequential Haiku subagents at the user's request (one per step,
same task order as the plan; never two at once since T3/T4 share files):
P1 = T1+T2, P2 = T3, P3 = T4+T5.

- [x] T1 — PDF logic module — `uv run pytest tests/test_pdftools.py` 29 passed; ruff clean
- [x] T2 — app skeleton, CLI, home — `tests/test_pdf_cli.py` + `tests/test_pdfweb.py` 17 passed; `correctron-pdf --no-abrir` printed port 8766; full suite 415 passed
- [x] T3 — Dividir page — `tests/test_pdfweb.py` 21 passed; full suite 424 passed; Verification 2.1–2.6 passed in headless Chromium and Firefox (Playwright, see Results)
- [x] T4 — Anonimizar page — `tests/test_pdfweb.py` 33 passed; full suite 436 passed; Verification 2.7–2.12 passed in headless Chromium and Firefox
- [x] T5 — README — `grep -n correctron-pdf README.md` → line 100; section names `.secciones.json`, `.recuadros.json`, `anonimizados/`

Deviations:
- Execution: plan says single agent; user asked for Haiku subagent(s) (2026-10-11), run one at a time in task order.
- Review (orchestrator), after the packages:
  - `.pdf` is matched case-insensitively (scanners often write `.PDF`): new `pdftools.is_pdf_name` and `pdftools.folder_pdfs`, used by `list_pdfs`, `anonymize_folder`, `resolve_pdf`, `/archivo` and the folder count on the Anonimizar page (removes a duplicated predicate in `routes.py`). Test `test_upper_case_extension_counts_as_pdf`.
  - Anonimizar: only ←/→ change page (↑/↓ were also bound and blocked scrolling the tall page).
  - Anonimizar: with one PDF in the folder the button reads «Aplicar al único PDF de esta carpeta».
  - CSS: Pico's `ul li { list-style: square }` drew markers next to every thumbnail; `list-style: none` set on the `li`s. The 0.2 s rotation transition was removed (rotated pages were captured half-turned).
- Interpretations by the implementers, kept: drawing a rectangle selects it; a click on empty page space clears the selection; fractions are rounded to 4 decimals on the client; `GET /dividir` and `/anonimizar` validate the sidecar, so a hand-edited invalid sidecar shows the 400 error page instead of loading.

## Results

All goals delivered; nothing left out.

- **Tests:** `uv run pytest` → 437 passed (369 baseline + 68 new: `tests/test_pdftools.py` 30, `tests/test_pdf_cli.py` 5, `tests/test_pdfweb.py` 33). `uv run ruff check` → All checks passed; `uv run ruff format --check` → 62 files already formatted.
- **CLI:** `uv run correctron-pdf --no-abrir --data <dir>` prints `Correctron PDF en http://127.0.0.1:8766 — datos: <dir>`.
- **Verification section, step 2 (1–12):** run end to end in real headless Chromium and Firefox (Playwright 1.63, scratch script outside the repo) against a live server with a generated 12-page PDF. All 12 steps passed in both browsers with no JS errors (the only console entry is the network log of the intentional 409 in step 12, in Chromium). The checks:
  - Sidecar content is exactly the D8 example.
  - Exported files have 4 + 4 pages, with rotations `[0,0,0,0]` and `[0,180,0,0]`.
  - The eyedropper picked `#141478` from the dark-blue name area and recoloured the selected box.
  - Each anonymized page is a single image object, and the covered area has the box colour on all 4 pages.
  - The folder export writes 2 files.
  - An external edit gives the 409 notice with «Recargar», and the hand edit is kept.
- **Screenshots:** reviewed for the home page, the grid with sections and a rotated page, the zoom dialog, and the Anonimizar page with a «todas» box. They led to the CSS fixes listed under Deviations.
- **Verification step 3:** the grading web is untouched (`git diff --stat` shows no change under `src/correctron/web/`; `tests/test_web_files.py` passes within the full suite).

## Closure

- Date: 2026-10-11
- Outcome: completed. The user asked to implement with Haiku subagents and to close the plan after review.
- Follow-ups (not captured as tickets yet):
  - Send exported sections straight into an exam's `entregas/` (non-goal of this plan).
  - The home page opens every PDF to count pages, which is slow on large folders.
  - While an anonymize export runs it holds the pdfium lock, so thumbnails wait until it finishes.
  - Double-clicking a page to zoom also counts as two selection clicks.
