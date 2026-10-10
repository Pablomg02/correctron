from datetime import date
from decimal import Decimal

import pytest

from correctron.config_io import load_exam_config
from correctron.csvtable import read_table
from correctron.effective import (
    REVISION_RE,
    copy_to_final,
    effective_grades,
    grade_before,
    list_revisions,
    new_revision,
    save_revision_row,
)
from correctron.fsutil import VersionConflict, file_version
from correctron.roster import load_roster

TODAY = date(2026, 12, 1)


@pytest.fixture
def exam(sample_data):
    exam_dir = sample_data / "mecanica-de-vuelo" / "parcial-1"
    cfg, issues = load_exam_config(exam_dir / "config.json", "c")
    assert issues == []
    roster = load_roster(exam_dir / "alumnos.csv", "r")
    return exam_dir, cfg, roster


def _by_id(grades):
    return {g.id: g for g in grades}


def test_revision_re():
    assert REVISION_RE.match("01-2026-11-20.csv")
    assert not REVISION_RE.match("1-2026-11-20.csv")


def test_sample_effective_grades(exam):
    exam_dir, cfg, roster = exam
    grades = effective_grades(exam_dir, cfg, roster)
    assert [g.id for g in grades] == [e.id for e in roster.entries]
    by_id = _by_id(grades)
    carlos = by_id["fernandez-rey-carlos"]
    assert carlos.status == "ok"
    assert carlos.result.total == Decimal("6")
    assert carlos.revised_in == ["01-2026-11-20.csv"]
    assert carlos.cells["ej1b"] == "1.5"
    assert carlos.cells["total"] == "6"
    assert carlos.alumno == "Fernández Rey, Carlos"
    ana = by_id["alvarez-lopez-ana"]
    assert ana.status == "ok" and ana.result.total == Decimal("9")
    assert ana.revised_in == []
    assert ana.presentado == "si"
    assert by_id["martinez-souto-diego"].status == "np"
    assert by_id["martinez-souto-diego"].presentado == "no"
    for sid in ("garcia-perez-lucia", "otero-vidal-sara", "ramos-gil-irene"):
        assert by_id[sid].status == "sin_nota"


def test_incompleta_status(exam):
    exam_dir, cfg, roster = exam
    (exam_dir / "notas" / "final.csv").write_text(
        "id,alumno,ej1a,ej1b,ej2,ej3,total,comentario,origen\n"
        "garcia-perez-lucia,x,2,2,,,,,manual\n",
        encoding="utf-8",
    )
    lucia = _by_id(effective_grades(exam_dir, cfg, roster))["garcia-perez-lucia"]
    assert lucia.status == "incompleta"
    assert lucia.result.partial == Decimal("4")


def test_revision_without_final_row_gives_grade(exam):
    exam_dir, cfg, roster = exam
    (exam_dir / "revisiones" / "02-2026-12-01.csv").write_text(
        "id,alumno,ej1a,ej1b,ej2,ej3,total,motivo\notero-vidal-sara,,1,1,1,1,,Añadida\n",
        encoding="utf-8",
    )
    sara = _by_id(effective_grades(exam_dir, cfg, roster))["otero-vidal-sara"]
    assert sara.status == "ok" and sara.result.total == Decimal("4")
    assert sara.revised_in == ["02-2026-12-01.csv"]


def test_list_and_new_revision(exam):
    exam_dir, cfg, _ = exam
    assert [p.name for p in list_revisions(exam_dir)] == ["01-2026-11-20.csv"]
    path = new_revision(exam_dir, TODAY)
    assert path == exam_dir / "revisiones" / "02-2026-12-01.csv"
    assert path.read_text(encoding="utf-8") == "id,alumno,ej1a,ej1b,ej2,ej3,total,motivo\n"
    assert [p.name for p in list_revisions(exam_dir)] == ["01-2026-11-20.csv", path.name]
    assert new_revision(exam_dir, TODAY).name == "03-2026-12-01.csv"


def test_new_revision_on_empty_exam(sample_data):
    exam_dir = sample_data / "mecanica-de-vuelo" / "trabajo-1"
    path = new_revision(exam_dir, TODAY)
    assert path.name == "01-2026-12-01.csv"
    assert path.read_text(encoding="utf-8") == "id,alumno,memoria,presentacion,total,motivo\n"


def test_grade_before(exam):
    exam_dir, cfg, _ = exam
    rev1 = exam_dir / "revisiones" / "01-2026-11-20.csv"
    before = grade_before(exam_dir, cfg, "fernandez-rey-carlos", rev1)
    assert before == {
        "ej1a": "1",
        "ej1b": "1",
        "ej2": "2",
        "ej3": "1.5",
        "total": "5.5",
        "comentario": "",
    }
    after = grade_before(exam_dir, cfg, "fernandez-rey-carlos", None)
    assert after["ej1b"] == "1.5" and after["total"] == "6"
    rev2 = new_revision(exam_dir, TODAY)
    assert grade_before(exam_dir, cfg, "fernandez-rey-carlos", rev2) == after
    assert grade_before(exam_dir, cfg, "nadie", None)["total"] == ""


def test_save_revision_row_only_changed_leaves(exam):
    exam_dir, cfg, roster = exam
    rev = new_revision(exam_dir, TODAY)
    cells = {"ej1a": "2", "ej1b": "1.50", "ej2": "2,5", "ej3": "2.5"}
    new_version = save_revision_row(
        exam_dir, cfg, roster, rev, "alvarez-lopez-ana", cells, "Recontado", file_version(rev)
    )
    assert new_version == file_version(rev)
    assert rev.read_text(encoding="utf-8") == (
        "id,alumno,ej1a,ej1b,ej2,ej3,total,motivo\n"
        'alvarez-lopez-ana,"Álvarez López, Ana",,,2.5,,8.5,Recontado\n'
    )
    ana = _by_id(effective_grades(exam_dir, cfg, roster))["alvarez-lopez-ana"]
    assert ana.result.total == Decimal("8.5")
    assert ana.revised_in == [rev.name]


def test_save_revision_row_replaces_existing_row(exam):
    exam_dir, cfg, roster = exam
    rev = exam_dir / "revisiones" / "01-2026-11-20.csv"
    cells = {"ej1a": "1", "ej1b": "1", "ej2": "3", "ej3": "1.5"}
    save_revision_row(
        exam_dir, cfg, roster, rev, "fernandez-rey-carlos", cells, "Otro", file_version(rev)
    )
    assert rev.read_text(encoding="utf-8") == (
        "id,alumno,ej1a,ej1b,ej2,ej3,total,motivo\n"
        'fernandez-rey-carlos,"Fernández Rey, Carlos",,,3,,6.5,Otro\n'
    )


def test_save_revision_row_stale_version(exam):
    exam_dir, cfg, roster = exam
    rev = exam_dir / "revisiones" / "01-2026-11-20.csv"
    before = rev.read_bytes()
    with pytest.raises(VersionConflict):
        save_revision_row(
            exam_dir, cfg, roster, rev, "alvarez-lopez-ana", {"ej2": "1"}, "x", "0000000000000000"
        )
    assert rev.read_bytes() == before


def test_save_revision_row_manual_mode(exam):
    exam_dir, cfg, roster = exam
    cfg.calculo_total = "manual"
    rev = new_revision(exam_dir, TODAY)
    save_revision_row(
        exam_dir,
        cfg,
        roster,
        rev,
        "alvarez-lopez-ana",
        {"ej1a": "2", "total": "9,25"},
        "Manual",
        file_version(rev),
    )
    row = read_table(rev).rows[0]
    assert row["ej1a"] == "" and row["total"] == "9.25" and row["motivo"] == "Manual"


def test_copy_to_final_literal_line(exam):
    exam_dir, cfg, roster = exam
    n = copy_to_final(exam_dir, cfg, roster, "claude", ["garcia-perez-lucia"])
    assert n == 1
    lines = (exam_dir / "notas" / "final.csv").read_text(encoding="utf-8").splitlines()
    assert 'garcia-perez-lucia,"García Pérez, Lucía",2,2,3,3,10,,claude' in lines
    assert len(lines) == 4


def test_copy_to_final_skips_missing_rows(exam):
    exam_dir, cfg, roster = exam
    assert copy_to_final(exam_dir, cfg, roster, "pablo", ["otero-vidal-sara", "nadie"]) == 0


def test_copy_to_final_canonicalises(exam):
    exam_dir, cfg, roster = exam
    (exam_dir / "notas" / "llm.csv").write_text(
        "id;alumno;ej1a;ej1b;ej2;ej3;total;comentario\n"
        "otero-vidal-sara;Otero Vidal, Sara;1;7,5;2,0;1;;Hola, qué tal\n",
        encoding="utf-8",
    )
    # ej1b=7,5 is out of range but still copied canonicalised.
    assert copy_to_final(exam_dir, cfg, roster, "llm", ["otero-vidal-sara"]) == 1
    final = read_table(exam_dir / "notas" / "final.csv")
    assert final.delimiter == ","
    row = next(r for r in final.rows if r["id"] == "otero-vidal-sara")
    assert row["ej1b"] == "7.5"
    assert row["ej2"] == "2"
    assert row["comentario"] == "Hola, qué tal"
    assert row["origen"] == "llm"


def test_copy_to_final_copies_feedback(exam):
    exam_dir, cfg, roster = exam
    n = copy_to_final(exam_dir, cfg, roster, "claude", ["alvarez-lopez-ana"])
    assert n == 1
    src = exam_dir / "notas" / "claude" / "alvarez-lopez-ana.md"
    dst = exam_dir / "notas" / "final" / "alvarez-lopez-ana.md"
    assert dst.read_bytes() == src.read_bytes()
    row = next(r for r in read_table(exam_dir / "notas" / "final.csv").rows if r["id"] == src.stem)
    assert row["ej2"] == "2.5" and row["total"] == "8.5"
    assert row["comentario"] == "Error menor en ej2" and row["origen"] == "claude"
