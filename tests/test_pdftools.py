import io
import json
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from PIL import Image

from correctron import pdftools
from correctron.fsutil import VersionConflict
from correctron.pdftools import PdfError


def make_pdf(path: Path, pages: int, rotations: dict[int, int] | None = None) -> Path:
    """A PDF of `pages` A4 blank pages; `rotations` maps 1-based page numbers to /Rotate."""
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(595, 842)
    for number, degrees in (rotations or {}).items():
        doc[number - 1].set_rotation(degrees)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()
    return path


def pixel_rgb(pdf: Path, page_number: int, x: float, y: float) -> tuple[int, int, int]:
    """RGB of the pixel at fractions (x, y) of page `page_number` rendered at 100 dpi."""
    doc = pdfium.PdfDocument(str(pdf))
    try:
        image = doc[page_number - 1].render(scale=100 / 72).to_pil().convert("RGB")
        return image.getpixel((int(x * image.width), int(y * image.height)))
    finally:
        doc.close()


def test_list_pdfs_skips_hidden_folders_and_sorts(tmp_path):
    make_pdf(tmp_path / "b.pdf", 1)
    make_pdf(tmp_path / "sub" / "a.pdf", 1)
    make_pdf(tmp_path / ".papelera" / "x.pdf", 1)
    (tmp_path / "notas.txt").write_text("no es pdf")
    assert pdftools.list_pdfs(tmp_path) == [tmp_path / "b.pdf", tmp_path / "sub" / "a.pdf"]


def test_upper_case_extension_counts_as_pdf(tmp_path):
    make_pdf(tmp_path / "ESCANEO.PDF", 1)
    make_pdf(tmp_path / "a.pdf", 1)
    assert pdftools.list_pdfs(tmp_path) == [tmp_path / "ESCANEO.PDF", tmp_path / "a.pdf"]
    assert pdftools.folder_pdfs(tmp_path) == [tmp_path / "ESCANEO.PDF", tmp_path / "a.pdf"]


def test_page_count(tmp_path):
    assert pdftools.page_count(make_pdf(tmp_path / "x.pdf", 5)) == 5


def test_page_count_rejects_broken_file(tmp_path):
    broken = tmp_path / "roto.pdf"
    broken.write_bytes(b"esto no es un pdf")
    with pytest.raises(PdfError):
        pdftools.page_count(broken)


def test_render_page_jpeg_returns_jpeg_of_requested_width(tmp_path):
    pdf = make_pdf(tmp_path / "x.pdf", 3)
    data = pdftools.render_page_jpeg(pdf, 2, 220)
    assert data.startswith(b"\xff\xd8")
    assert Image.open(io.BytesIO(data)).width == 220


def test_render_page_jpeg_clamps_width(tmp_path):
    pdf = make_pdf(tmp_path / "x.pdf", 1)
    assert Image.open(io.BytesIO(pdftools.render_page_jpeg(pdf, 1, 5))).width == 100
    assert Image.open(io.BytesIO(pdftools.render_page_jpeg(pdf, 1, 9999))).width == 2000


def test_render_page_jpeg_rejects_page_out_of_range(tmp_path):
    pdf = make_pdf(tmp_path / "x.pdf", 3)
    with pytest.raises(PdfError):
        pdftools.render_page_jpeg(pdf, 0, 220)
    with pytest.raises(PdfError):
        pdftools.render_page_jpeg(pdf, 4, 220)


def test_section_filename_replaces_forbidden_characters():
    assert pdftools.section_filename("Ana / López: 1") == "Ana - López- 1.pdf"


def test_section_filename_keeps_accents_and_strips_edges():
    assert pdftools.section_filename(" Álvarez López, Ana ") == "Álvarez López, Ana.pdf"


def test_section_filename_rejects_empty_name():
    with pytest.raises(PdfError):
        pdftools.section_filename("  ")


def test_sidecar_paths_follow_the_naming_rule(tmp_path):
    pdf = tmp_path / "examenes.pdf"
    assert pdftools.sections_path(pdf) == tmp_path / "examenes.secciones.json"
    assert pdftools.boxes_path(pdf) == tmp_path / "examenes.recuadros.json"


def test_validate_sections_normalises_and_sorts():
    data = {
        "secciones": [
            {"nombre": "Fernández", "desde": 5, "hasta": 8},
            {"nombre": " Álvarez ", "desde": 1, "hasta": 4},
        ],
        "girar": [6, 2, 6],
    }
    result = pdftools.validate_sections(data, 8)
    assert result == {
        "secciones": [
            {"nombre": "Álvarez", "desde": 1, "hasta": 4},
            {"nombre": "Fernández", "desde": 5, "hasta": 8},
        ],
        "girar": [2, 6],
    }


@pytest.mark.parametrize(
    "secciones",
    [
        [{"nombre": "A", "desde": 1, "hasta": 4}, {"nombre": "B", "desde": 4, "hasta": 6}],
        [{"nombre": "A", "desde": 1, "hasta": 9}],
        [{"nombre": "A", "desde": 3, "hasta": 2}],
        [{"nombre": "Ana", "desde": 1, "hasta": 1}, {"nombre": "ana", "desde": 2, "hasta": 2}],
        [{"nombre": "   ", "desde": 1, "hasta": 1}],
    ],
    ids=["solapa", "fuera-de-rango", "desde-mayor", "nombre-repetido", "nombre-vacio"],
)
def test_validate_sections_rejects_invalid_sections(secciones):
    with pytest.raises(PdfError):
        pdftools.validate_sections({"secciones": secciones, "girar": []}, 8)


def test_validate_boxes_lowercases_colour_and_rejects_bad_input():
    ok = {"pagina": "todas", "x": 0.1, "y": 0.1, "ancho": 0.2, "alto": 0.1, "color": "#FF0000"}
    assert pdftools.validate_boxes({"recuadros": [ok]})["recuadros"][0]["color"] == "#ff0000"
    with pytest.raises(PdfError):
        pdftools.validate_boxes({"recuadros": [{**ok, "x": 0.9}]})
    with pytest.raises(PdfError):
        pdftools.validate_boxes({"recuadros": [{**ok, "color": "red"}]})
    with pytest.raises(PdfError):
        pdftools.validate_boxes({"recuadros": [{**ok, "pagina": 0}]})


def test_save_and_load_sections_write_the_d8_format(tmp_path):
    pdf = make_pdf(tmp_path / "examenes.pdf", 8)
    data = {"secciones": [{"nombre": "Ana", "desde": 1, "hasta": 4}], "girar": [6]}
    version = pdftools.save_sections(pdf, data, "")
    assert version
    written = json.loads((tmp_path / "examenes.secciones.json").read_text(encoding="utf-8"))
    assert written == data
    loaded, loaded_version = pdftools.load_sections(pdf)
    assert loaded == data
    assert loaded_version == version


def test_load_sections_without_sidecar_is_empty(tmp_path):
    pdf = make_pdf(tmp_path / "examenes.pdf", 2)
    assert pdftools.load_sections(pdf) == ({"secciones": [], "girar": []}, "")
    assert pdftools.load_boxes(pdf) == ({"recuadros": []}, "")


def test_save_sections_with_stale_version_raises_conflict(tmp_path):
    pdf = make_pdf(tmp_path / "examenes.pdf", 2)
    pdftools.save_sections(pdf, {"secciones": [], "girar": []}, "")
    with pytest.raises(VersionConflict):
        pdftools.save_sections(pdf, {"secciones": [], "girar": []}, "stale")


def test_save_boxes_round_trip(tmp_path):
    pdf = make_pdf(tmp_path / "examenes.pdf", 2)
    box = {"pagina": 2, "x": 0.1, "y": 0.1, "ancho": 0.2, "alto": 0.1, "color": "#000000"}
    version = pdftools.save_boxes(pdf, {"recuadros": [box]}, "")
    data, loaded_version = pdftools.load_boxes(pdf)
    assert data == {"recuadros": [box]}
    assert loaded_version == version


def test_export_sections_writes_one_pdf_per_section_with_rotation(tmp_path):
    pdf = make_pdf(tmp_path / "examen.pdf", 6)
    pdftools.save_sections(
        pdf,
        {
            "secciones": [
                {"nombre": "Uno", "desde": 1, "hasta": 2},
                {"nombre": "Dos", "desde": 3, "hasta": 6},
            ],
            "girar": [3],
        },
        "",
    )
    outputs = pdftools.export_sections(tmp_path, pdf)
    assert outputs == [tmp_path / "examen" / "Uno.pdf", tmp_path / "examen" / "Dos.pdf"]
    first = pdfium.PdfDocument(str(outputs[0]))
    second = pdfium.PdfDocument(str(outputs[1]))
    try:
        assert len(first) == 2
        assert len(second) == 4
        assert second[0].get_rotation() == 180
        assert second[1].get_rotation() == 0
    finally:
        first.close()
        second.close()


def test_export_sections_moves_previous_output_to_trash(tmp_path):
    pdf = make_pdf(tmp_path / "examen.pdf", 2)
    pdftools.save_sections(
        pdf, {"secciones": [{"nombre": "Uno", "desde": 1, "hasta": 2}], "girar": []}, ""
    )
    pdftools.export_sections(tmp_path, pdf)
    pdftools.export_sections(tmp_path, pdf)
    assert (tmp_path / "examen" / "Uno.pdf").is_file()
    assert len(list((tmp_path / ".papelera").rglob("Uno.pdf"))) == 1


def test_export_sections_without_sections_is_an_error(tmp_path):
    pdf = make_pdf(tmp_path / "examen.pdf", 2)
    with pytest.raises(PdfError, match="No hay secciones"):
        pdftools.export_sections(tmp_path, pdf)


def test_anonymize_flattens_rectangles_on_every_page(tmp_path):
    pdf = make_pdf(tmp_path / "examen.pdf", 3)
    boxes = [{"pagina": "todas", "x": 0, "y": 0, "ancho": 0.5, "alto": 0.5, "color": "#ff0000"}]
    out, warnings = pdftools.anonymize(tmp_path, pdf, boxes)
    assert out == tmp_path / "anonimizados" / "examen.pdf"
    assert warnings == []
    original = pdfium.PdfDocument(str(pdf))
    result = pdfium.PdfDocument(str(out))
    try:
        assert len(result) == len(original) == 3
        for i in range(3):
            w0, h0 = original[i].get_size()
            w1, h1 = result[i].get_size()
            assert abs(w0 - w1) <= 1 and abs(h0 - h1) <= 1
    finally:
        original.close()
        result.close()
    inside = pixel_rgb(out, 2, 0.25, 0.25)
    assert all(abs(c - t) <= 20 for c, t in zip(inside, (255, 0, 0), strict=True))
    outside = pixel_rgb(out, 2, 0.75, 0.75)
    assert all(c >= 235 for c in outside)


def test_anonymize_warns_about_pages_that_do_not_exist(tmp_path):
    pdf = make_pdf(tmp_path / "corto.pdf", 1)
    boxes = [{"pagina": 3, "x": 0, "y": 0, "ancho": 0.1, "alto": 0.1, "color": "#000000"}]
    out, warnings = pdftools.anonymize(tmp_path, pdf, boxes)
    assert out.is_file()
    assert warnings == ["corto.pdf no tiene página 3."]


def test_anonymize_replaces_previous_output_through_trash(tmp_path):
    pdf = make_pdf(tmp_path / "examen.pdf", 1)
    boxes = [{"pagina": 1, "x": 0, "y": 0, "ancho": 0.1, "alto": 0.1, "color": "#000000"}]
    pdftools.anonymize(tmp_path, pdf, boxes)
    pdftools.anonymize(tmp_path, pdf, boxes)
    assert len(list((tmp_path / ".papelera").rglob("examen.pdf"))) == 1


def test_anonymize_without_rectangles_is_an_error(tmp_path):
    pdf = make_pdf(tmp_path / "examen.pdf", 1)
    with pytest.raises(PdfError, match="No hay recuadros"):
        pdftools.anonymize(tmp_path, pdf, [])


def test_anonymize_folder_applies_saved_rectangles_to_every_pdf(tmp_path):
    make_pdf(tmp_path / "corto.pdf", 1)
    largo = make_pdf(tmp_path / "largo.pdf", 3)
    box = {"pagina": 3, "x": 0.1, "y": 0.1, "ancho": 0.2, "alto": 0.1, "color": "#000000"}
    pdftools.save_boxes(largo, {"recuadros": [box]}, "")
    outputs, warnings = pdftools.anonymize_folder(tmp_path, largo)
    assert outputs == [
        tmp_path / "anonimizados" / "corto.pdf",
        tmp_path / "anonimizados" / "largo.pdf",
    ]
    assert all(path.is_file() for path in outputs)
    assert len(warnings) == 1
    assert "corto.pdf" in warnings[0]
