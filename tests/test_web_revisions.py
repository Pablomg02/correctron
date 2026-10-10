from datetime import date

from conftest import oob_value, row_html

S = "mecanica-de-vuelo"
E = f"/a/{S}/e/parcial-1"
TODAY = date.today().isoformat()


def revision(sample_data, name):
    return sample_data / S / "parcial-1" / "revisiones" / name


def test_revision_table_shows_changes(client):
    resp = client.get(f"{E}?tab=revisiones")
    assert resp.status_code == 200
    carlos = row_html(resp.text, "fernandez-rey-carlos")
    assert "ej1b: 1 → 1,5" in carlos
    assert "5,5 → 6" in carlos
    assert "Apartado 1b mal sumado" in carlos
    assert "La nota vigente = final.csv + revisiones en orden." in resp.text


def test_new_revision_session(client, sample_data):
    resp = client.post(f"{E}/revisiones", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"{E}?tab=revisiones&rev=02-{TODAY}.csv"
    assert revision(sample_data, f"02-{TODAY}.csv").read_text(encoding="utf-8") == (
        "id,alumno,ej1a,ej1b,ej2,ej3,total,motivo\n"
    )


def form_version(client, rev, alumno):
    resp = client.get(f"{E}?tab=revisiones&rev={rev}&alumno={alumno}")
    assert resp.status_code == 200
    return oob_value(resp.text, "version-revision")


def test_revise_ana(client, sample_data):
    client.post(f"{E}/revisiones")
    rev = f"02-{TODAY}.csv"
    page = client.get(f"{E}?tab=revisiones&rev={rev}&alumno=alvarez-lopez-ana")
    assert 'value="2,5"' in page.text  # ej3 prefilled from final.csv, decimal comma
    resp = client.post(
        f"{E}/revisiones/{rev}/alvarez-lopez-ana",
        data={
            "ej1a": "2",
            "ej1b": "1.5",
            "ej2": "2,5",
            "ej3": "2.5",
            "motivo": "Recontado",
            "version": form_version(client, rev, "alvarez-lopez-ana"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith(f"{E}?tab=revisiones&rev={rev}")
    assert revision(sample_data, rev).read_text(encoding="utf-8") == (
        "id,alumno,ej1a,ej1b,ej2,ej3,total,motivo\n"
        'alvarez-lopez-ana,"Álvarez López, Ana",,,2.5,,8.5,Recontado\n'
    )
    summary = client.get(f"{E}?tab=resumen")
    ana = row_html(summary.text, "alvarez-lopez-ana")
    assert "8,5" in ana and "revisada" in ana


def test_blank_reason_is_rejected(client, sample_data):
    client.post(f"{E}/revisiones")
    rev = f"02-{TODAY}.csv"
    before = revision(sample_data, rev).read_bytes()
    resp = client.post(
        f"{E}/revisiones/{rev}/alvarez-lopez-ana",
        data={
            "ej2": "2,5",
            "motivo": " ",
            "version": form_version(client, rev, "alvarez-lopez-ana"),
        },
    )
    assert resp.status_code == 200
    assert "Escribe el motivo" in resp.text
    assert 'value="2,5"' in resp.text  # the submitted value is kept
    assert revision(sample_data, rev).read_bytes() == before


def test_out_of_range_is_rejected(client, sample_data):
    client.post(f"{E}/revisiones")
    rev = f"02-{TODAY}.csv"
    before = revision(sample_data, rev).read_bytes()
    resp = client.post(
        f"{E}/revisiones/{rev}/alvarez-lopez-ana",
        data={"ej2": "9", "motivo": "x", "version": form_version(client, rev, "alvarez-lopez-ana")},
    )
    assert resp.status_code == 200
    assert "Fuera de rango" in resp.text
    assert revision(sample_data, rev).read_bytes() == before


def test_stale_version_is_409(client, sample_data):
    rev = "01-2026-11-20.csv"
    before = revision(sample_data, rev).read_bytes()
    resp = client.post(
        f"{E}/revisiones/{rev}/alvarez-lopez-ana",
        data={"ej2": "2", "motivo": "x", "version": "0" * 16},
    )
    assert resp.status_code == 409
    assert revision(sample_data, rev).read_bytes() == before


def test_unknown_revision_is_404(client):
    assert client.get(f"{E}?tab=revisiones&rev=99-2030-01-01.csv").status_code == 404


def test_edit_existing_row_prefills_reason(client):
    resp = client.get(f"{E}?tab=revisiones&rev=01-2026-11-20.csv&alumno=fernandez-rey-carlos")
    assert "Apartado 1b mal sumado" in resp.text.split('id="form-revision"', 1)[1]
    assert 'value="1,5"' in resp.text.split('id="form-revision"', 1)[1]
