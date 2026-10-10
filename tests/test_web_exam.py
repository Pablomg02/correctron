from conftest import oob_value, row_html

from correctron.fsutil import tree_fingerprint

S = "mecanica-de-vuelo"
E = f"/a/{S}/e/parcial-1"


def roster_csv(sample_data, exam="parcial-1"):
    return (sample_data / S / exam / "alumnos.csv").read_text(encoding="utf-8")


def roster_version(client):
    return oob_value(client.get(f"{E}?tab=alumnos").text, "version-lista")


def test_summary(client):
    resp = client.get(E)
    assert resp.status_code == 200
    assert "NP" in row_html(resp.text, "martinez-souto-diego")
    carlos = row_html(resp.text, "fernandez-rey-carlos")
    assert ">6<" in carlos
    assert "revisada" in carlos
    assert "tab=revisiones&rev=01-2026-11-20.csv" in carlos
    assert "Sin nota" in row_html(resp.text, "garcia-perez-lucia")
    assert "ramos-gil-irene" in resp.text
    assert "Primer parcial" in resp.text


def test_summary_counts(client):
    resp = client.get(f"{E}?tab=resumen")
    assert 'id="cuenta-roster">6<' in resp.text
    assert 'id="cuenta-np">1<' in resp.text


def test_exam_page_polls_exam_folder(client, sample_data):
    resp = client.get(E)
    assert oob_value(resp.text, "huella-actual") == tree_fingerprint(sample_data / S / "parcial-1")
    assert "/api/huella?ruta=mecanica-de-vuelo/parcial-1" in resp.text


def test_unknown_exam_is_404(client):
    assert client.get(f"/a/{S}/e/nada").status_code == 404


def test_roster_tab_lists_missing_students(client):
    resp = client.get(f"{E}?tab=alumnos")
    assert resp.status_code == 200
    assert 'id="panel-roster"' in resp.text
    panel = resp.text.split('id="no-en-examen"', 1)[1].split("</section>", 1)[0]
    assert "perez-castro-hugo" in panel
    otro = resp.text.split('id="no-en-asignatura"', 1)[1].split("</section>", 1)[0]
    assert "ramos-gil-irene" in otro


def test_set_presentado(client, sample_data):
    resp = client.post(
        f"{E}/alumnos/alvarez-lopez-ana",
        data={"presentado": "no", "observaciones": "", "version": roster_version(client)},
    )
    assert resp.status_code == 200
    assert "alvarez-lopez-ana,Álvarez López,Ana,no," in roster_csv(sample_data)
    assert 'id="fila-' not in resp.text


def test_add_all(client, sample_data):
    resp = client.post(f"{E}/alumnos", data={"todos": "1", "version": roster_version(client)})
    assert resp.status_code == 200
    assert "perez-castro-hugo,Pérez Castro,Hugo,," in roster_csv(sample_data)
    row_html(resp.text, "perez-castro-hugo")


def test_add_selected(client, sample_data):
    resp = client.post(
        f"/a/{S}/e/trabajo-1/alumnos/alvarez-lopez-ana/borrar",
        data={
            "version": oob_value(
                client.get(f"/a/{S}/e/trabajo-1?tab=alumnos").text, "version-lista"
            )
        },
    )
    assert "alvarez-lopez-ana" not in roster_csv(sample_data, "trabajo-1")
    resp = client.post(
        f"/a/{S}/e/trabajo-1/alumnos",
        data={"ids": ["alvarez-lopez-ana"], "version": oob_value(resp.text, "version-lista")},
    )
    assert resp.status_code == 200
    assert "alvarez-lopez-ana" in roster_csv(sample_data, "trabajo-1")


def test_mark_present(client, sample_data):
    client.post(f"{E}/alumnos", data={"todos": "1", "version": roster_version(client)})
    resp = client.post(f"{E}/marcar-presentados", data={"version": roster_version(client)})
    assert resp.status_code == 200
    text = roster_csv(sample_data)
    assert "perez-castro-hugo,Pérez Castro,Hugo,si," in text
    assert "martinez-souto-diego,Martínez Souto,Diego,no," in text
    assert all(line.split(",")[3] in ("si", "no") for line in text.splitlines()[1:])


def test_mark_present_turns_every_blank_into_si(client, sample_data):
    url = f"/a/{S}/e/trabajo-1"
    version = oob_value(client.get(f"{url}?tab=alumnos").text, "version-lista")
    resp = client.post(f"{url}/marcar-presentados", data={"version": version})
    assert resp.status_code == 200
    lines = roster_csv(sample_data, "trabajo-1").splitlines()[1:]
    assert len(lines) == 6
    assert all(line.split(",")[3] == "si" for line in lines)


def test_set_then_add_all_threads_version(client, sample_data):
    resp = client.post(
        f"{E}/alumnos/garcia-perez-lucia",
        data={
            "presentado": "si",
            "observaciones": "Llegó tarde",
            "version": roster_version(client),
        },
    )
    version = oob_value(resp.text, "version-lista")
    resp = client.post(f"{E}/alumnos", data={"todos": "1", "version": version})
    assert resp.status_code == 200
    text = roster_csv(sample_data)
    assert "Llegó tarde" in text and "perez-castro-hugo" in text


def test_remove_from_roster(client, sample_data):
    resp = client.post(
        f"{E}/alumnos/ramos-gil-irene/borrar", data={"version": roster_version(client)}
    )
    assert resp.status_code == 200
    assert "ramos-gil-irene" not in roster_csv(sample_data)
    assert 'id="fila-ramos-gil-irene"' not in resp.text


def test_invalid_presentado_is_offered_back(client, sample_data):
    path = sample_data / S / "parcial-1" / "alumnos.csv"
    path.write_text(
        path.read_text(encoding="utf-8").replace("Ana,si,", "Ana,tal vez,"), encoding="utf-8"
    )
    resp = client.get(f"{E}?tab=alumnos")
    assert "(no válido: tal vez)" in row_html(resp.text, "alvarez-lopez-ana")
    resp = client.post(
        f"{E}/alumnos/alvarez-lopez-ana",
        data={
            "presentado": "tal vez",
            "observaciones": "Revisar",
            "version": roster_version(client),
        },
    )
    assert resp.status_code == 200
    assert "Ana,tal vez,Revisar" in roster_csv(sample_data)


def test_broken_config_still_renders_summary(client, sample_data):
    (sample_data / S / "parcial-1" / "config.json").write_text("{", encoding="utf-8")
    resp = client.get(E)
    assert resp.status_code == 200
    assert "JSON no válido" in resp.text
    resp = client.get(f"{E}?tab=notas")
    assert resp.status_code == 200
    assert "Corrige config.json para continuar" in resp.text
    assert client.get(f"{E}?tab=alumnos").status_code == 200


def test_mark_present_notice_agrees_in_number(client):
    client.post(
        f"{E}/alumnos", data={"ids": ["perez-castro-hugo"], "version": roster_version(client)}
    )
    resp = client.post(f"{E}/marcar-presentados", data={"version": roster_version(client)})
    assert "1 alumno marcado como presentado." in resp.text
