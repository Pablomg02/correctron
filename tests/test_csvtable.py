from pathlib import Path

import pytest

from correctron.csvtable import CsvMalformed, Table, read_table, write_table


def test_missing_file_gives_empty_table(tmp_path):
    table = read_table(tmp_path / "nope.csv")
    assert table == Table()
    assert table.columns == [] and table.rows == [] and table.malformed == []


def test_basic_read(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text(
        ' ID , Alumno ,ej1\nana," Álvarez, Ana ", 2 \n\n,,\nbob,Bob\n', encoding="utf-8"
    )
    table = read_table(path)
    assert table.columns == ["id", "alumno", "ej1"]
    assert table.rows == [
        {"id": "ana", "alumno": "Álvarez, Ana", "ej1": "2"},
        {"id": "bob", "alumno": "Bob", "ej1": ""},
    ]
    assert table.delimiter == ","
    assert table.bom is False
    assert table.encoding == "utf-8"


def test_semicolon_bom_round_trip(tmp_path):
    path = tmp_path / "a.csv"
    original = "\ufeffid;alumno;ej1\nana;Ana;7,5\n".encode()
    path.write_bytes(original)
    table = read_table(path)
    assert table.delimiter == ";"
    assert table.bom is True
    assert table.rows[0]["ej1"] == "7,5"
    write_table(path, table)
    assert path.read_bytes() == original


def test_semicolon_header_with_comma_cell(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text('id;alumno;ej1\nperez-ana;"Pérez, Ana";3\n', encoding="utf-8")
    table = read_table(path)
    assert table.delimiter == ";"
    assert table.rows == [{"id": "perez-ana", "alumno": "Pérez, Ana", "ej1": "3"}]


def test_tab_delimiter(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("id\talumno\nana\tAna, B\n", encoding="utf-8")
    table = read_table(path)
    assert table.delimiter == "\t"
    assert table.rows == [{"id": "ana", "alumno": "Ana, B"}]


def test_delimiter_tie_defaults_to_comma(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("id\nana\n", encoding="utf-8")
    assert read_table(path).delimiter == ","
    path.write_text("a;b\tc\n1;2\t3\n", encoding="utf-8")
    assert read_table(path).delimiter == ","


def test_malformed_row(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("id,alumno\nana,Ana\nbob,Bob,extra\n", encoding="utf-8")
    table = read_table(path)
    assert table.malformed == [3]
    assert table.rows[1] == {"id": "bob", "alumno": "Bob"}
    before = path.read_bytes()
    with pytest.raises(CsvMalformed):
        write_table(path, table)
    assert path.read_bytes() == before


def test_unknown_columns_survive_round_trip(tmp_path):
    path = tmp_path / "a.csv"
    original = 'id,alumno,revisado_por,ej1\nana,"Álvarez, Ana",luis,2\n'
    path.write_text(original, encoding="utf-8")
    table = read_table(path)
    write_table(path, table)
    assert path.read_text(encoding="utf-8") == original


def test_cp1252_round_trip(tmp_path):
    path = tmp_path / "a.csv"
    original = "id,apellidos\nperez,Pérez\n".encode("cp1252")
    path.write_bytes(original)
    table = read_table(path)
    assert table.encoding == "cp1252"
    assert table.rows == [{"id": "perez", "apellidos": "Pérez"}]
    write_table(path, table)
    assert path.read_bytes() == original


def test_crlf_input_written_with_lf(tmp_path):
    path = tmp_path / "a.csv"
    path.write_bytes(b"id,a\r\nx,1\r\n")
    table = read_table(path)
    assert table.rows == [{"id": "x", "a": "1"}]
    write_table(path, table)
    assert path.read_bytes() == b"id,a\nx,1\n"


def test_write_new_table_minimal_quoting(tmp_path: Path):
    path = tmp_path / "sub" / "a.csv"
    table = Table(columns=["id", "alumno", "x"], rows=[{"id": "a", "alumno": "B, C"}])
    write_table(path, table)
    assert path.read_text(encoding="utf-8") == 'id,alumno,x\na,"B, C",\n'
