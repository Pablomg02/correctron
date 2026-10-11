"""PDF logic for the PDF tools web: thumbnails, sections, rectangles and flattened copies.

Pure functions without web code, so they can be tested directly. pypdfium2 is not
thread-safe and FastAPI runs sync routes in a thread pool, so every pypdfium2 call is
made while holding `_PDFIUM_LOCK`. The lock is not re-entrant: public functions never
call each other while holding it.
"""

from __future__ import annotations

import io
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

from .fsutil import (
    atomic_write_bytes,
    atomic_write_text,
    check_version,
    file_version,
    move_to_trash,
)

ANON_DPI = 200
ANON_JPEG_QUALITY = 85
THUMB_JPEG_QUALITY = 80
ANON_DIR = "anonimizados"

_PDFIUM_LOCK = threading.Lock()
_MIN_WIDTH = 100
_MAX_WIDTH = 2000
_SLACK = 1e-6
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_FORBIDDEN_RE = re.compile(r'[/\\:*?"<>|\x00-\x1f\x7f]')
_SPACES_RE = re.compile(r" {2,}")


class PdfError(ValueError):
    """A user-facing problem with a PDF or with the data sent about it."""


# --- reading ---------------------------------------------------------------


def is_pdf_name(name: str) -> bool:
    """A visible file name with a `.pdf` extension in any case (scanners often write `.PDF`)."""
    return name.lower().endswith(".pdf") and not name.startswith(".")


def folder_pdfs(folder: Path) -> list[Path]:
    """The PDFs directly in `folder` (not recursive), sorted by name."""
    return sorted(
        (path for path in folder.iterdir() if is_pdf_name(path.name) and path.is_file()),
        key=lambda p: p.name,
    )


def list_pdfs(root: Path) -> list[Path]:
    """Every `*.pdf` under `root`, skipping hidden folders and files, sorted by path."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if is_pdf_name(name):
                found.append(Path(dirpath) / name)
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def _open(pdf: Path) -> pdfium.PdfDocument:
    """Open a PDF. The caller must hold `_PDFIUM_LOCK` and close the document."""
    try:
        return pdfium.PdfDocument(str(pdf))
    except pdfium.PdfiumError as exc:
        raise PdfError(f"No se puede abrir «{pdf.name}»: no es un PDF válido.") from exc


def page_count(pdf: Path) -> int:
    with _PDFIUM_LOCK:
        doc = _open(pdf)
        try:
            return len(doc)
        finally:
            doc.close()


def _check_page(pdf: Path, number: int, count: int) -> None:
    if not 1 <= number <= count:
        raise PdfError(f"«{pdf.name}» tiene {count} páginas; la página {number} no existe.")


def render_page_jpeg(pdf: Path, n: int, width: int) -> bytes:
    """Page `n` (1-based) as a JPEG `width` pixels wide, rotation applied."""
    width = min(max(int(width), _MIN_WIDTH), _MAX_WIDTH)
    with _PDFIUM_LOCK:
        doc = _open(pdf)
        try:
            _check_page(pdf, n, len(doc))
            page = doc[n - 1]
            try:
                shown_width, _ = page.get_size()  # already includes /Rotate
                image = page.render(scale=width / shown_width).to_pil().convert("RGB")
            finally:
                page.close()
        finally:
            doc.close()
    if image.width != width:
        height = max(1, round(image.height * width / image.width))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=THUMB_JPEG_QUALITY)
    return buf.getvalue()


# --- names and sidecar files -------------------------------------------------


def section_filename(name: str) -> str:
    """The file name for a section: forbidden characters become "-", then `.pdf`."""
    cleaned = _FORBIDDEN_RE.sub("-", name)
    cleaned = _SPACES_RE.sub(" ", cleaned.strip()).strip(" .")
    if not cleaned:
        raise PdfError("El nombre de la sección no puede estar vacío.")
    return f"{cleaned}.pdf"


def sections_path(pdf: Path) -> Path:
    return pdf.parent / f"{pdf.stem}.secciones.json"


def boxes_path(pdf: Path) -> Path:
    return pdf.parent / f"{pdf.stem}.recuadros.json"


def _read_sidecar(path: Path, empty: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """The parsed sidecar and its version; a missing file gives `empty` and version ""."""
    version = file_version(path)
    if not version:
        return empty, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PdfError(f"«{path.name}» no es un JSON válido: revísalo a mano.") from exc
    if not isinstance(data, dict):
        raise PdfError(f"«{path.name}» no tiene el formato esperado.")
    return {**empty, **data}, version


def load_sections(pdf: Path) -> tuple[dict[str, Any], str]:
    return _read_sidecar(sections_path(pdf), {"secciones": [], "girar": []})


def load_boxes(pdf: Path) -> tuple[dict[str, Any], str]:
    return _read_sidecar(boxes_path(pdf), {"recuadros": []})


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


# --- validation --------------------------------------------------------------


def _page_number(value: Any, n_pages: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= n_pages:
        raise PdfError(f"La página {value} no existe: el PDF tiene {n_pages} páginas.")
    return value


def validate_sections(data: dict[str, Any], n_pages: int) -> dict[str, Any]:
    """Check the sections (D9) and return them normalised: sorted, names stripped."""
    secciones = data.get("secciones", [])
    girar = data.get("girar", [])
    if not isinstance(secciones, list) or not isinstance(girar, list):
        raise PdfError("El formato de las secciones no es válido.")

    clean: list[dict[str, Any]] = []
    for item in secciones:
        if not isinstance(item, dict) or not isinstance(item.get("nombre"), str):
            raise PdfError("Cada sección necesita un nombre.")
        nombre = item["nombre"].strip()
        section_filename(nombre)  # raises when the name is empty
        desde = _page_number(item.get("desde"), n_pages)
        hasta = _page_number(item.get("hasta"), n_pages)
        if desde > hasta:
            raise PdfError(f"La sección «{nombre}» empieza después de su última página.")
        clean.append({"nombre": nombre, "desde": desde, "hasta": hasta})
    clean.sort(key=lambda s: s["desde"])

    names: set[str] = set()
    previous: dict[str, Any] | None = None
    for section in clean:
        key = section_filename(section["nombre"]).lower()
        if key in names:
            raise PdfError(f"Hay dos secciones con el nombre «{section['nombre']}».")
        names.add(key)
        if previous is not None and section["desde"] <= previous["hasta"]:
            raise PdfError(
                f"Las secciones «{previous['nombre']}» y «{section['nombre']}» se solapan."
            )
        previous = section

    pages = sorted({_page_number(page, n_pages) for page in girar})
    return {"secciones": clean, "girar": pages}


def _number(item: dict[str, Any], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PdfError(f"Cada recuadro necesita «{key}» como número.")
    return float(value)


def validate_boxes(data: dict[str, Any]) -> dict[str, Any]:
    """Check the rectangles (D13) and return them normalised: colours lowercase, edges clamped."""
    recuadros = data.get("recuadros", [])
    if not isinstance(recuadros, list):
        raise PdfError("El formato de los recuadros no es válido.")

    clean: list[dict[str, Any]] = []
    for item in recuadros:
        if not isinstance(item, dict):
            raise PdfError("El formato de los recuadros no es válido.")
        pagina = item.get("pagina")
        if isinstance(pagina, bool) or not (
            pagina == "todas" or (isinstance(pagina, int) and pagina >= 1)
        ):
            raise PdfError("La página de un recuadro debe ser un número o «todas».")
        x, y = _number(item, "x"), _number(item, "y")
        ancho, alto = _number(item, "ancho"), _number(item, "alto")
        if x < 0 or y < 0 or ancho <= 0 or alto <= 0:
            raise PdfError("Un recuadro tiene una posición o un tamaño no válidos.")
        if x + ancho > 1 + _SLACK or y + alto > 1 + _SLACK:
            raise PdfError("Un recuadro se sale de la página.")
        x, y = min(x, 1.0), min(y, 1.0)
        ancho, alto = min(ancho, 1 - x), min(alto, 1 - y)
        if ancho <= 0 or alto <= 0:
            raise PdfError("Un recuadro se sale de la página.")
        color = item.get("color")
        if not isinstance(color, str) or not _COLOR_RE.match(color):
            raise PdfError("El color de un recuadro debe tener la forma #rrggbb.")
        clean.append(
            {
                "pagina": pagina,
                "x": x,
                "y": y,
                "ancho": ancho,
                "alto": alto,
                "color": color.lower(),
            }
        )
    return {"recuadros": clean}


def save_sections(pdf: Path, data: dict[str, Any], version: str) -> str:
    """Validate and write the sections sidecar; returns its new version."""
    clean = validate_sections(data, page_count(pdf))
    path = sections_path(pdf)
    check_version(path, version)
    atomic_write_text(path, _dump(clean))
    return file_version(path)


def save_boxes(pdf: Path, data: dict[str, Any], version: str) -> str:
    """Validate and write the rectangles sidecar; returns its new version."""
    clean = validate_boxes(data)
    path = boxes_path(pdf)
    check_version(path, version)
    atomic_write_text(path, _dump(clean))
    return file_version(path)


# --- splitting ---------------------------------------------------------------


def _section_bytes(source: pdfium.PdfDocument, desde: int, hasta: int, girar: set[int]) -> bytes:
    """The pages `desde`..`hasta` of `source` as a PDF, pages in `girar` turned 180°."""
    out = pdfium.PdfDocument.new()
    try:
        out.import_pages(source, list(range(desde - 1, hasta)))
        for offset, number in enumerate(range(desde, hasta + 1)):
            if number in girar:
                page = out[offset]
                try:
                    page.set_rotation((page.get_rotation() + 180) % 360)
                finally:
                    page.close()
        buf = io.BytesIO()
        out.save(buf)
        return buf.getvalue()
    finally:
        out.close()


def export_sections(root: Path, pdf: Path) -> list[Path]:
    """Write one PDF per section into `<folder>/<stem>/`; the old file of a name goes to trash."""
    data, _ = load_sections(pdf)
    clean = validate_sections(data, page_count(pdf))
    if not clean["secciones"]:
        raise PdfError("No hay secciones.")
    girar = set(clean["girar"])
    folder = pdf.parent / pdf.stem
    written: list[Path] = []
    for section in clean["secciones"]:
        with _PDFIUM_LOCK:
            source = _open(pdf)
            try:
                content = _section_bytes(source, section["desde"], section["hasta"], girar)
            finally:
                source.close()
        target = folder / section_filename(section["nombre"])
        if target.exists():
            move_to_trash(root, target)
        atomic_write_bytes(target, content)
        written.append(target)
    return written


# --- anonymizing ---------------------------------------------------------------


def _rgb(color: str) -> tuple[int, int, int]:
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))


def _flatten_page(source: pdfium.PdfDocument, number: int, boxes: list[dict[str, Any]]) -> bytes:
    """Page `number` rendered at ANON_DPI with `boxes` painted on it, as a one-page PDF.

    The caller must hold `_PDFIUM_LOCK`.
    """
    page = source[number - 1]
    try:
        image = page.render(scale=ANON_DPI / 72).to_pil().convert("RGB")
    finally:
        page.close()
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for box in boxes:
        if box["pagina"] != "todas" and box["pagina"] != number:
            continue
        x0 = round(box["x"] * width)
        y0 = round(box["y"] * height)
        x1 = max(x0, round((box["x"] + box["ancho"]) * width) - 1)
        y1 = max(y0, round((box["y"] + box["alto"]) * height) - 1)
        draw.rectangle([x0, y0, x1, y1], fill=_rgb(box["color"]))
    buf = io.BytesIO()
    image.save(buf, "PDF", resolution=ANON_DPI, quality=ANON_JPEG_QUALITY)
    return buf.getvalue()


def anonymize(root: Path, pdf: Path, boxes: list[dict[str, Any]]) -> tuple[Path, list[str]]:
    """Write a flattened copy of `pdf` with `boxes` painted over it, in `anonimizados/`.

    Returns the output path and warnings for boxes on pages the PDF does not have.
    """
    clean = validate_boxes({"recuadros": boxes})["recuadros"]
    if not clean:
        raise PdfError("No hay recuadros.")
    out_path = pdf.parent / ANON_DIR / pdf.name
    warnings: list[str] = []
    with _PDFIUM_LOCK:
        source = _open(pdf)
        result = pdfium.PdfDocument.new()
        try:
            count = len(source)
            missing = sorted(
                {b["pagina"] for b in clean if isinstance(b["pagina"], int) and b["pagina"] > count}
            )
            warnings = [f"{pdf.name} no tiene página {number}." for number in missing]
            for number in range(1, count + 1):
                one_page = io.BytesIO(_flatten_page(source, number, clean))
                single = pdfium.PdfDocument(one_page)
                try:
                    result.import_pages(single)
                finally:
                    single.close()
            buf = io.BytesIO()
            result.save(buf)
            content = buf.getvalue()
        finally:
            result.close()
            source.close()
    if out_path.exists():
        move_to_trash(root, out_path)
    atomic_write_bytes(out_path, content)
    return out_path, warnings


def anonymize_folder(root: Path, pdf: Path) -> tuple[list[Path], list[str]]:
    """Apply the rectangles saved for `pdf` to every `*.pdf` directly in its folder."""
    data, _ = load_boxes(pdf)
    boxes = validate_boxes(data)["recuadros"]
    if not boxes:
        raise PdfError("No hay recuadros.")
    targets = folder_pdfs(pdf.parent)
    outputs: list[Path] = []
    warnings: list[str] = []
    for target in targets:
        out_path, notices = anonymize(root, target, boxes)
        outputs.append(out_path)
        warnings.extend(notices)
    return outputs, warnings
