from urllib.parse import parse_qs, urlparse

S = "mecanica-de-vuelo"
E = f"/a/{S}/e/parcial-1"


def exam_dir(sample_data):
    return sample_data / S / "parcial-1"


def test_upload_two_files_to_statement(client, sample_data):
    resp = client.post(
        f"{E}/subir",
        data={"destino": "enunciado"},
        files=[
            ("archivos", ("soluciones.pdf", b"%PDF-1.4 a", "application/pdf")),
            ("archivos", ("notas de clase.txt", b"hola", "text/plain")),
        ],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = urlparse(resp.headers["location"])
    assert location.path == E
    assert parse_qs(location.query)["tab"] == ["enunciado"]
    folder = exam_dir(sample_data) / "enunciado"
    assert (folder / "soluciones.pdf").read_bytes() == b"%PDF-1.4 a"
    assert (folder / "notas de clase.txt").read_bytes() == b"hola"
    page = client.get(resp.headers["location"])
    assert "soluciones.pdf" in page.text
    assert "2 archivos subidos" in page.text


def test_upload_to_new_submission_folder(client, sample_data):
    resp = client.post(
        f"{E}/subir",
        data={"destino": "entregas/perez-castro-hugo/original"},
        files=[("archivos", ("examen.pdf", b"%PDF-1.4 h", "application/pdf"))],
        follow_redirects=False,
    )
    assert resp.status_code == 303
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert query["alumno"] == ["perez-castro-hugo"] and query["parte"] == ["original"]
    target = exam_dir(sample_data) / "entregas" / "perez-castro-hugo" / "original" / "examen.pdf"
    assert target.is_file()


def test_upload_bad_destination_is_400(client, sample_data):
    resp = client.post(
        f"{E}/subir",
        data={"destino": "../../x"},
        files=[("archivos", ("a.pdf", b"x", "application/pdf"))],
    )
    assert resp.status_code == 400
    assert not (sample_data / "x").exists()


def test_delete_outside_root_is_404(client):
    resp = client.post(f"{E}/borrar-archivo", data={"ruta": "../../../etc/passwd"})
    assert resp.status_code == 404


def test_delete_moves_to_trash(client, sample_data):
    rel = f"{S}/parcial-1/enunciado/rubrica.pdf"
    resp = client.post(f"{E}/borrar-archivo", data={"ruta": rel}, follow_redirects=False)
    assert resp.status_code == 303
    assert "tab=enunciado" in resp.headers["location"]
    assert not (sample_data / rel).exists()
    trashed = list((sample_data / ".papelera").rglob("rubrica.pdf"))
    assert len(trashed) == 1
    assert trashed[0].as_posix().endswith(f"{S}/parcial-1/enunciado/rubrica.pdf")


def test_delete_with_htmx_redirects_back(client, sample_data):
    rel = f"{S}/parcial-1/entregas/alvarez-lopez-ana/corregido/examen-corregido.pdf"
    resp = client.post(f"{E}/borrar-archivo", data={"ruta": rel}, headers={"HX-Request": "true"})
    assert resp.status_code == 200
    redirect = resp.headers["hx-redirect"]
    assert "alumno=alvarez-lopez-ana" in redirect and "parte=corregido" in redirect


def test_delete_config_is_400(client, sample_data):
    rel = f"{S}/parcial-1/config.json"
    resp = client.post(f"{E}/borrar-archivo", data={"ruta": rel})
    assert resp.status_code == 400
    assert (sample_data / rel).is_file()


def test_statement_tab_shows_first_pdf(client):
    resp = client.get(f"{E}?tab=enunciado")
    assert resp.status_code == 200
    assert '<iframe src="/archivo/mecanica-de-vuelo/parcial-1/enunciado/enunciado.pdf"' in resp.text
    assert "rubrica.pdf" in resp.text
    assert 'enctype="multipart/form-data"' in resp.text


def test_statement_tab_selected_file(client):
    resp = client.get(
        f"{E}?tab=enunciado&archivo=mecanica-de-vuelo/parcial-1/enunciado/rubrica.pdf"
    )
    assert '<iframe src="/archivo/mecanica-de-vuelo/parcial-1/enunciado/rubrica.pdf"' in resp.text


def test_submissions_table(client):
    resp = client.get(f"{E}?tab=entregas")
    assert resp.status_code == 200
    assert "alumno=alvarez-lopez-ana" in resp.text
    assert '<tr id="fila-martinez-souto-diego" class="np">' in resp.text


def test_submission_viewer(client):
    resp = client.get(f"{E}?tab=entregas&alumno=alvarez-lopez-ana&parte=corregido")
    assert resp.status_code == 200
    assert "<iframe" in resp.text
    assert (
        '<iframe src="/archivo/mecanica-de-vuelo/parcial-1/entregas/alvarez-lopez-ana/'
        'corregido/examen-corregido.pdf"' in resp.text
    )
    assert "alumno=fernandez-rey-carlos" in resp.text  # "siguiente" link


def test_orphan_submission_folder_is_listed(client, sample_data):
    (exam_dir(sample_data) / "entregas" / "desconocido" / "original").mkdir(parents=True)
    resp = client.get(f"{E}?tab=entregas")
    assert "desconocido" in resp.text
