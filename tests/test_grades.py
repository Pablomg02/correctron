import copy
from decimal import Decimal
from pathlib import Path

import pytest

from correctron.config_io import load_exam_config, parse_exam_config
from correctron.csvtable import CsvMalformed
from correctron.fsutil import file_version
from correctron.grades import (
    GradeSheet,
    compute,
    list_graders,
    load_sheet,
    save_sheet,
    validate_cell,
)
from correctron.roster import load_roster

EXAM = Path("mecanica-de-vuelo") / "parcial-1"


def _cfg(root, exam="parcial-1"):
    cfg, issues = load_exam_config(root / "mecanica-de-vuelo" / exam / "config.json", "c")
    assert issues == []
    return cfg


def _roster(root, exam="parcial-1"):
    return load_roster(root / "mecanica-de-vuelo" / exam / "alumnos.csv", "r")


def _variant(cfg, **changes):
    cfg = copy.deepcopy(cfg)
    for key, value in changes.items():
        setattr(cfg, key, value)
    return cfg


def test_sample_ana_total_and_group(sample_data):
    cfg = _cfg(sample_data)
    sheet = load_sheet(sample_data / EXAM / "notas" / "pablo.csv", "pablo")
    result = compute(cfg, sheet.row("alvarez-lopez-ana"))
    assert result.complete
    assert result.total == Decimal("9")
    assert result.groups == {"ej1": Decimal("3.5")}
    assert result.leaves["ej1b"] == Decimal("1.5")
    assert result.cell_errors == {}
    assert result.partial is None


def test_sample_lucia_incomplete(sample_data):
    cfg = _cfg(sample_data)
    sheet = load_sheet(sample_data / EXAM / "notas" / "pablo.csv", "pablo")
    result = compute(cfg, sheet.row("garcia-perez-lucia"))
    assert not result.complete
    assert result.total is None
    assert result.partial == Decimal("4")
    assert result.groups == {"ej1": Decimal("4")}
    assert result.leaves["ej2"] is None


def test_group_subtotal_none_when_leaf_blank(sample_data):
    cfg = _cfg(sample_data)
    result = compute(cfg, {"ej1a": "2", "ej2": "1"})
    assert result.groups == {"ej1": None}
    assert result.partial == Decimal("3")


def test_empty_row_has_no_partial(sample_data):
    result = compute(_cfg(sample_data), {})
    assert not result.complete and result.total is None and result.partial is None


def test_ponderada(sample_data):
    cfg = _cfg(sample_data, "trabajo-1")
    result = compute(cfg, {"memoria": "8", "presentacion": "5"})
    assert result.complete
    assert result.total == Decimal("7")
    assert result.partial is None


def test_ponderada_with_group():
    cfg, _ = parse_exam_config(
        {
            "calculo_total": "ponderada",
            "nota_maxima": 10,
            "criterios": [
                {
                    "id": "g",
                    "peso": 1,
                    "subcriterios": [{"id": "a", "maximo": 2}, {"id": "b", "maximo": 2}],
                },
                {"id": "c", "maximo": 5, "peso": 3},
            ],
        },
        "x/config.json",
    )
    result = compute(cfg, {"a": "1", "b": "2", "c": "5"})
    # (1 * 3/4 + 3 * 1) / 4 * 10 = 9.375 -> 9.38
    assert result.total == Decimal("9.38")


def test_unparsable_leaf(sample_data):
    cfg = _cfg(sample_data)
    result = compute(cfg, {"ej1a": "abc", "ej1b": "2", "ej2": "3", "ej3": "3"})
    assert "ej1a" in result.cell_errors
    assert not result.complete
    assert result.total is None
    assert result.leaves["ej1a"] is None


def test_out_of_range_leaf(sample_data):
    cfg = _cfg(sample_data)
    result = compute(cfg, {"ej1a": "2.5", "ej1b": "2", "ej2": "3", "ej3": "3"})
    assert "ej1a" in result.cell_errors
    assert "2" in result.cell_errors["ej1a"]
    assert not result.complete
    result = compute(cfg, {"ej1a": "-1", "ej1b": "2", "ej2": "3", "ej3": "3"})
    assert "ej1a" in result.cell_errors


def test_manual_total(sample_data):
    cfg = _variant(_cfg(sample_data), calculo_total="manual")
    result = compute(cfg, {"total": "6,75", "ej1a": "1"})
    assert result.complete
    assert result.total == Decimal("6.75")
    result = compute(cfg, {"total": ""})
    assert not result.complete and result.total is None
    result = compute(cfg, {"total": "11"})
    assert "total" in result.cell_errors and not result.complete


def test_no_criteria_is_manual():
    cfg, _ = parse_exam_config({}, "x/config.json")
    result = compute(cfg, {"total": "8"})
    assert result.complete and result.total == Decimal("8")


def test_rounding_one_decimal():
    cfg, _ = parse_exam_config(
        {
            "decimales": 1,
            "criterios": [{"id": "a", "maximo": 5}, {"id": "b", "maximo": 5}],
        },
        "x/config.json",
    )
    result = compute(cfg, {"a": "3.125", "b": "3.125"})
    assert result.total == Decimal("6.3")


def test_save_sheet_canonical(sample_data):
    cfg = _cfg(sample_data)
    roster = _roster(sample_data)
    path = sample_data / EXAM / "notas" / "otro.csv"
    path.write_text(
        "ID,revisado_por,ej3,ej2,ej1b,ej1a,alumno,total,comentario\n"
        "otero-vidal-sara,luis,1,1,1,1,Nombre viejo,99,ok\n"
        "alvarez-lopez-ana,eva,2.5,3,1.5,2,,,\n"
        "zz-fuera,,,,,,Fuera Fuera,,\n",
        encoding="utf-8",
    )
    sheet = load_sheet(path, "otro")
    save_sheet(sheet, cfg, roster)
    assert path.read_text(encoding="utf-8") == (
        "id,alumno,ej1a,ej1b,ej2,ej3,total,comentario,revisado_por\n"
        'alvarez-lopez-ana,"Álvarez López, Ana",2,1.5,3,2.5,9,,eva\n'
        'otero-vidal-sara,"Otero Vidal, Sara",1,1,1,1,4,ok,luis\n'
        "zz-fuera,Fuera Fuera,,,,,,,\n"
    )
    assert sheet.version == file_version(path)


def test_save_final_sheet_has_origen(sample_data):
    cfg = _cfg(sample_data)
    path = sample_data / EXAM / "notas" / "final.csv"
    before = path.read_text(encoding="utf-8")
    sheet = load_sheet(path, "final")
    save_sheet(sheet, cfg, _roster(sample_data))
    assert path.read_text(encoding="utf-8") == before


def test_save_sheet_incomplete_total_blank_and_keeps_dialect(sample_data):
    cfg = _cfg(sample_data)
    path = sample_data / EXAM / "notas" / "llm.csv"
    path.write_text(
        "id;alumno;ej1a;ej1b;ej2;ej3;total;comentario\ngarcia-perez-lucia;x;2;1,5;;;3,5;\n",
        encoding="utf-8",
    )
    sheet = load_sheet(path, "llm")
    save_sheet(sheet, cfg, _roster(sample_data))
    assert path.read_text(encoding="utf-8") == (
        "id;alumno;ej1a;ej1b;ej2;ej3;total;comentario\n"
        "garcia-perez-lucia;García Pérez, Lucía;2;1,5;;;;\n"
    )


def test_save_sheet_manual_keeps_total(sample_data):
    cfg = _variant(_cfg(sample_data), calculo_total="manual")
    path = sample_data / EXAM / "notas" / "pablo.csv"
    sheet = load_sheet(path, "pablo")
    sheet.set_row("alvarez-lopez-ana", {"total": "7.25"})
    save_sheet(sheet, cfg, _roster(sample_data))
    assert load_sheet(path, "pablo").row("alvarez-lopez-ana")["total"] == "7.25"


def test_save_sheet_malformed_raises(sample_data):
    path = sample_data / EXAM / "notas" / "pablo.csv"
    path.write_text("id,alumno\na,b,c\n", encoding="utf-8")
    sheet = load_sheet(path, "pablo")
    with pytest.raises(CsvMalformed):
        save_sheet(sheet, _cfg(sample_data), _roster(sample_data))


def test_sheet_row_operations(tmp_path):
    sheet = load_sheet(tmp_path / "notas" / "x.csv", "x")
    assert isinstance(sheet, GradeSheet)
    assert sheet.version == ""
    assert sheet.row("a") is None
    sheet.set_row("a", {"ej1a": "1"})
    sheet.set_row("a", {"comentario": "bien"})
    assert sheet.row("a")["ej1a"] == "1"
    assert sheet.row("a")["comentario"] == "bien"
    sheet.set_row("b", {})
    sheet.remove_row("a")
    assert sheet.row("a") is None
    assert sheet.row("b") is not None


def test_list_graders(sample_data):
    exam = sample_data / EXAM
    assert list_graders(exam) == ["claude", "pablo"]
    assert list_graders(sample_data / "mecanica-de-vuelo" / "trabajo-1") == []


def test_validate_cell(sample_data):
    cfg = _cfg(sample_data)
    assert validate_cell(cfg, "ej2", "2,5") == ("2.5", None)
    assert validate_cell(cfg, "ej2", " ") == ("", None)
    assert validate_cell(cfg, "ej2", "3.00") == ("3", None)
    value, error = validate_cell(cfg, "ej2", "7")
    assert error and "3" in error
    value, error = validate_cell(cfg, "ej1a", "abc")
    assert error
    assert validate_cell(cfg, "total", "9,5") == ("9.5", None)
    assert validate_cell(cfg, "total", "11")[1]
    assert validate_cell(cfg, "comentario", "  Muy bien ") == ("Muy bien", None)
