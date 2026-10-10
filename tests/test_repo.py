import json
from pathlib import Path

import pytest

from correctron import repo as repo_mod
from correctron.csvtable import CsvMalformed, read_table
from correctron.fsutil import PathOutsideData, VersionConflict, file_version
from correctron.repo import AREA_RE, BadRequest, NotFound, Repository

S = "mecanica-de-vuelo"
E = "parcial-1"
STALE = "0000000000000000"


@pytest.fixture
def repo(sample_data):
    return Repository(sample_data)


def _v(path: Path) -> str:
    return file_version(path)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# --- exceptions and exports ------------------------------------------------


def test_exception_types():
    assert issubclass(NotFound, KeyError)
    assert issubclass(BadRequest, ValueError)
    assert repo_mod.VersionConflict is VersionConflict
    assert repo_mod.CsvMalformed is CsvMalformed
    assert repo_mod.PathOutsideData is PathOutsideData


# --- root and subjects -----------------------------------------------------


def test_ensure_root_writes_leeme_once(tmp_path):
    root = tmp_path / "nuevo" / "data"
    r = Repository(root)
    r.ensure_root()
    leeme = root / "LEEME.md"
    assert "## Instrucciones para un corrector LLM" in leeme.read_text(encoding="utf-8")
    leeme.write_text("mi versión\n", encoding="utf-8")
    r.ensure_root()
    assert leeme.read_text(encoding="utf-8") == "mi versión\n"


def test_list_subjects(repo, sample_data):
    (sample_data / ".papelera").mkdir()
    (sample_data / "_privado").mkdir()
    (sample_data / "suelto.txt").write_text("x")
    subjects = repo.list_subjects()
    assert len(subjects) == 1
    info = subjects[0]
    assert (info.slug, info.nombre, info.curso, info.n_students, info.n_exams) == (
        S,
        "Mecánica de Vuelo",
        "2026-2027",
        6,
        2,
    )


def test_subject_meta(repo, sample_data):
    meta, issues, version = repo.subject_meta(S)
    assert meta["nombre"] == "Mecánica de Vuelo"
    assert issues == []
    assert version == _v(sample_data / S / "asignatura.json")
    with pytest.raises(NotFound):
        repo.subject_meta("no-existe")
    with pytest.raises(NotFound):
        repo.subject_meta("..")


def test_create_subject_unique(repo, sample_data):
    slug = repo.create_subject("Mecánica de Vuelo", "2027-2028")
    assert slug == "mecanica-de-vuelo-2"
    meta = json.loads((sample_data / slug / "asignatura.json").read_text(encoding="utf-8"))
    assert meta == {"nombre": "Mecánica de Vuelo", "curso": "2027-2028", "codigo": ""}
    assert (sample_data / slug / "alumnos.csv").read_text(encoding="utf-8") == (
        "id,apellidos,nombre,email,observaciones\n"
    )
    assert repo.create_subject("Física", "") == "fisica"
    with pytest.raises(BadRequest):
        repo.create_subject("   ", "")


def test_update_subject_meta(repo, sample_data):
    path = sample_data / S / "asignatura.json"
    repo.update_subject_meta(S, "Mecánica de Vuelo II", "2027", "G123", _v(path))
    meta, _, _ = repo.subject_meta(S)
    assert (meta["nombre"], meta["curso"], meta["codigo"]) == (
        "Mecánica de Vuelo II",
        "2027",
        "G123",
    )
    with pytest.raises(BadRequest):
        repo.update_subject_meta(S, "", "", "", _v(path))


# --- students --------------------------------------------------------------


def _subject_csv(root):
    return root / S / "alumnos.csv"


def test_add_student_homonym(repo, sample_data):
    path = _subject_csv(sample_data)
    new_id = repo.add_student(S, "Álvarez López", "Ana", "otra@example.org", _v(path))
    assert new_id == "alvarez-lopez-ana-2"
    ids = [s.id for s in repo.students(S).students]
    assert ids.count("alvarez-lopez-ana-2") == 1 and len(ids) == 7
    assert repo.add_student(S, "Nuevo", "Pedro", "", _v(path)) == "nuevo-pedro"
    with pytest.raises(BadRequest):
        repo.add_student(S, "", "Pedro", "", _v(path))


def test_import_students(repo, sample_data):
    path = _subject_csv(sample_data)
    ids, errors = repo.import_students(S, "Gómez Ruiz, Marta\nLópez\tPedro\tp@x.org\n", _v(path))
    assert ids == ["gomez-ruiz-marta", "lopez-pedro"] and errors == []
    assert len(repo.students(S).students) == 8


def test_import_students_bad_line_writes_nothing(repo, sample_data):
    path = _subject_csv(sample_data)
    before = path.read_bytes()
    ids, errors = repo.import_students(S, "Gómez Ruiz, Marta\nSoloUnaPalabra\n", _v(path))
    assert ids == []
    assert len(errors) == 1 and errors[0].startswith("Línea 2")
    assert path.read_bytes() == before


def test_update_student_propagates(repo, sample_data):
    path = _subject_csv(sample_data)
    repo.update_student(
        S, "garcia-perez-lucia", "García Pérez", "Lucía María", "l@x.org", "Beca", _v(path)
    )
    student = next(s for s in repo.students(S).students if s.id == "garcia-perez-lucia")
    assert (student.nombre, student.email, student.observaciones) == (
        "Lucía María",
        "l@x.org",
        "Beca",
    )
    for exam in ("parcial-1", "trabajo-1"):
        roster = repo.roster(S, exam)
        entry = next(e for e in roster.entries if e.id == "garcia-perez-lucia")
        assert entry.nombre == "Lucía María"
    p1 = (sample_data / S / E / "alumnos.csv").read_text(encoding="utf-8")
    assert "garcia-perez-lucia,García Pérez,Lucía María,si,\n" in p1
    with pytest.raises(NotFound):
        repo.update_student(S, "nadie", "A", "B", "", "", _v(path))
    with pytest.raises(BadRequest):
        repo.update_student(S, "garcia-perez-lucia", "", "B", "", "", _v(path))


def test_update_student_refuses_when_roster_malformed(repo, sample_data):
    roster = sample_data / S / "trabajo-1" / "alumnos.csv"
    with open(roster, "a", encoding="utf-8") as fh:
        fh.write("x,y,z,,,extra\n")
    path = _subject_csv(sample_data)
    before = path.read_bytes()
    with pytest.raises(CsvMalformed):
        repo.update_student(S, "garcia-perez-lucia", "García", "L", "", "", _v(path))
    assert path.read_bytes() == before


def test_remove_student(repo, sample_data):
    path = _subject_csv(sample_data)
    pablo = sample_data / S / E / "notas" / "pablo.csv"
    before = pablo.read_bytes()
    exams = repo.remove_student(S, "alvarez-lopez-ana", _v(path))
    assert exams == ["parcial-1", "trabajo-1"]
    assert "alvarez-lopez-ana" not in [s.id for s in repo.students(S).students]
    assert pablo.read_bytes() == before
    assert repo.exams_containing(S, "alvarez-lopez-ana") == ["parcial-1", "trabajo-1"]
    assert repo.exams_containing(S, "perez-castro-hugo") == ["trabajo-1"]
    with pytest.raises(NotFound):
        repo.remove_student(S, "alvarez-lopez-ana", _v(path))


# --- exams -----------------------------------------------------------------


def test_list_exams(repo, sample_data):
    (sample_data / S / "apuntes").mkdir()
    exams = repo.list_exams(S)
    assert [e.slug for e in exams] == ["parcial-1", "trabajo-1"]
    p1 = exams[0]
    assert (p1.nombre, p1.tipo, p1.fecha, p1.n_roster, p1.n_presentados, p1.config_ok) == (
        "Primer parcial",
        "examen",
        "2026-11-03",
        6,
        5,
        True,
    )
    (sample_data / S / "trabajo-1" / "config.json").write_text("{", encoding="utf-8")
    broken = repo.list_exams(S)
    assert [e.slug for e in broken] == ["trabajo-1", "parcial-1"]
    assert broken[0].config_ok is False


def test_create_exam_tree(repo, sample_data):
    slug = repo.create_exam(S, "Examen final", "examen", "2027-01-20", True)
    assert slug == "examen-final"
    exam_dir = sample_data / S / slug
    config = json.loads((exam_dir / "config.json").read_text(encoding="utf-8"))
    assert config == {
        "nombre": "Examen final",
        "tipo": "examen",
        "fecha": "2027-01-20",
        "nota_maxima": 10,
        "decimales": 2,
        "calculo_total": "suma",
        "criterios": [],
    }
    roster = (exam_dir / "alumnos.csv").read_text(encoding="utf-8")
    expected = (sample_data / S / "trabajo-1" / "alumnos.csv").read_text(encoding="utf-8")
    assert roster == expected
    for folder in ("enunciado", "entregas", "notas", "revisiones"):
        assert (exam_dir / folder).is_dir()
        assert list((exam_dir / folder).iterdir()) == []
    assert repo.exam_dir(S, slug) == exam_dir
    assert repo.create_exam(S, "Examen final", "trabajo", "", False) == "examen-final-2"
    empty = (sample_data / S / "examen-final-2" / "alumnos.csv").read_text(encoding="utf-8")
    assert empty == "id,apellidos,nombre,presentado,observaciones\n"
    with pytest.raises(BadRequest):
        repo.create_exam(S, "X", "otro", "", True)
    with pytest.raises(BadRequest):
        repo.create_exam(S, "X", "examen", "20/01/2027", True)
    with pytest.raises(BadRequest):
        repo.create_exam(S, "", "examen", "", True)


def test_exam_dir_not_found(repo, sample_data):
    (sample_data / S / "apuntes").mkdir()
    for exam in ("no-existe", "apuntes", "..", "../mecanica-de-vuelo"):
        with pytest.raises(NotFound):
            repo.exam_dir(S, exam)
    with pytest.raises(NotFound):
        repo.exam_dir("no-existe", E)


def test_exam_config(repo, sample_data):
    cfg, issues, version = repo.exam_config(S, E)
    assert cfg.leaf_ids() == ["ej1a", "ej1b", "ej2", "ej3"]
    assert issues == []
    assert version == _v(sample_data / S / E / "config.json")


def test_save_exam_config_json(repo, sample_data):
    path = sample_data / S / E / "config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["criterios"].append({"id": "ej4", "nombre": "Ejercicio 4", "maximo": 1})
    issues = repo.save_exam_config_json(S, E, json.dumps(data), _v(path))
    assert [i.level for i in issues] == ["aviso"]
    saved = path.read_text(encoding="utf-8")
    assert '"id": "ej4"' in saved and saved.endswith("}\n")
    assert '"peso": 1' in saved.split('"ej4"')[1]


def test_save_exam_config_json_errors_write_nothing(repo, sample_data):
    path = sample_data / S / E / "config.json"
    before = path.read_bytes()
    data = json.loads(before)
    data["criterios"][1]["id"] = "ej3"
    issues = repo.save_exam_config_json(S, E, json.dumps(data), _v(path))
    assert any(i.level == "error" for i in issues)
    issues = repo.save_exam_config_json(S, E, "{", _v(path))
    assert issues[0].level == "error" and issues[0].message.startswith("JSON no válido")
    assert path.read_bytes() == before


def test_orphan_columns(repo, sample_data):
    assert repo.orphan_columns(S, E) == []
    path = sample_data / S / E / "config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["criterios"][2]
    repo.save_exam_config_json(S, E, json.dumps(data), _v(path))
    assert repo.orphan_columns(S, E) == ["ej3"]
    rev = sample_data / S / E / "revisiones" / "01-2026-11-20.csv"
    rev.write_text(
        "id,alumno,ej1a,ej1b,ej2,ej3,vacia,total,motivo\nfernandez-rey-carlos,,,1.5,,,,6,x\n",
        encoding="utf-8",
    )
    assert repo.orphan_columns(S, E) == ["ej3"]


# --- roster ----------------------------------------------------------------


def _roster_csv(root, exam=E):
    return root / S / exam / "alumnos.csv"


def test_roster_diff(repo):
    only_subject, only_exam = repo.roster_diff(S, E)
    assert [s.id for s in only_subject] == ["perez-castro-hugo"]
    assert [e.id for e in only_exam] == ["ramos-gil-irene"]


def test_add_to_roster(repo, sample_data):
    path = _roster_csv(sample_data)
    repo.add_to_roster(S, E, ["perez-castro-hugo"], _v(path))
    entry = next(e for e in repo.roster(S, E).entries if e.id == "perez-castro-hugo")
    assert (entry.apellidos, entry.nombre, entry.presentado) == ("Pérez Castro", "Hugo", "")
    assert repo.roster_diff(S, E)[0] == []
    with pytest.raises(NotFound):
        repo.add_to_roster(S, E, ["nadie"], _v(path))


def test_update_roster_entry(repo, sample_data):
    path = _roster_csv(sample_data)
    repo.update_roster_entry(S, E, "alvarez-lopez-ana", "NP", "Enferma", _v(path))
    assert "alvarez-lopez-ana,Álvarez López,Ana,no,Enferma\n" in path.read_text(encoding="utf-8")
    with pytest.raises(BadRequest):
        repo.update_roster_entry(S, E, "alvarez-lopez-ana", "quizá", "", _v(path))
    with pytest.raises(NotFound):
        repo.update_roster_entry(S, E, "nadie", "si", "", _v(path))


def test_update_roster_entry_keeps_unparsable_current_value(repo, sample_data):
    path = _roster_csv(sample_data)
    text = path.read_text(encoding="utf-8").replace("Otero Vidal,Sara,si", "Otero Vidal,Sara,?")
    path.write_text(text, encoding="utf-8")
    repo.update_roster_entry(S, E, "otero-vidal-sara", "?", "Revisar", _v(path))
    assert "otero-vidal-sara,Otero Vidal,Sara,?,Revisar\n" in path.read_text(encoding="utf-8")


def test_mark_present(repo, sample_data):
    path = _roster_csv(sample_data, "trabajo-1")
    assert repo.mark_present(S, "trabajo-1", _v(path)) == 6
    assert all(e.presentado == "si" for e in repo.roster(S, "trabajo-1").entries)
    before = _v(path)
    assert repo.mark_present(S, "trabajo-1", before) == 0
    assert _v(path) == before
    roster = _roster_csv(sample_data)
    with pytest.raises(VersionConflict):
        repo.mark_present(S, E, STALE)
    assert "martinez-souto-diego,Martínez Souto,Diego,no," in roster.read_text(encoding="utf-8")


def test_remove_from_roster(repo, sample_data):
    path = _roster_csv(sample_data)
    repo.remove_from_roster(S, E, "ramos-gil-irene", _v(path))
    assert "ramos-gil-irene" not in path.read_text(encoding="utf-8")
    with pytest.raises(NotFound):
        repo.remove_from_roster(S, E, "ramos-gil-irene", _v(path))


# --- graders and grades ----------------------------------------------------


def test_graders_and_create(repo, sample_data):
    assert repo.graders(S, E) == ["claude", "pablo"]
    assert repo.create_grader(S, E, "Claude Opus") == "claude-opus"
    path = sample_data / S / E / "notas" / "claude-opus.csv"
    assert path.read_text(encoding="utf-8") == "id,alumno,ej1a,ej1b,ej2,ej3,total,comentario\n"
    for bad in ("final", "Final", "pablo", "  "):
        with pytest.raises(BadRequest):
            repo.create_grader(S, E, bad)


def test_sheet(repo):
    assert repo.sheet(S, E, "pablo").row("alvarez-lopez-ana")["total"] == "9"
    assert repo.sheet(S, E, "final").name == "final"
    for bad in ("nadie", "../alumnos"):
        with pytest.raises(NotFound):
            repo.sheet(S, E, bad)


def test_save_grade_row_error_leaves_file(repo, sample_data):
    path = sample_data / S / E / "notas" / "pablo.csv"
    before = path.read_bytes()
    version, errors = repo.save_grade_row(
        S, E, "pablo", "garcia-perez-lucia", {"ej1a": "5"}, _v(path)
    )
    assert version == _v(path)
    assert set(errors) == {"ej1a"}
    assert path.read_bytes() == before


def test_save_grade_row_ok(repo, sample_data):
    path = sample_data / S / E / "notas" / "pablo.csv"
    version, errors = repo.save_grade_row(
        S, E, "pablo", "garcia-perez-lucia", {"ej2": "3", "ej3": "2,5"}, _v(path)
    )
    assert errors == {}
    assert version == _v(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert 'garcia-perez-lucia,"García Pérez, Lucía",2,2,3,2.5,9.5,' in lines
    version2, errors2 = repo.save_grade_row(
        S, E, "pablo", "garcia-perez-lucia", {"comentario": " Bien "}, version
    )
    assert errors2 == {} and version2 != version
    with pytest.raises(BadRequest):
        repo.save_grade_row(S, E, "pablo", "garcia-perez-lucia", {"origen": "x"}, version2)
    with pytest.raises(NotFound):
        repo.save_grade_row(S, E, "pablo", "nadie", {"ej2": "1"}, version2)
    with pytest.raises(NotFound):
        repo.save_grade_row(S, E, "nadie", "garcia-perez-lucia", {"ej2": "1"}, version2)


def test_save_grade_row_final_sets_origen(repo, sample_data):
    path = sample_data / S / E / "notas" / "final.csv"
    _, errors = repo.save_grade_row(S, E, "final", "alvarez-lopez-ana", {"ej2": "2.5"}, _v(path))
    assert errors == {}
    row = next(r for r in read_table(path).rows if r["id"] == "alvarez-lopez-ana")
    assert row["origen"] == "manual" and row["total"] == "8.5"


def test_save_grade_row_creates_final(repo, sample_data):
    path = sample_data / S / E / "notas" / "final.csv"
    path.unlink()
    _, errors = repo.save_grade_row(S, E, "final", "otero-vidal-sara", {"ej1a": "1"}, "")
    assert errors == {}
    assert path.read_text(encoding="utf-8") == (
        "id,alumno,ej1a,ej1b,ej2,ej3,total,comentario,origen\n"
        'otero-vidal-sara,"Otero Vidal, Sara",1,,,,,,manual\n'
    )


def test_feedback(repo, sample_data):
    text, version = repo.feedback(S, E, "claude", "alvarez-lopez-ana")
    assert text.startswith("# Álvarez López, Ana")
    assert version != ""
    text, version = repo.feedback(S, E, "pablo", "alvarez-lopez-ana")
    assert (text, version) == ("", "")
    repo.save_feedback(S, E, "pablo", "alvarez-lopez-ana", "Línea 1\r\nLínea 2", "")
    path = sample_data / S / E / "notas" / "pablo" / "alvarez-lopez-ana.md"
    assert path.read_text(encoding="utf-8") == "Línea 1\nLínea 2\n"
    repo.save_feedback(S, E, "pablo", "alvarez-lopez-ana", "   ", _v(path))
    assert not path.exists()
    trashed = list((sample_data / ".papelera").rglob("alvarez-lopez-ana.md"))
    assert len(trashed) == 1
    with pytest.raises(NotFound):
        repo.feedback(S, E, "nadie", "alvarez-lopez-ana")
    with pytest.raises(NotFound):
        repo.feedback(S, E, "pablo", "../../config")


# --- files -----------------------------------------------------------------


def test_area_re():
    assert AREA_RE.match("enunciado")
    assert AREA_RE.match("entregas/alvarez-lopez-ana/original")
    assert AREA_RE.match("entregas/alvarez-lopez-ana/corregido")
    for bad in ("notas", "entregas/../notas/original", "entregas/x/otro", "enunciado/sub"):
        assert not AREA_RE.match(bad)


def test_list_files(repo):
    files = repo.list_files(S, E, "enunciado")
    assert [f.name for f in files] == ["enunciado.pdf", "rubrica.pdf"]
    first = files[0]
    assert first.rel_path == f"{S}/{E}/enunciado/enunciado.pdf"
    assert first.is_pdf and first.size > 0
    assert repo.list_files(S, E, "entregas/perez-castro-hugo/original") == []
    with pytest.raises(BadRequest):
        repo.list_files(S, E, "entregas/../notas/original")


def test_list_files_skips_dotfiles(repo, sample_data):
    assert repo.list_files(S, "trabajo-1", "enunciado") == []


def test_save_upload(repo, sample_data):
    area = "entregas/perez-castro-hugo/original"
    rel = repo.save_upload(S, E, area, "../../evil.pdf", b"%PDF-1")
    assert rel == f"{S}/{E}/{area}/evil.pdf"
    assert (sample_data / rel).read_bytes() == b"%PDF-1"
    rel2 = repo.save_upload(S, E, area, "../../evil.pdf", b"%PDF-2")
    assert rel2 == f"{S}/{E}/{area}/evil (2).pdf"
    with pytest.raises(BadRequest):
        repo.save_upload(S, E, "../../x", "a.pdf", b"")


def test_trash_file(repo, sample_data):
    rel = f"{S}/{E}/enunciado/rubrica.pdf"
    repo.trash_file(S, E, rel)
    assert not (sample_data / rel).exists()
    trashed = list((sample_data / ".papelera").rglob("rubrica.pdf"))
    assert len(trashed) == 1
    assert trashed[0].relative_to(sample_data / ".papelera").parts[1:] == tuple(rel.split("/"))


def test_trash_file_rejects(repo, sample_data):
    config = sample_data / S / E / "config.json"
    with pytest.raises(BadRequest):
        repo.trash_file(S, E, f"{S}/{E}/config.json")
    with pytest.raises(BadRequest):
        repo.trash_file(S, E, f"{S}/{E}/notas/pablo.csv")
    with pytest.raises(BadRequest):
        repo.trash_file(S, E, f"{S}/trabajo-1/alumnos.csv")
    with pytest.raises(PathOutsideData):
        repo.trash_file(S, E, "../../../etc/passwd")
    with pytest.raises(NotFound):
        repo.trash_file(S, E, f"{S}/{E}/enunciado/no-existe.pdf")
    assert config.exists()


def test_submission_counts_and_orphans(repo, sample_data):
    counts = repo.submission_counts(S, E)
    assert counts["alvarez-lopez-ana"] == (1, 1)
    assert counts["fernandez-rey-carlos"] == (1, 0)
    assert counts["garcia-perez-lucia"] == (0, 0)
    assert repo.orphan_submission_dirs(S, E) == []
    repo.save_upload(S, E, "entregas/perez-castro-hugo/original", "a.pdf", b"x")
    assert repo.orphan_submission_dirs(S, E) == ["perez-castro-hugo"]
    assert repo.submission_counts(S, E)["perez-castro-hugo"] == (1, 0)


# --- version checks --------------------------------------------------------

VERSIONED = {
    "update_subject_meta": (
        f"{S}/asignatura.json",
        lambda r: r.update_subject_meta(S, "N", "", "", STALE),
    ),
    "add_student": (f"{S}/alumnos.csv", lambda r: r.add_student(S, "A", "B", "", STALE)),
    "import_students": (f"{S}/alumnos.csv", lambda r: r.import_students(S, "A, B", STALE)),
    "update_student": (
        f"{S}/alumnos.csv",
        lambda r: r.update_student(S, "alvarez-lopez-ana", "A", "B", "", "", STALE),
    ),
    "remove_student": (
        f"{S}/alumnos.csv",
        lambda r: r.remove_student(S, "alvarez-lopez-ana", STALE),
    ),
    "save_exam_config_json": (
        f"{S}/{E}/config.json",
        lambda r: r.save_exam_config_json(S, E, "{}", STALE),
    ),
    "add_to_roster": (
        f"{S}/{E}/alumnos.csv",
        lambda r: r.add_to_roster(S, E, ["perez-castro-hugo"], STALE),
    ),
    "update_roster_entry": (
        f"{S}/{E}/alumnos.csv",
        lambda r: r.update_roster_entry(S, E, "alvarez-lopez-ana", "no", "", STALE),
    ),
    "remove_from_roster": (
        f"{S}/{E}/alumnos.csv",
        lambda r: r.remove_from_roster(S, E, "alvarez-lopez-ana", STALE),
    ),
    "save_grade_row": (
        f"{S}/{E}/notas/pablo.csv",
        lambda r: r.save_grade_row(S, E, "pablo", "garcia-perez-lucia", {"ej2": "1"}, STALE),
    ),
    "save_feedback": (
        f"{S}/{E}/notas/claude/alvarez-lopez-ana.md",
        lambda r: r.save_feedback(S, E, "claude", "alvarez-lopez-ana", "x", STALE),
    ),
}


@pytest.mark.parametrize("method", list(VERSIONED))
def test_stale_version_raises(repo, sample_data, method):
    _, call = VERSIONED[method]
    before = _snapshot(sample_data)
    with pytest.raises(VersionConflict):
        call(repo)
    assert _snapshot(sample_data) == before


def test_malformed_csv_blocks_writes(repo, sample_data):
    path = _subject_csv(sample_data)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("x,y,z,,,extra\n")
    with pytest.raises(CsvMalformed):
        repo.add_student(S, "A", "B", "", _v(path))
