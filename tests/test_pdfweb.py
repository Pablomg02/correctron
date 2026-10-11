import json
import re
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from correctron.fsutil import PathOutsideData, VersionConflict, file_version
from correctron.pdftools import PdfError, page_count
from correctron.pdfweb.app import create_app
from correctron.pdfweb.routes import resolve_pdf


def make_pdf(path: Path, pages: int) -> Path:
    """A PDF of `pages` blank A4 pages at `path` (parent folders are created)."""
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(595, 842)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def pdf_root(tmp_path: Path) -> Path:
    """Data folder with examenes.pdf (3 pages) and a hidden .papelera/x.pdf."""
    root = tmp_path / "pdfs"
    make_pdf(root / "examenes.pdf", 3)
    make_pdf(root / ".papelera" / "x.pdf", 1)
    return root


@pytest.fixture
def pdf_client(pdf_root: Path) -> TestClient:
    return TestClient(create_app(pdf_root))


def test_home_lists_pdfs_with_links_and_hides_trash(pdf_client):
    response = pdf_client.get("/")
    assert response.status_code == 200
    assert "examenes.pdf" in response.text
    assert "3 páginas" in response.text
    assert "/dividir?pdf=examenes.pdf" in response.text
    assert "/anonimizar?pdf=examenes.pdf" in response.text
    assert "x.pdf" not in response.text


def test_home_empty_state_names_the_folder(tmp_path):
    root = tmp_path / "vacia"
    response = TestClient(create_app(root)).get("/")
    assert response.status_code == 200
    assert "No hay PDFs." in response.text
    assert str(root.resolve()) in response.text


def test_pagina_returns_a_jpeg(pdf_client):
    response = pdf_client.get("/pagina", params={"pdf": "examenes.pdf", "n": 1, "ancho": 220})
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-cache"
    assert response.content.startswith(b"\xff\xd8")


@pytest.mark.parametrize("page", [0, 4])
def test_pagina_rejects_pages_out_of_range(pdf_client, page):
    response = pdf_client.get("/pagina", params={"pdf": "examenes.pdf", "n": page, "ancho": 220})
    assert response.status_code == 400


def test_pagina_refuses_paths_outside_the_root(tmp_path, pdf_root, pdf_client):
    make_pdf(tmp_path / "x.pdf", 1)
    response = pdf_client.get("/pagina", params={"pdf": "../x.pdf", "n": 1, "ancho": 220})
    assert response.status_code == 404


def test_archivo_serves_a_pdf_inline(pdf_client):
    response = pdf_client.get("/archivo/examenes.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")


def test_archivo_refuses_files_that_are_not_pdf(pdf_root, pdf_client):
    (pdf_root / "notas.txt").write_text("no es un pdf", encoding="utf-8")
    assert pdf_client.get("/archivo/notas.txt").status_code == 404
    assert pdf_client.get("/archivo/no-existe.pdf").status_code == 404


def test_static_assets_are_served(pdf_client):
    assert pdf_client.get("/comun/vendor/alpine.min.js").status_code == 200
    assert pdf_client.get("/static/pdf.css").status_code == 200


def test_resolve_pdf_requires_an_existing_pdf(pdf_root):
    assert resolve_pdf(pdf_root, "examenes.pdf") == (pdf_root / "examenes.pdf").resolve()
    with pytest.raises(PdfError, match="No existe el PDF «no.pdf»."):
        resolve_pdf(pdf_root, "no.pdf")
    with pytest.raises(PathOutsideData):
        resolve_pdf(pdf_root, "../examenes.pdf")


@pytest.fixture
def error_client(pdf_root: Path) -> TestClient:
    """A client whose app has test-only routes raising each mapped exception."""
    app = create_app(pdf_root)

    @app.get("/api/pdf")
    def api_pdf():
        raise PdfError("Mensaje de prueba.")

    @app.get("/api/conflicto")
    def api_conflict():
        raise VersionConflict("x")

    @app.get("/api/fuera")
    def api_outside():
        raise PathOutsideData("x")

    @app.get("/html/pdf")
    def html_pdf():
        raise PdfError("Mensaje de prueba.")

    @app.get("/html/conflicto")
    def html_conflict():
        raise VersionConflict("x")

    return TestClient(app)


def test_api_errors_are_json(error_client):
    response = error_client.get("/api/pdf")
    assert response.status_code == 400
    assert response.json() == {"error": "Mensaje de prueba."}

    response = error_client.get("/api/conflicto")
    assert response.status_code == 409
    assert "recarga para ver la versión actual" in response.json()["error"]

    response = error_client.get("/api/fuera")
    assert response.status_code == 404
    assert "error" in response.json()


def test_page_errors_are_html(error_client):
    response = error_client.get("/html/pdf")
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Mensaje de prueba." in response.text

    response = error_client.get("/html/conflicto")
    assert response.status_code == 409
    assert "recarga para ver la versión actual" in response.text
    assert "Recargar" in response.text


# --- Dividir (T3) ----------------------------------------------------------------


def _estado(html: str) -> dict:
    """The JSON embedded in the #estado script of a page."""
    match = re.search(r'<script type="application/json" id="estado">(.*?)</script>', html, re.S)
    assert match, "the page has no #estado script"
    return json.loads(match.group(1))


SECCIONES_OK = {
    "secciones": [
        {"nombre": "Álvarez López, Ana", "desde": 1, "hasta": 4},
        {"nombre": "Fernández Rey, Carlos", "desde": 5, "hasta": 8},
    ],
    "girar": [6],
}


def test_dividir_embeds_the_state_and_loads_the_script(pdf_client):
    response = pdf_client.get("/dividir", params={"pdf": "examenes.pdf"})
    assert response.status_code == 200
    assert 'id="estado"' in response.text
    assert "dividir.js" in response.text
    assert _estado(response.text) == {
        "pdf": "examenes.pdf",
        "paginas": 3,
        "secciones": [],
        "girar": [],
        "version": "",
    }
    assert pdf_client.get("/static/dividir.js").status_code == 200


def test_dividir_embeds_saved_sections_and_their_version(pdf_root, pdf_client):
    sidecar = pdf_root / "examen.secciones.json"
    make_pdf(pdf_root / "examen.pdf", 8)
    sidecar.write_text(json.dumps(SECCIONES_OK, ensure_ascii=False), encoding="utf-8")
    response = pdf_client.get("/dividir", params={"pdf": "examen.pdf"})
    estado = _estado(response.text)
    assert estado["paginas"] == 8
    assert estado["secciones"] == SECCIONES_OK["secciones"]
    assert estado["girar"] == [6]
    assert estado["version"] == file_version(sidecar)


def test_dividir_unknown_pdf_is_a_page_error(pdf_client):
    response = pdf_client.get("/dividir", params={"pdf": "no.pdf"})
    assert response.status_code == 400
    assert "No existe el PDF «no.pdf»." in response.text


def test_put_secciones_writes_the_sidecar_and_returns_the_version(pdf_root, pdf_client):
    make_pdf(pdf_root / "examenes.pdf", 8)
    response = pdf_client.put(
        "/api/secciones", params={"pdf": "examenes.pdf"}, json={"version": "", **SECCIONES_OK}
    )
    assert response.status_code == 200
    version = response.json()["version"]
    sidecar = pdf_root / "examenes.secciones.json"
    assert version == file_version(sidecar)
    assert sidecar.read_text(encoding="utf-8") == (
        json.dumps(
            {
                "secciones": [
                    {"nombre": "Álvarez López, Ana", "desde": 1, "hasta": 4},
                    {"nombre": "Fernández Rey, Carlos", "desde": 5, "hasta": 8},
                ],
                "girar": [6],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def test_put_secciones_with_overlap_is_400_and_keeps_the_file(pdf_root, pdf_client):
    make_pdf(pdf_root / "examenes.pdf", 8)
    sidecar = pdf_root / "examenes.secciones.json"
    sidecar.write_text(json.dumps(SECCIONES_OK, ensure_ascii=False), encoding="utf-8")
    before = sidecar.read_bytes()
    overlapping = {
        "secciones": [
            {"nombre": "A", "desde": 1, "hasta": 2},
            {"nombre": "B", "desde": 2, "hasta": 3},
        ],
        "girar": [],
    }
    response = pdf_client.put(
        "/api/secciones",
        params={"pdf": "examenes.pdf"},
        json={"version": file_version(sidecar), **overlapping},
    )
    assert response.status_code == 400
    assert "error" in response.json()
    assert sidecar.read_bytes() == before


def test_put_secciones_with_a_stale_version_is_409(pdf_root, pdf_client):
    make_pdf(pdf_root / "examenes.pdf", 8)
    sidecar = pdf_root / "examenes.secciones.json"
    sidecar.write_text(json.dumps(SECCIONES_OK, ensure_ascii=False), encoding="utf-8")
    response = pdf_client.put(
        "/api/secciones",
        params={"pdf": "examenes.pdf"},
        json={"version": "0000000000000000", **SECCIONES_OK},
    )
    assert response.status_code == 409
    assert "recarga para ver la versión actual" in response.json()["error"]


def test_put_secciones_rejects_a_body_that_is_not_json(pdf_client):
    response = pdf_client.put(
        "/api/secciones",
        params={"pdf": "examenes.pdf"},
        content=b"no es json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert "error" in response.json()


def test_exportar_writes_one_pdf_per_section(pdf_root, pdf_client):
    make_pdf(pdf_root / "examen.pdf", 8)
    pdf_client.put(
        "/api/secciones",
        params={"pdf": "examen.pdf"},
        json={"version": "", **SECCIONES_OK},
    )
    response = pdf_client.post("/api/secciones/exportar", params={"pdf": "examen.pdf"})
    assert response.status_code == 200
    assert response.json() == {
        "archivos": ["examen/Álvarez López, Ana.pdf", "examen/Fernández Rey, Carlos.pdf"]
    }
    first = pdf_root / "examen" / "Álvarez López, Ana.pdf"
    second = pdf_root / "examen" / "Fernández Rey, Carlos.pdf"
    assert page_count(first) == 4
    assert page_count(second) == 4
    # Page 6 of the exam is the second page of the second section, turned 180 degrees.
    doc = pdfium.PdfDocument(str(second))
    try:
        assert doc[1].get_rotation() == 180
        assert doc[0].get_rotation() == 0
    finally:
        doc.close()


def test_exportar_without_sections_is_400(pdf_client):
    response = pdf_client.post("/api/secciones/exportar", params={"pdf": "examenes.pdf"})
    assert response.status_code == 400
    assert response.json() == {"error": "No hay secciones."}


# --- Anonimizar (T4) -------------------------------------------------------------

RECUADROS_OK = {
    "recuadros": [
        {"pagina": "todas", "x": 0.05, "y": 0.02, "ancho": 0.45, "alto": 0.06, "color": "#FFFFFF"},
        {"pagina": 3, "x": 0.6, "y": 0.9, "ancho": 0.3, "alto": 0.05, "color": "#000000"},
    ]
}


def test_anonimizar_embeds_the_state_and_loads_the_script(pdf_client):
    response = pdf_client.get("/anonimizar", params={"pdf": "examenes.pdf"})
    assert response.status_code == 200
    assert 'id="estado"' in response.text
    assert "anonimizar.js" in response.text
    assert _estado(response.text) == {
        "pdf": "examenes.pdf",
        "paginas": 3,
        "recuadros": [],
        "version": "",
    }
    assert pdf_client.get("/static/anonimizar.js").status_code == 200


def test_anonimizar_embeds_saved_rectangles_and_their_version(pdf_root, pdf_client):
    sidecar = pdf_root / "examenes.recuadros.json"
    sidecar.write_text(json.dumps(RECUADROS_OK), encoding="utf-8")
    response = pdf_client.get("/anonimizar", params={"pdf": "examenes.pdf"})
    estado = _estado(response.text)
    assert estado["recuadros"][0] == {
        "pagina": "todas",
        "x": 0.05,
        "y": 0.02,
        "ancho": 0.45,
        "alto": 0.06,
        "color": "#ffffff",
    }
    assert estado["version"] == file_version(sidecar)


def test_anonimizar_counts_the_pdfs_of_the_folder(pdf_root, pdf_client):
    make_pdf(pdf_root / "otro.pdf", 1)
    make_pdf(pdf_root / "carpeta" / "dentro.pdf", 1)
    response = pdf_client.get("/anonimizar", params={"pdf": "examenes.pdf"})
    assert "Aplicar a los 2 PDFs de esta carpeta" in response.text


def test_anonimizar_unknown_pdf_is_a_page_error(pdf_client):
    response = pdf_client.get("/anonimizar", params={"pdf": "no.pdf"})
    assert response.status_code == 400
    assert "No existe el PDF «no.pdf»." in response.text


def test_put_recuadros_writes_the_sidecar_with_lowercase_colours(pdf_root, pdf_client):
    response = pdf_client.put(
        "/api/recuadros", params={"pdf": "examenes.pdf"}, json={"version": "", **RECUADROS_OK}
    )
    assert response.status_code == 200
    sidecar = pdf_root / "examenes.recuadros.json"
    assert response.json() == {"version": file_version(sidecar)}
    assert sidecar.read_text(encoding="utf-8") == (
        json.dumps(
            {
                "recuadros": [
                    {
                        "pagina": "todas",
                        "x": 0.05,
                        "y": 0.02,
                        "ancho": 0.45,
                        "alto": 0.06,
                        "color": "#ffffff",
                    },
                    {
                        "pagina": 3,
                        "x": 0.6,
                        "y": 0.9,
                        "ancho": 0.3,
                        "alto": 0.05,
                        "color": "#000000",
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


@pytest.mark.parametrize(
    "recuadro",
    [
        {"pagina": 1, "x": 0.8, "y": 0.1, "ancho": 0.3, "alto": 0.1, "color": "#000000"},
        {"pagina": 1, "x": 0.1, "y": 0.1, "ancho": 0.3, "alto": 0.1, "color": "red"},
    ],
    ids=["se-sale-de-la-pagina", "color-con-nombre"],
)
def test_put_recuadros_rejects_invalid_rectangles(pdf_root, pdf_client, recuadro):
    response = pdf_client.put(
        "/api/recuadros",
        params={"pdf": "examenes.pdf"},
        json={"version": "", "recuadros": [recuadro]},
    )
    assert response.status_code == 400
    assert "error" in response.json()
    assert not (pdf_root / "examenes.recuadros.json").exists()


def test_put_recuadros_with_a_stale_version_is_409(pdf_root, pdf_client):
    sidecar = pdf_root / "examenes.recuadros.json"
    sidecar.write_text(json.dumps(RECUADROS_OK), encoding="utf-8")
    response = pdf_client.put(
        "/api/recuadros",
        params={"pdf": "examenes.pdf"},
        json={"version": "0000000000000000", **RECUADROS_OK},
    )
    assert response.status_code == 409
    assert "recarga para ver la versión actual" in response.json()["error"]


def test_anonimizar_one_pdf_writes_a_flattened_copy(pdf_root, pdf_client):
    pdf_client.put(
        "/api/recuadros", params={"pdf": "examenes.pdf"}, json={"version": "", **RECUADROS_OK}
    )
    response = pdf_client.post("/api/anonimizar", params={"pdf": "examenes.pdf", "todos": 0})
    assert response.status_code == 200
    assert response.json() == {"archivos": ["anonimizados/examenes.pdf"], "avisos": []}
    output = pdf_root / "anonimizados" / "examenes.pdf"
    assert page_count(output) == 3
    assert (pdf_root / "examenes.pdf").exists()


def test_anonimizar_folder_applies_the_rectangles_to_every_pdf(pdf_root, pdf_client):
    make_pdf(pdf_root / "otro.pdf", 1)
    rectangulo = {"pagina": 2, "x": 0.1, "y": 0.1, "ancho": 0.2, "alto": 0.1, "color": "#000000"}
    pdf_client.put(
        "/api/recuadros",
        params={"pdf": "examenes.pdf"},
        json={"version": "", "recuadros": [rectangulo]},
    )
    response = pdf_client.post("/api/anonimizar", params={"pdf": "examenes.pdf", "todos": 1})
    assert response.status_code == 200
    assert response.json() == {
        "archivos": ["anonimizados/examenes.pdf", "anonimizados/otro.pdf"],
        "avisos": ["otro.pdf no tiene página 2."],
    }
    assert page_count(pdf_root / "anonimizados" / "examenes.pdf") == 3
    assert page_count(pdf_root / "anonimizados" / "otro.pdf") == 1


def test_anonimizar_without_rectangles_is_400(pdf_client):
    for todos in (0, 1):
        response = pdf_client.post(
            "/api/anonimizar", params={"pdf": "examenes.pdf", "todos": todos}
        )
        assert response.status_code == 400
        assert response.json() == {"error": "No hay recuadros."}


def test_anonimizar_todos_must_be_0_or_1(pdf_root, pdf_client):
    pdf_client.put(
        "/api/recuadros", params={"pdf": "examenes.pdf"}, json={"version": "", **RECUADROS_OK}
    )
    response = pdf_client.post("/api/anonimizar", params={"pdf": "examenes.pdf", "todos": 2})
    assert response.status_code == 400
    assert "error" in response.json()
    assert not (pdf_root / "anonimizados").exists()
