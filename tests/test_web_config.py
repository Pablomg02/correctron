import json

from conftest import oob_value

from correctron.fsutil import file_version

S = "mecanica-de-vuelo"
E = f"/a/{S}/e/parcial-1"


def config_path(sample_data):
    return sample_data / S / "parcial-1" / "config.json"


def current_config(sample_data):
    return json.loads(config_path(sample_data).read_text(encoding="utf-8"))


def test_config_tab_embeds_json_for_the_editor(client, sample_data):
    resp = client.get(f"{E}?tab=config")
    assert resp.status_code == 200
    assert '<script type="application/json" id="config-datos">' in resp.text
    assert 'x-data="editorCriterios()"' in resp.text
    assert "/static/criterios.js" in resp.text
    assert oob_value(resp.text, "version-config") == file_version(config_path(sample_data))
    assert 'name="config_json"' in resp.text
    assert "<textarea" in resp.text  # the raw editor is always available


def test_post_valid_config_adds_leaf(client, sample_data):
    data = current_config(sample_data)
    data["criterios"].append({"id": "ej4", "nombre": "Ejercicio 4", "maximo": 1, "peso": 1})
    resp = client.post(
        f"{E}/config",
        data={
            "config_json": json.dumps(data),
            "version": file_version(config_path(sample_data)),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"{E}?tab=config&ok=1"
    assert current_config(sample_data)["criterios"][-1]["id"] == "ej4"
    page = client.get(resp.headers["location"])
    assert "Guardado" in page.text


def test_post_duplicate_id_shows_error_and_writes_nothing(client, sample_data):
    before = config_path(sample_data).read_bytes()
    data = current_config(sample_data)
    data["criterios"].append({"id": "ej2", "nombre": "Repetido", "maximo": 1})
    text = json.dumps(data)
    resp = client.post(
        f"{E}/config", data={"config_json": text, "version": file_version(config_path(sample_data))}
    )
    assert resp.status_code == 200
    assert "ej2" in resp.text and "repetido" in resp.text.lower()
    assert config_path(sample_data).read_bytes() == before


def test_post_stale_version_is_409(client, sample_data):
    before = config_path(sample_data).read_bytes()
    resp = client.post(
        f"{E}/config",
        data={"config_json": json.dumps(current_config(sample_data)), "version": "0" * 16},
    )
    assert resp.status_code == 409
    assert config_path(sample_data).read_bytes() == before


def test_broken_config_shows_raw_editor(client, sample_data):
    config_path(sample_data).write_text("{", encoding="utf-8")
    resp = client.get(f"{E}?tab=config")
    assert resp.status_code == 200
    assert "<textarea" in resp.text
    assert "JSON no válido" in resp.text
    assert 'id="config-datos"' not in resp.text
    # The raw editor can repair it.
    fixed = json.dumps({"nombre": "Arreglado", "criterios": []})
    resp = client.post(
        f"{E}/config",
        data={"config_json": fixed, "version": file_version(config_path(sample_data))},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert current_config(sample_data)["nombre"] == "Arreglado"


def test_removed_leaf_columns_are_kept_and_reported(client, sample_data):
    data = current_config(sample_data)
    data["criterios"] = [c for c in data["criterios"] if c["id"] != "ej3"]
    resp = client.post(
        f"{E}/config",
        data={"config_json": json.dumps(data), "version": file_version(config_path(sample_data))},
    )
    assert resp.status_code == 200  # redirect followed
    assert "Las columnas ej3 siguen en los CSV de notas" in resp.text
    pablo = sample_data / S / "parcial-1" / "notas" / "pablo.csv"
    resp = client.post(
        f"{E}/notas/pablo/garcia-perez-lucia",
        data={"ej1a": "1", "version": file_version(pablo)},
    )
    assert resp.status_code == 200
    header = pablo.read_text(encoding="utf-8").splitlines()[0]
    assert "ej3" in header.split(",")
