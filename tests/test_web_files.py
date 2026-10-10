from decimal import Decimal

from conftest import oob_value

from correctron.fsutil import tree_fingerprint
from correctron.web.app import create_app, nota

EXAM = "mecanica-de-vuelo/parcial-1"


def test_pdf_is_served_inline(client):
    resp = client.get(f"/archivo/{EXAM}/enunciado/enunciado.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" not in resp.headers.get("content-disposition", "")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.content.startswith(b"%PDF-")


def test_html_upload_is_an_attachment(client, sample_data):
    target = sample_data / EXAM / "enunciado" / "x.html"
    target.write_text("<script>alert(1)</script>", encoding="utf-8")
    resp = client.get(f"/archivo/{EXAM}/enunciado/x.html")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert not resp.headers["content-type"].startswith("text/html")


def test_encoded_dot_dot_is_rejected(client):
    assert client.get("/archivo/%2e%2e/%2e%2e/etc/passwd").status_code == 404


def test_symlink_to_outside_is_rejected(client, sample_data, tmp_path):
    outside = tmp_path / "secreto.txt"
    outside.write_text("secreto", encoding="utf-8")
    (sample_data / "enlace.txt").symlink_to(outside)
    resp = client.get("/archivo/enlace.txt")
    assert resp.status_code == 404
    assert "secreto" not in resp.text


def test_missing_file_is_404(client):
    assert client.get(f"/archivo/{EXAM}/enunciado/nada.pdf").status_code == 404


def test_markdown_is_plain_text_inline(client):
    resp = client.get(f"/archivo/{EXAM}/notas/claude/alvarez-lopez-ana.md")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/plain; charset=utf-8"
    assert "attachment" not in resp.headers.get("content-disposition", "")
    assert "Álvarez López" in resp.text


def test_huella_unchanged_then_changed(client, sample_data):
    huella = tree_fingerprint(sample_data / EXAM)
    resp = client.get("/api/huella", params={"ruta": EXAM, "huella": huella})
    assert resp.status_code == 204
    (sample_data / EXAM / "notas" / "pablo.csv").write_text("id\n", encoding="utf-8")
    resp = client.get("/api/huella", params={"ruta": EXAM, "huella": huella})
    assert resp.status_code == 200
    assert "Recargar" in resp.text
    assert "Hay cambios en los archivos hechos fuera de la web." in resp.text


def test_huella_outside_root_is_404(client):
    assert client.get("/api/huella", params={"ruta": "../..", "huella": "x"}).status_code == 404


def test_vendored_assets_are_served(client):
    for path in (
        "/static/vendor/htmx.min.js",
        "/static/vendor/alpine.min.js",
        "/static/vendor/pico.min.css",
        "/static/app.css",
        "/static/app.js",
    ):
        assert client.get(path).status_code == 200, path


def test_create_app_writes_leeme(tmp_path):
    root = tmp_path / "nuevo"
    create_app(root)
    assert (root / "LEEME.md").is_file()


def test_nota_filter():
    assert nota(Decimal("9.50"), 2) == "9,5"
    assert nota(Decimal("6"), 2) == "6"
    assert nota(Decimal("6.125"), 2) == "6,13"
    assert nota(None, 2) == "—"


def test_home_page_has_layout_and_state(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert '<html lang="es"' in resp.text
    assert 'id="avisos"' in resp.text
    assert "/static/vendor/htmx.min.js" in resp.text


def test_subject_page_embeds_fingerprint(client, sample_data):
    resp = client.get("/a/mecanica-de-vuelo")
    assert oob_value(resp.text, "huella-actual") == tree_fingerprint(
        sample_data / "mecanica-de-vuelo"
    )
    assert 'hx-trigger="every 3s"' in resp.text


def test_not_found_page_is_html(client):
    resp = client.get("/a/no-existe")
    assert resp.status_code == 404
    assert "no-existe" in resp.text
    assert resp.headers["content-type"].startswith("text/html")


def test_htmx_error_is_a_fragment(client):
    resp = client.get("/a/no-existe", headers={"HX-Request": "true"})
    assert resp.status_code == 404
    assert "<html" not in resp.text
    assert "banner" in resp.text


def test_favicon_is_served(client):
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/svg+xml"


def test_theme_follows_the_os(client):
    resp = client.get("/")
    assert 'data-theme="light"' not in resp.text
    css = client.get("/static/app.css").text
    assert "prefers-color-scheme: dark" in css
