import pytest

from correctron.csvtable import CsvMalformed
from correctron.fsutil import file_version
from correctron.models import RosterEntry, Student
from correctron.roster import (
    load_roster,
    load_students,
    parse_import_text,
    parse_presentado,
    save_roster,
    save_students,
)


def _subject_path(root):
    return root / "mecanica-de-vuelo" / "alumnos.csv"


def _roster_path(root, exam="parcial-1"):
    return root / "mecanica-de-vuelo" / exam / "alumnos.csv"


def test_sample_subject_list(sample_data):
    path = _subject_path(sample_data)
    sl = load_students(path, "mecanica-de-vuelo/alumnos.csv")
    assert len(sl.students) == 6
    assert sl.issues == []
    assert sl.version == file_version(path)
    assert sl.students[4] == Student(
        "otero-vidal-sara", "Otero Vidal", "Sara", "sara@example.org", "Repetidora", {}
    )


def test_sample_roster(sample_data):
    roster = load_roster(_roster_path(sample_data), "mecanica-de-vuelo/parcial-1/alumnos.csv")
    assert len(roster.entries) == 6
    assert roster.issues == []
    diego = next(e for e in roster.entries if e.id == "martinez-souto-diego")
    assert parse_presentado(diego.presentado) == "no"
    assert roster.entries[-1] == RosterEntry(
        "ramos-gil-irene", "Ramos Gil", "Irene", "si", "Erasmus", {}
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sí", "si"),
        ("si", "si"),
        (" S ", "si"),
        ("x", "si"),
        ("1", "si"),
        ("TRUE", "si"),
        ("yes", "si"),
        ("Presentado", "si"),
        ("NP", "no"),
        ("no", "no"),
        ("n", "no"),
        ("0", "no"),
        ("false", "no"),
        ("No presentado", "no"),
        ("", ""),
        ("  ", ""),
        ("tal vez", None),
    ],
)
def test_parse_presentado(raw, expected):
    assert parse_presentado(raw) == expected


def test_extra_column_survives_save(sample_data):
    path = _roster_path(sample_data)
    path.write_text(
        "id,apellidos,nombre,grupo,presentado,observaciones\nb-b,B,B,G2,si,\na-a,A,A,G1,,nota\n",
        encoding="utf-8",
    )
    roster = load_roster(path, "r")
    assert roster.entries[0].extra == {"grupo": "G2"}
    save_roster(path, roster)
    assert path.read_text(encoding="utf-8") == (
        "id,apellidos,nombre,presentado,observaciones,grupo\na-a,A,A,,nota,G1\nb-b,B,B,si,,G2\n"
    )


def test_save_students_canonical_order_and_dialect(tmp_path):
    path = tmp_path / "alumnos.csv"
    path.write_bytes("﻿nombre;id;apellidos;grupo\nLuis;ruiz-luis;Ruiz;A\n".encode())
    sl = load_students(path, "x/alumnos.csv")
    sl.students.append(Student("abad-eva", "Abad", "Eva"))
    save_students(path, sl)
    assert (
        path.read_bytes()
        == (
            "﻿id;apellidos;nombre;email;observaciones;grupo\n"
            "abad-eva;Abad;Eva;;;\n"
            "ruiz-luis;Ruiz;Luis;;;A\n"
        ).encode()
    )


def test_save_refuses_malformed(tmp_path):
    path = tmp_path / "alumnos.csv"
    path.write_text("id,apellidos,nombre\na,A,A\nb,B,B,extra\n", encoding="utf-8")
    sl = load_students(path, "x/alumnos.csv")
    assert any(i.level == "error" and "3" in i.message for i in sl.issues)
    with pytest.raises(CsvMalformed):
        save_students(path, sl)
    roster = load_roster(path, "x/e/alumnos.csv")
    with pytest.raises(CsvMalformed):
        save_roster(path, roster)


def test_load_issues(tmp_path):
    path = tmp_path / "alumnos.csv"
    path.write_text("id,apellidos\na,A\na,B\n,C\n", encoding="utf-8")
    sl = load_students(path, "x/alumnos.csv")
    messages = [i.message for i in sl.issues if i.level == "error"]
    assert len(messages) == 3
    assert any("nombre" in m for m in messages)
    assert any("«a»" in m for m in messages)
    assert all(i.file == "x/alumnos.csv" for i in sl.issues)
    assert len(sl.students) == 3


def test_roster_invalid_presentado(tmp_path):
    path = tmp_path / "alumnos.csv"
    path.write_text("id,apellidos,nombre,presentado\na,A,A,tal vez\nb,B,B,si\n", encoding="utf-8")
    roster = load_roster(path, "x/e/alumnos.csv")
    assert [i.level for i in roster.issues] == ["error"]
    assert "tal vez" in roster.issues[0].message


def test_missing_file_is_empty(tmp_path):
    sl = load_students(tmp_path / "alumnos.csv", "x/alumnos.csv")
    assert sl.students == [] and sl.version == ""


def test_parse_import_text():
    triples, errors = parse_import_text("Pérez, Ana\nRuiz\tLuis\tl@x.org\n\n")
    assert triples == [("Pérez", "Ana", ""), ("Ruiz", "Luis", "l@x.org")]
    assert errors == []


def test_parse_import_text_errors():
    triples, errors = parse_import_text("SoloUnaPalabra")
    assert triples == []
    assert len(errors) == 1 and errors[0].startswith("Línea 1:")
    _, errors = parse_import_text("A, B\n\n, Ana\nX, Y, z@x, sobra\n")
    assert [e.split(":")[0] for e in errors] == ["Línea 3", "Línea 4"]
