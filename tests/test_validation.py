import json
from pathlib import Path

import pytest

from correctron.validation import validate_exam, validate_subject

S = "mecanica-de-vuelo"
E = "parcial-1"
SUBJ = f"{S}"
EXAM = f"{S}/{E}"


def _append(path: Path, text: str) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def _replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def _edit_config(root: Path, fn) -> None:
    path = root / EXAM / "config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_sample_parcial_has_one_aviso(sample_data):
    issues = validate_exam(sample_data, S, E)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.level == "aviso"
    assert issue.file == f"{EXAM}/alumnos.csv"
    assert "ramos-gil-irene" in issue.message


def test_sample_trabajo_and_subject_clean(sample_data):
    assert validate_exam(sample_data, S, "trabajo-1") == []
    assert validate_subject(sample_data, S) == []


def test_issues_are_sorted(sample_data):
    _append(sample_data / EXAM / "notas" / "pablo.csv", "zz-x,,abc,,,,,\n")
    _append(sample_data / EXAM / "notas" / "claude.csv", "otero-vidal-sara,,,,,,,\n")
    issues = validate_exam(sample_data, S, E)
    keys = [(i.file, i.level != "error", i.message) for i in issues]
    assert keys == sorted(keys)


# Each case: (mutation, expected level, expected file relative to the exam or subject, fragment)
SUBJECT_CASES = {
    "asignatura-invalid-json": (
        lambda r: (r / SUBJ / "asignatura.json").write_text("{", encoding="utf-8"),
        "error",
        "asignatura.json",
        "JSON",
    ),
    "asignatura-not-object": (
        lambda r: (r / SUBJ / "asignatura.json").write_text("[]", encoding="utf-8"),
        "error",
        "asignatura.json",
        "objeto",
    ),
    "subject-missing-column": (
        lambda r: (r / SUBJ / "alumnos.csv").write_text("id,apellidos\na-a,A\n", encoding="utf-8"),
        "error",
        "alumnos.csv",
        "nombre",
    ),
    "subject-duplicate-id": (
        lambda r: _append(r / SUBJ / "alumnos.csv", "otero-vidal-sara,Otero,Sara,,\n"),
        "error",
        "alumnos.csv",
        "otero-vidal-sara",
    ),
    "subject-blank-id": (
        lambda r: _append(r / SUBJ / "alumnos.csv", ",Sin,Id,,\n"),
        "error",
        "alumnos.csv",
        "blanco",
    ),
    "subject-malformed-row": (
        lambda r: _append(r / SUBJ / "alumnos.csv", "x-y,X,Y,,,sobra\n"),
        "error",
        "alumnos.csv",
        "8",
    ),
    "subject-id-pattern": (
        lambda r: _append(r / SUBJ / "alumnos.csv", "Ana_Ruiz,Ruiz,Ana,,\n"),
        "aviso",
        "alumnos.csv",
        "Ana_Ruiz",
    ),
}


@pytest.mark.parametrize("case", list(SUBJECT_CASES))
def test_subject_checks(sample_data, case):
    mutate, level, file, fragment = SUBJECT_CASES[case]
    mutate(sample_data)
    issues = validate_subject(sample_data, S)
    matching = [i for i in issues if i.level == level and i.file == f"{SUBJ}/{file}"]
    assert len(matching) == 1, issues
    assert fragment in matching[0].message


EXAM_CASES = {
    "config-invalid-json": (
        lambda r: (r / EXAM / "config.json").write_text("{", encoding="utf-8"),
        "error",
        "config.json",
        "JSON no válido",
    ),
    "config-structure": (
        lambda r: _edit_config(r, lambda d: d["criterios"][1].update(id="ej3")),
        "error",
        "config.json",
        "ej3",
    ),
    "config-sum-maxima": (
        lambda r: _edit_config(r, lambda d: d["criterios"][2].update(maximo=2)),
        "aviso",
        "config.json",
        "suma",
    ),
    "config-unknown-criterion-key": (
        lambda r: _edit_config(r, lambda d: d["criterios"][1].update(color="rojo")),
        "aviso",
        "config.json",
        "color",
    ),
    "roster-missing-column": (
        lambda r: (r / EXAM / "alumnos.csv").write_text(
            "id,nombre,presentado\nalvarez-lopez-ana,Ana,si\n", encoding="utf-8"
        ),
        "error",
        "alumnos.csv",
        "apellidos",
    ),
    "roster-duplicate-id": (
        lambda r: _append(r / EXAM / "alumnos.csv", "otero-vidal-sara,Otero Vidal,Sara,si,\n"),
        "error",
        "alumnos.csv",
        "otero-vidal-sara",
    ),
    "roster-blank-id": (
        lambda r: _append(r / EXAM / "alumnos.csv", ",Sin,Id,si,\n"),
        "error",
        "alumnos.csv",
        "blanco",
    ),
    "roster-invalid-presentado": (
        lambda r: _replace(
            r / EXAM / "alumnos.csv", "Otero Vidal,Sara,si", "Otero Vidal,Sara,quizá"
        ),
        "error",
        "alumnos.csv",
        "quizá",
    ),
    "roster-malformed-row": (
        lambda r: _replace(
            r / EXAM / "alumnos.csv", "Otero Vidal,Sara,si,", "Otero Vidal,Sara,si,,x"
        ),
        "error",
        "alumnos.csv",
        "6",
    ),
    "sheet-missing-id-column": (
        lambda r: (r / EXAM / "notas" / "pablo.csv").write_text(
            "alumno,ej1a,ej1b,ej2,ej3,total,comentario\nAna,1,1,1,1,4,\n", encoding="utf-8"
        ),
        "error",
        "notas/pablo.csv",
        "id",
    ),
    "sheet-duplicate-id": (
        lambda r: _append(r / EXAM / "notas" / "pablo.csv", "alvarez-lopez-ana,,1,1,1,1,4,\n"),
        "error",
        "notas/pablo.csv",
        "alvarez-lopez-ana",
    ),
    "sheet-non-numeric": (
        lambda r: _replace(r / EXAM / "notas" / "pablo.csv", "2,1.5,3,2.5,9", "2,1.5,tres,2.5,9"),
        "error",
        "notas/pablo.csv",
        "tres",
    ),
    "sheet-out-of-range": (
        lambda r: _replace(r / EXAM / "notas" / "claude.csv", "1,1,1,1,4", "1,1,1,5,8"),
        "error",
        "notas/claude.csv",
        "ej3",
    ),
    "final-out-of-range": (
        lambda r: _replace(r / EXAM / "notas" / "final.csv", "1,1,2,1.5,5.5", "1,1,2,4,8"),
        "error",
        "notas/final.csv",
        "ej3",
    ),
    "revision-non-numeric": (
        lambda r: _replace(r / EXAM / "revisiones" / "01-2026-11-20.csv", ",1.5,,,6", ",uno,,,6"),
        "error",
        "revisiones/01-2026-11-20.csv",
        "uno",
    ),
    "sheet-malformed-row": (
        lambda r: _append(r / EXAM / "notas" / "claude.csv", "x,y,1,1,1,1,4,,sobra\n"),
        "error",
        "notas/claude.csv",
        "6",
    ),
    "sheet-id-not-in-roster": (
        lambda r: _append(r / EXAM / "notas" / "claude.csv", "perez-castro-hugo,,1,1,1,1,4,\n"),
        "aviso",
        "notas/claude.csv",
        "perez-castro-hugo",
    ),
    "sheet-grade-for-absent": (
        lambda r: _append(r / EXAM / "notas" / "claude.csv", "martinez-souto-diego,,1,1,1,1,4,\n"),
        "aviso",
        "notas/claude.csv",
        "martinez-souto-diego",
    ),
    "sheet-unknown-column": (
        lambda r: (r / EXAM / "notas" / "pablo.csv").write_text(
            "id,alumno,ej1a,ej1b,ej2,ej3,ej9,total,comentario\n"
            "alvarez-lopez-ana,,2,1.5,3,2.5,1,9,\n",
            encoding="utf-8",
        ),
        "aviso",
        "notas/pablo.csv",
        "ej9",
    ),
    "sheet-missing-leaf-column": (
        lambda r: (r / EXAM / "notas" / "pablo.csv").write_text(
            "id,alumno,ej1a,ej1b,ej2,total,comentario\nalvarez-lopez-ana,,2,1.5,3,,\n",
            encoding="utf-8",
        ),
        "aviso",
        "notas/pablo.csv",
        "ej3",
    ),
    "sheet-total-mismatch": (
        lambda r: _replace(r / EXAM / "notas" / "pablo.csv", "1,1,2,1.5,5.5", "1,1,2,1.5,6"),
        "aviso",
        "notas/pablo.csv",
        "fernandez-rey-carlos",
    ),
    "revision-total-mismatch-merged": (
        lambda r: _replace(
            r / EXAM / "revisiones" / "01-2026-11-20.csv", ",1.5,,,6,", ",1.5,,,1.5,"
        ),
        "aviso",
        "revisiones/01-2026-11-20.csv",
        "fernandez-rey-carlos",
    ),
    "sheet-invalid-grader-name": (
        lambda r: (r / EXAM / "notas" / "Claude Opus.csv").write_text(
            "id,alumno,ej1a,ej1b,ej2,ej3,total,comentario\n", encoding="utf-8"
        ),
        "aviso",
        "notas/Claude Opus.csv",
        "Claude Opus",
    ),
    "final-unknown-origen": (
        lambda r: _replace(r / EXAM / "notas" / "final.csv", "5.5,,pablo", "5.5,,gpt"),
        "aviso",
        "notas/final.csv",
        "gpt",
    ),
    "revision-bad-name": (
        lambda r: (r / EXAM / "revisiones" / "revision-extra.csv").write_text(
            "id,alumno,ej1a,ej1b,ej2,ej3,total,motivo\n", encoding="utf-8"
        ),
        "aviso",
        "revisiones/revision-extra.csv",
        "NN-AAAA-MM-DD",
    ),
    "revision-blank-motivo": (
        lambda r: _replace(
            r / EXAM / "revisiones" / "01-2026-11-20.csv", ",6,Apartado 1b mal sumado", ",6,"
        ),
        "aviso",
        "revisiones/01-2026-11-20.csv",
        "motivo",
    ),
    "entregas-folder-not-in-roster": (
        lambda r: (r / EXAM / "entregas" / "perez-castro-hugo" / "original").mkdir(parents=True),
        "aviso",
        "entregas/perez-castro-hugo",
        "perez-castro-hugo",
    ),
}


@pytest.mark.parametrize("case", list(EXAM_CASES))
def test_exam_checks(sample_data, case):
    mutate, level, file, fragment = EXAM_CASES[case]
    baseline = set(validate_exam(sample_data, S, E))
    mutate(sample_data)
    issues = validate_exam(sample_data, S, E)
    new = [i for i in issues if i not in baseline]
    matching = [i for i in new if i.level == level and i.file == f"{EXAM}/{file}"]
    assert len(matching) >= 1, new
    assert any(fragment in i.message for i in matching), matching


def test_broken_config_still_validates_roster(sample_data):
    (sample_data / EXAM / "config.json").write_text("{", encoding="utf-8")
    issues = validate_exam(sample_data, S, E)
    files = {i.file for i in issues}
    assert f"{EXAM}/config.json" in files
    assert f"{EXAM}/alumnos.csv" in files


def test_validation_never_raises_on_garbage(sample_data):
    notas = sample_data / EXAM / "notas"
    (notas / "pablo.csv").write_bytes(b"\xff\xfe\x00garbage;;\n\x00\x00")
    (notas / "vacio.csv").write_bytes(b"")
    (sample_data / EXAM / "alumnos.csv").write_bytes(b"")
    validate_exam(sample_data, S, E)
