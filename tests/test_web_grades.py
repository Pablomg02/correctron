import json
import re

from conftest import oob_value, row_html

from correctron.fsutil import file_version

S = "mecanica-de-vuelo"
E = f"/a/{S}/e/parcial-1"


def notas(sample_data, name):
    return sample_data / S / "parcial-1" / "notas" / f"{name}.csv"


def sheet_version(client, name):
    return oob_value(client.get(f"{E}?tab=notas&corrector={name}").text, "version-hoja")


def test_grid_has_group_header_and_subtotal(client):
    resp = client.get(f"{E}?tab=notas&corrector=pablo")
    assert resp.status_code == 200
    assert ">ej1<" in resp.text
    ana = row_html(resp.text, "alvarez-lopez-ana")
    assert re.search(r'id="sub-alvarez-lopez-ana-ej1"[^>]*>3,5<', ana)
    assert re.search(r'id="total-alvarez-lopez-ana"[^>]*>9<', ana)
    assert 'id="c-alvarez-lopez-ana-ej1a"' in ana
    lucia = row_html(resp.text, "garcia-perez-lucia")
    assert "parcial" in lucia
    assert 'hx-sync="this:queue all"' in resp.text


def test_default_sheet_is_final(client):
    resp = client.get(f"{E}?tab=notas")
    assert 'id="origen-alvarez-lopez-ana"' in resp.text
    assert oob_value(resp.text, "version-hoja") != ""


def test_np_row_is_disabled(client):
    resp = client.get(f"{E}?tab=notas&corrector=pablo")
    diego = row_html(resp.text, "martinez-souto-diego")
    assert "NP" in diego
    assert "disabled" in diego


def test_save_row_returns_only_oob(client, sample_data):
    resp = client.post(
        f"{E}/notas/pablo/garcia-perez-lucia",
        data={"ej2": "3", "ej3": "2,5", "version": sheet_version(client, "pablo")},
    )
    assert resp.status_code == 200
    assert 'id="total-garcia-perez-lucia"' in resp.text
    total = resp.text.split('id="total-garcia-perez-lucia"', 1)[1].split("</span>", 1)[0]
    assert "9,5" in total
    assert 'id="sub-garcia-perez-lucia-ej1"' in resp.text
    assert '<input id="c-garcia-perez-lucia-ej2"' not in resp.text
    assert "c-garcia-perez-lucia-ej2" not in resp.text
    assert 'id="err-garcia-perez-lucia"' in resp.text
    assert "hx-retarget" not in resp.headers
    assert 'garcia-perez-lucia,"García Pérez, Lucía",2,2,3,2.5,9.5,\n' in notas(
        sample_data, "pablo"
    ).read_text(encoding="utf-8")


def test_invalid_value_rerenders_row(client, sample_data):
    before = notas(sample_data, "pablo").read_bytes()
    resp = client.post(
        f"{E}/notas/pablo/garcia-perez-lucia",
        data={"ej2": "7", "version": sheet_version(client, "pablo")},
    )
    assert resp.status_code == 200
    assert resp.headers["hx-retarget"] == "#fila-garcia-perez-lucia"
    assert resp.headers["hx-reswap"] == "outerHTML"
    row = row_html(resp.text, "garcia-perez-lucia")
    assert 'aria-invalid="true"' in row
    assert 'value="7"' in row
    assert "Fuera de rango" in row
    assert notas(sample_data, "pablo").read_bytes() == before


def test_consecutive_saves_thread_version(client, sample_data):
    resp = client.post(
        f"{E}/notas/pablo/garcia-perez-lucia",
        data={"ej2": "3", "version": sheet_version(client, "pablo")},
    )
    assert resp.status_code == 200
    resp = client.post(
        f"{E}/notas/pablo/garcia-perez-lucia",
        data={"ej3": "1", "version": oob_value(resp.text, "version-hoja")},
    )
    assert resp.status_code == 200
    resp = client.post(
        f"{E}/notas/pablo/otero-vidal-sara",
        data={"ej1a": "1", "version": oob_value(resp.text, "version-hoja")},
    )
    assert resp.status_code == 200
    assert oob_value(resp.text, "version-hoja") == file_version(notas(sample_data, "pablo"))


def test_stale_version_is_409(client, sample_data):
    before = notas(sample_data, "pablo").read_bytes()
    resp = client.post(
        f"{E}/notas/pablo/garcia-perez-lucia",
        data={"ej2": "3", "version": "0" * 16},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 409
    assert notas(sample_data, "pablo").read_bytes() == before


def test_create_grader(client, sample_data):
    resp = client.post(f"{E}/correctores", data={"nombre": "Claude Opus"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"{E}?tab=notas&corrector=claude-opus"
    assert (
        notas(sample_data, "claude-opus").read_text(encoding="utf-8")
        == "id,alumno,ej1a,ej1b,ej2,ej3,total,comentario\n"
    )


def test_create_grader_final_is_400(client):
    assert client.post(f"{E}/correctores", data={"nombre": "final"}).status_code == 400


def test_feedback_dialog_and_save(client, sample_data):
    url = f"{E}/notas/pablo/alvarez-lopez-ana/feedback"
    resp = client.get(url)
    assert resp.status_code == 200
    assert "<textarea" in resp.text
    resp = client.post(url, data={"texto": "Muy bien razonado.", "version": ""})
    assert resp.status_code == 200
    path = sample_data / S / "parcial-1" / "notas" / "pablo" / "alvarez-lopez-ana.md"
    assert path.read_text(encoding="utf-8") == "Muy bien razonado.\n"
    assert 'id="fb-alvarez-lopez-ana"' in resp.text
    assert "hx-swap-oob" in resp.text
    assert resp.headers["hx-trigger"] == "cerrar-feedback"


def test_feedback_button_shows_existing_file(client):
    resp = client.get(f"{E}?tab=notas&corrector=claude")
    ana = row_html(resp.text, "alvarez-lopez-ana")
    assert "fb-lleno" in ana


def test_save_final_sets_manual(client, sample_data):
    resp = client.post(
        f"{E}/notas/final/alvarez-lopez-ana",
        data={"ej2": "2", "version": sheet_version(client, "final")},
    )
    assert resp.status_code == 200
    assert 'id="origen-alvarez-lopez-ana"' in resp.text
    assert "manual" in resp.text
    text = notas(sample_data, "final").read_text(encoding="utf-8")
    assert 'alvarez-lopez-ana,"Álvarez López, Ana",2,1.5,2,2.5,8,Muy bien,manual\n' in text


def test_final_with_revisions_warns(client):
    resp = client.get(f"{E}?tab=notas&corrector=final")
    assert "Hay revisiones posteriores" in resp.text


def test_rows_outside_roster_are_listed(client, sample_data):
    path = notas(sample_data, "pablo")
    path.write_text(
        path.read_text(encoding="utf-8") + 'perez-castro-hugo,"Pérez Castro, Hugo",1,1,1,1,4,\n',
        encoding="utf-8",
    )
    resp = client.get(f"{E}?tab=notas&corrector=pablo")
    assert "Fuera de la lista" in resp.text
    outside = resp.text.split("Fuera de la lista", 1)[1]
    assert "perez-castro-hugo" in outside


def test_invalid_file_value_is_marked(client, sample_data):
    path = notas(sample_data, "pablo")
    path.write_text(
        path.read_text(encoding="utf-8").replace(",1,1,2,1.5,", ",1,abc,2,1.5,"), encoding="utf-8"
    )
    resp = client.get(f"{E}?tab=notas&corrector=pablo")
    carlos = row_html(resp.text, "fernandez-rey-carlos")
    assert 'value="abc"' in carlos
    assert 'aria-invalid="true"' in carlos


def test_manual_mode_has_total_input(client, sample_data):
    cfg = sample_data / S / "parcial-1" / "config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["calculo_total"] = "manual"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    resp = client.get(f"{E}?tab=notas&corrector=pablo")
    assert 'id="c-alvarez-lopez-ana-total"' in row_html(resp.text, "alvarez-lopez-ana")
    resp = client.post(
        f"{E}/notas/pablo/garcia-perez-lucia",
        data={"total": "6,75", "version": sheet_version(client, "pablo")},
    )
    assert resp.status_code == 200
    assert ",6.75," in notas(sample_data, "pablo").read_text(encoding="utf-8")


def test_unknown_sheet_is_404(client):
    assert client.get(f"{E}?tab=notas&corrector=nadie").status_code == 404


def test_grid_shows_numbers_with_decimal_comma_and_saves_them_canonical(client, sample_data):
    """File values are shown as the user types them (1,5); saving the row writes 1.5 again."""
    ana = row_html(client.get(f"{E}?tab=notas&corrector=pablo").text, "alvarez-lopez-ana")
    assert re.search(r'id="c-alvarez-lopez-ana-ej1b"[^>]*value="1,5"', ana)
    assert re.search(r'id="c-alvarez-lopez-ana-comentario"[^>]*value="Muy bien"', ana)
    resp = client.post(
        f"{E}/notas/pablo/alvarez-lopez-ana",
        data={
            "ej1a": "2",
            "ej1b": "1,5",
            "ej2": "3",
            "ej3": "2,5",
            "comentario": "Muy bien",
            "version": sheet_version(client, "pablo"),
        },
    )
    assert resp.status_code == 200
    text = notas(sample_data, "pablo").read_text(encoding="utf-8")
    assert 'alvarez-lopez-ana,"Álvarez López, Ana",2,1.5,3,2.5,9,Muy bien' in text


def test_malformed_sheet_is_shown_read_only(client, sample_data):
    """A sheet with more cells than its header cannot be saved, so its inputs are disabled."""
    path = notas(sample_data, "pablo")
    path.write_text(path.read_text(encoding="utf-8") + "otero-vidal-sara,x,1,1,1,1,4,,extra\n")
    resp = client.get(f"{E}?tab=notas&corrector=pablo")
    assert "más celdas que la cabecera" in resp.text
    ana = row_html(resp.text, "alvarez-lopez-ana")
    assert re.search(r'<input id="c-alvarez-lopez-ana-ej2"[^>]*\bdisabled\b', ana)
    ana_ok = row_html(client.get(f"{E}?tab=notas&corrector=claude").text, "alvarez-lopez-ana")
    assert not re.search(r'<input id="c-alvarez-lopez-ana-ej2"[^>]*\bdisabled\b', ana_ok)
