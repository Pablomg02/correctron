import copy
import json
from decimal import Decimal

import pytest

from correctron.config_io import (
    RESERVED_COLUMNS,
    default_exam_config,
    exam_config_to_dict,
    load_exam_config,
    load_subject_meta,
    parse_exam_config,
    save_exam_config,
    save_subject_meta,
)
from correctron.models import Criterion, ExamConfig, Issue, Leaf

FILE = "asig/ex/config.json"


def _parcial(sample_data):
    path = sample_data / "mecanica-de-vuelo" / "parcial-1" / "config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _errors(issues):
    return [i for i in issues if i.level == "error"]


def _avisos(issues):
    return [i for i in issues if i.level == "aviso"]


def test_reserved_columns():
    assert RESERVED_COLUMNS == {"id", "alumno", "total", "comentario", "origen", "motivo"}


def test_sample_parcial_parses(sample_data):
    path = sample_data / "mecanica-de-vuelo" / "parcial-1" / "config.json"
    cfg, issues = load_exam_config(path, "mecanica-de-vuelo/parcial-1/config.json")
    assert issues == []
    assert cfg is not None
    assert cfg.leaf_ids() == ["ej1a", "ej1b", "ej2", "ej3"]
    assert cfg.nombre == "Primer parcial"
    assert cfg.nota_maxima == Decimal("10")
    assert cfg.effective_mode() == "suma"
    group = cfg.criterios[0]
    assert group.is_group and group.maximo is None
    assert [leaf.id for leaf in group.leaves()] == ["ej1a", "ej1b"]
    leaf = cfg.criterios[1]
    assert not leaf.is_group
    assert leaf.leaves() == [Leaf("ej2", "Ejercicio 2", Decimal("3"))]
    assert cfg.leaf("ej1b") == Leaf("ej1b", "Apartado b", Decimal("2"))
    assert cfg.leaf("ej1") is None


def test_sample_trabajo_parses(sample_data):
    path = sample_data / "mecanica-de-vuelo" / "trabajo-1" / "config.json"
    cfg, issues = load_exam_config(path, "x")
    assert issues == []
    assert cfg.calculo_total == "ponderada"
    assert [c.peso for c in cfg.criterios] == [Decimal("2"), Decimal("1")]


def test_defaults_and_folder_name():
    cfg, issues = parse_exam_config({}, "asig/mi-examen/config.json")
    assert issues == []
    assert cfg == ExamConfig(
        nombre="mi-examen",
        tipo="examen",
        fecha="",
        nota_maxima=Decimal("10"),
        decimales=2,
        calculo_total="suma",
        criterios=[],
        extra={},
    )
    assert cfg.effective_mode() == "manual"


def test_criterion_nombre_defaults_to_id():
    cfg, issues = parse_exam_config({"criterios": [{"id": "p1", "maximo": 10}]}, FILE)
    assert issues == []
    assert cfg.criterios[0] == Criterion("p1", "p1", Decimal("1"), Decimal("10"), [])


def _mutate(sample_data, fn):
    data = copy.deepcopy(_parcial(sample_data))
    fn(data)
    return parse_exam_config(data, FILE)


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda d: d["criterios"][2].update(id="ej2"), id="duplicate-id"),
        pytest.param(
            lambda d: d["criterios"][0]["subcriterios"][1].update(id="ej2"), id="duplicate-sub-id"
        ),
        pytest.param(lambda d: d["criterios"][1].update(id="total"), id="reserved-id"),
        pytest.param(lambda d: d["criterios"][1].update(id="version"), id="reserved-version-id"),
        pytest.param(lambda d: d["criterios"][1].update(id="Ej-2"), id="bad-id-pattern"),
        pytest.param(lambda d: d["criterios"][1].pop("id"), id="missing-id"),
        pytest.param(lambda d: d["criterios"][0].update(maximo=4), id="group-with-maximo"),
        pytest.param(lambda d: d["criterios"][1].pop("maximo"), id="leaf-without-maximo"),
        pytest.param(
            lambda d: d["criterios"][0]["subcriterios"][0].pop("maximo"), id="sub-without-maximo"
        ),
        pytest.param(lambda d: d["criterios"][1].update(maximo=0), id="maximo-zero"),
        pytest.param(lambda d: d["criterios"][1].update(maximo=-1), id="maximo-negative"),
        pytest.param(lambda d: d["criterios"][1].update(maximo="3"), id="maximo-string"),
        pytest.param(lambda d: d["criterios"][1].update(peso=-1), id="peso-negative"),
        pytest.param(
            lambda d: d["criterios"][0]["subcriterios"][0].update(peso=1), id="peso-in-sub"
        ),
        pytest.param(lambda d: d["criterios"][0].update(subcriterios=[]), id="empty-group"),
        pytest.param(lambda d: d.update(tipo="otro"), id="bad-tipo"),
        pytest.param(lambda d: d.update(calculo_total="media"), id="bad-calculo"),
        pytest.param(lambda d: d.update(decimales=5), id="decimales-5"),
        pytest.param(lambda d: d.update(decimales=-1), id="decimales-neg"),
        pytest.param(lambda d: d.update(decimales=1.5), id="decimales-float"),
        pytest.param(lambda d: d.update(nota_maxima=0), id="nota-maxima-zero"),
        pytest.param(lambda d: d.update(nota_maxima=True), id="nota-maxima-bool"),
        pytest.param(lambda d: d.update(fecha="3/11/2026"), id="bad-fecha"),
        pytest.param(lambda d: d.update(nombre=3), id="bad-nombre"),
        pytest.param(lambda d: d.update(criterios={}), id="criterios-not-list"),
        pytest.param(lambda d: d["criterios"].append("ej4"), id="criterion-not-object"),
    ],
)
def test_invalid_config_gives_error(sample_data, mutation):
    cfg, issues = _mutate(sample_data, mutation)
    assert cfg is None
    assert len(_errors(issues)) >= 1
    assert all(i.file == FILE for i in issues)


def test_not_an_object():
    cfg, issues = parse_exam_config([1, 2], FILE)
    assert cfg is None
    assert [i.level for i in issues] == ["error"]


def test_suma_with_wrong_total_gives_one_aviso(sample_data):
    cfg, issues = _mutate(sample_data, lambda d: d["criterios"][2].update(maximo=2))
    assert cfg is not None
    assert len(issues) == 1
    assert issues[0].level == "aviso"
    assert "9" in issues[0].message and "10" in issues[0].message


def test_suma_without_criteria_has_no_aviso():
    cfg, issues = parse_exam_config({"calculo_total": "suma", "criterios": []}, FILE)
    assert cfg is not None and issues == []


def test_ponderada_with_zero_weights_is_error(sample_data):
    def fn(d):
        d["calculo_total"] = "ponderada"
        d["criterios"][0]["peso"] = 0
        d["criterios"][1]["peso"] = 0
        d["criterios"][2]["peso"] = 0

    cfg, issues = _mutate(sample_data, fn)
    assert cfg is None
    assert len(_errors(issues)) == 1


def test_unknown_key_in_criterion_is_aviso_and_dropped(sample_data):
    cfg, issues = _mutate(sample_data, lambda d: d["criterios"][1].update(color="rojo"))
    assert cfg is not None
    assert [i.level for i in issues] == ["aviso"]
    assert "color" in issues[0].message
    assert "color" not in json.dumps(exam_config_to_dict(cfg))


def test_default_config_round_trip():
    cfg = default_exam_config("X", "examen", "")
    assert cfg.nota_maxima == Decimal("10")
    assert cfg.decimales == 2
    assert cfg.calculo_total == "suma"
    assert cfg.criterios == []
    parsed, issues = parse_exam_config(exam_config_to_dict(cfg), FILE)
    assert issues == []
    assert parsed == cfg


def test_invalid_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{", encoding="utf-8")
    cfg, issues = load_exam_config(path, FILE)
    assert cfg is None
    assert len(issues) == 1
    assert issues[0].level == "error"
    assert issues[0].file == FILE
    assert issues[0].message.startswith("JSON no válido: ")


def test_missing_config_file(tmp_path):
    cfg, issues = load_exam_config(tmp_path / "config.json", FILE)
    assert cfg is None
    assert [i.level for i in issues] == ["error"]


@pytest.mark.parametrize("exam", ["parcial-1", "trabajo-1"])
def test_sample_round_trip_with_unknown_key(sample_data, exam):
    path = sample_data / "mecanica-de-vuelo" / exam / "config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["mi_clave"] = {"a": [1, 2]}
    first, issues = parse_exam_config(data, FILE)
    assert issues == []
    assert first.extra == {"mi_clave": {"a": [1, 2]}}
    as_dict = exam_config_to_dict(first)
    assert list(as_dict)[-1] == "mi_clave"
    second, issues2 = parse_exam_config(as_dict, FILE)
    assert issues2 == []
    assert second == first
    del data["mi_clave"]
    del as_dict["mi_clave"]
    assert as_dict == data


def test_to_dict_key_order_and_numbers(sample_data):
    cfg, _ = parse_exam_config(_parcial(sample_data), FILE)
    as_dict = exam_config_to_dict(cfg)
    assert list(as_dict) == [
        "nombre",
        "tipo",
        "fecha",
        "nota_maxima",
        "decimales",
        "calculo_total",
        "criterios",
    ]
    assert as_dict["nota_maxima"] == 10 and isinstance(as_dict["nota_maxima"], int)
    cfg.criterios[1].maximo = Decimal("2.50")
    assert exam_config_to_dict(cfg)["criterios"][1]["maximo"] == 2.5


def test_save_exam_config(tmp_path, sample_data):
    cfg, _ = parse_exam_config(_parcial(sample_data), FILE)
    path = tmp_path / "ex" / "config.json"
    save_exam_config(path, cfg)
    text = path.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert '\n  "nombre": "Primer parcial",' in text
    reloaded, issues = load_exam_config(path, FILE)
    assert issues == [] and reloaded == cfg


def test_subject_meta_missing(tmp_path):
    meta, issues = load_subject_meta(tmp_path / "asig" / "asignatura.json", "asig")
    assert meta == {"nombre": "asig", "curso": "", "codigo": ""}
    assert issues == []


def test_subject_meta_sample_and_save(sample_data):
    path = sample_data / "mecanica-de-vuelo" / "asignatura.json"
    meta, issues = load_subject_meta(path, "mecanica-de-vuelo")
    assert issues == []
    assert meta == {"nombre": "Mecánica de Vuelo", "curso": "2026-2027", "codigo": ""}
    meta["extra"] = 1
    save_subject_meta(path, meta)
    assert path.read_text(encoding="utf-8").endswith("}\n")
    again, _ = load_subject_meta(path, "mecanica-de-vuelo")
    assert again == meta


@pytest.mark.parametrize("content", ["{", "[1]"])
def test_subject_meta_invalid(tmp_path, content):
    path = tmp_path / "asig" / "asignatura.json"
    path.parent.mkdir()
    path.write_text(content, encoding="utf-8")
    meta, issues = load_subject_meta(path, "asig")
    assert meta == {"nombre": "asig", "curso": "", "codigo": ""}
    assert issues == [Issue("error", "asig/asignatura.json", issues[0].message)]
