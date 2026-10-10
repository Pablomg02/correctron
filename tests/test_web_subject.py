import json
import re

from conftest import oob_value, row_html

S = "mecanica-de-vuelo"


def students_csv(sample_data):
    return (sample_data / S / "alumnos.csv").read_text(encoding="utf-8")


def list_version(client):
    return oob_value(client.get(f"/a/{S}").text, "version-lista")


def test_home_lists_subjects(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Mecánica de Vuelo" in resp.text
    assert f'href="/a/{S}"' in resp.text


def test_create_subject_redirects(client, sample_data):
    resp = client.post(
        "/asignaturas", data={"nombre": "Física", "curso": "2026"}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/a/fisica"
    assert (sample_data / "fisica" / "asignatura.json").is_file()
    assert client.get("/a/fisica").status_code == 200


def test_create_subject_blank_name_is_400(client):
    assert client.post("/asignaturas", data={"nombre": " "}).status_code == 400


def test_subject_page_lists_students(client):
    resp = client.get(f"/a/{S}")
    assert resp.status_code == 200
    assert 'id="panel-alumnos"' in resp.text
    assert "Pérez Castro" in row_html(resp.text, "perez-castro-hugo")
    assert 'id="c-perez-castro-hugo-apellidos"' in resp.text


def test_add_student(client, sample_data):
    resp = client.post(
        f"/a/{S}/alumnos",
        data={
            "apellidos": "Nuevo Alumno",
            "nombre": "Ana",
            "email": "",
            "version": list_version(client),
        },
    )
    assert resp.status_code == 200
    assert "nuevo-alumno-ana,Nuevo Alumno,Ana" in students_csv(sample_data)
    assert 'id="panel-alumnos"' in resp.text
    row_html(resp.text, "nuevo-alumno-ana")


def test_add_student_stale_version_is_409(client, sample_data):
    before = students_csv(sample_data)
    resp = client.post(
        f"/a/{S}/alumnos",
        data={"apellidos": "X", "nombre": "Y", "version": "0000000000000000"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 409
    assert students_csv(sample_data) == before


def test_import_two_lines(client, sample_data):
    resp = client.post(
        f"/a/{S}/importar-alumnos",
        data={
            "texto": "Sanz Mora, Julia\nLópez\tPedro\tp@x.org\n",
            "version": list_version(client),
        },
    )
    assert resp.status_code == 200
    text = students_csv(sample_data)
    assert "sanz-mora-julia" in text and "lopez-pedro" in text
    assert "2 alumnos importados" in resp.text


def test_import_bad_line_writes_nothing(client, sample_data):
    before = students_csv(sample_data)
    resp = client.post(
        f"/a/{S}/importar-alumnos",
        data={"texto": "Sanz Mora, Julia\nSoloUnaPalabra\n", "version": list_version(client)},
    )
    assert resp.status_code == 200
    assert "Línea" in resp.text
    assert students_csv(sample_data) == before
    assert "SoloUnaPalabra" in resp.text  # the pasted text is kept in the form


def test_edit_then_add_threads_version(client, sample_data):
    resp = client.post(
        f"/a/{S}/alumnos/otero-vidal-sara",
        data={
            "apellidos": "Otero Vidal",
            "nombre": "Sara",
            "email": "sara@example.org",
            "observaciones": "Ya no repite",
            "version": list_version(client),
        },
    )
    assert resp.status_code == 200
    assert "Ya no repite" in students_csv(sample_data)
    assert 'id="c-otero-vidal-sara-' not in resp.text  # inputs are never replaced (D26)
    version = oob_value(resp.text, "version-lista")
    huella = oob_value(resp.text, "huella-actual")
    poll = client.get("/api/huella", params={"ruta": S, "huella": huella})
    assert poll.status_code == 204
    resp = client.post(
        f"/a/{S}/alumnos",
        data={"apellidos": "Ruiz", "nombre": "Luis", "version": version},
    )
    assert resp.status_code == 200
    assert "ruiz-luis" in students_csv(sample_data)


def test_edit_blank_name_is_rejected_with_notice(client, sample_data):
    before = students_csv(sample_data)
    resp = client.post(
        f"/a/{S}/alumnos/otero-vidal-sara",
        data={"apellidos": "", "nombre": "Sara", "version": list_version(client)},
    )
    assert resp.status_code == 200
    assert "aviso-error" in resp.text
    assert students_csv(sample_data) == before


def test_remove_student_lists_exams(client, sample_data):
    resp = client.post(
        f"/a/{S}/alumnos/alvarez-lopez-ana/borrar", data={"version": list_version(client)}
    )
    assert resp.status_code == 200
    for sid in (
        "fernandez-rey-carlos",
        "garcia-perez-lucia",
        "martinez-souto-diego",
        "otero-vidal-sara",
        "perez-castro-hugo",
    ):
        row_html(resp.text, sid)
    assert 'id="fila-alvarez-lopez-ana"' not in resp.text
    assert "parcial-1" in resp.text
    assert "alvarez-lopez-ana" not in students_csv(sample_data)


def test_rename_propagates_to_rosters(client, sample_data):
    resp = client.post(
        f"/a/{S}/alumnos/garcia-perez-lucia",
        data={
            "apellidos": "García Pérez",
            "nombre": "Lucía María",
            "email": "lucia@example.org",
            "observaciones": "",
            "version": list_version(client),
        },
    )
    assert resp.status_code == 200
    for exam in ("parcial-1", "trabajo-1"):
        roster = (sample_data / S / exam / "alumnos.csv").read_text(encoding="utf-8")
        assert "garcia-perez-lucia,García Pérez,Lucía María" in roster


def test_create_exam_redirects_to_config(client, sample_data):
    resp = client.post(
        f"/a/{S}/examenes",
        data={
            "nombre": "Parcial 2",
            "tipo": "examen",
            "fecha": "2027-01-10",
            "copiar_alumnos": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/a/{S}/e/parcial-2?tab=config"
    exam = sample_data / S / "parcial-2"
    assert (exam / "config.json").is_file()
    roster = (exam / "alumnos.csv").read_text(encoding="utf-8")
    assert "perez-castro-hugo" in roster


def test_create_exam_without_students(client, sample_data):
    client.post(f"/a/{S}/examenes", data={"nombre": "Vacío", "tipo": "trabajo", "fecha": ""})
    roster = (sample_data / S / "vacio" / "alumnos.csv").read_text(encoding="utf-8")
    assert roster == "id,apellidos,nombre,presentado,observaciones\n"


def test_exams_tab(client):
    resp = client.get(f"/a/{S}?tab=examenes")
    assert resp.status_code == 200
    assert "Primer parcial" in resp.text
    assert f"/a/{S}/e/parcial-1" in resp.text


def test_datos_tab_saves(client, sample_data):
    resp = client.get(f"/a/{S}?tab=datos")
    version = oob_value(resp.text, "version-datos")
    resp = client.post(
        f"/a/{S}/datos",
        data={
            "nombre": "Mecánica de Vuelo",
            "curso": "2027-2028",
            "codigo": "MV1",
            "version": version,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    meta = json.loads((sample_data / S / "asignatura.json").read_text(encoding="utf-8"))
    assert meta["curso"] == "2027-2028" and meta["codigo"] == "MV1"


def test_problems_tab(client):
    resp = client.get(f"/a/{S}?tab=problemas")
    assert resp.status_code == 200
    assert "parcial-1" in resp.text
    assert f"/a/{S}/e/parcial-1?tab=resumen" in resp.text


def students_tab_count(html):
    """The number shown by the out-of-band refresh of the «Alumnos» tab counter."""
    match = re.search(r'<span id="cuenta-alumnos"[^>]*hx-swap-oob="true"[^>]*>(\d+)</span>', html)
    assert match, "no out-of-band refresh of the students tab counter"
    return int(match.group(1))


def test_structural_actions_refresh_students_tab_count(client):
    resp = client.post(
        f"/a/{S}/alumnos",
        data={"apellidos": "Ruiz", "nombre": "Luis", "version": list_version(client)},
    )
    assert students_tab_count(resp.text) == 7
    resp = client.post(
        f"/a/{S}/importar-alumnos",
        data={"texto": "Sanz Mora, Julia\nVila, Xoán\n", "version": list_version(client)},
    )
    assert students_tab_count(resp.text) == 9
    resp = client.post(f"/a/{S}/alumnos/ruiz-luis/borrar", data={"version": list_version(client)})
    assert students_tab_count(resp.text) == 8


def test_add_student_keeps_focus_on_the_add_form(client):
    """After adding, the re-rendered panel puts the cursor back in «Apellidos»."""
    resp = client.post(
        f"/a/{S}/alumnos",
        data={"apellidos": "Ruiz", "nombre": "Luis", "version": list_version(client)},
    )
    assert re.search(r'<input name="apellidos"[^>]*\bautofocus\b', resp.text)
    page = client.get(f"/a/{S}").text
    assert not re.search(r'<input name="apellidos"[^>]*\bautofocus\b', page)
