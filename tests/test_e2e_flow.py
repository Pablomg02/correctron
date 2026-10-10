"""Whole flow through the web on an empty data root, threading every version."""

import json
from datetime import date

from conftest import oob_value, row_html
from fastapi.testclient import TestClient

from correctron.web.app import create_app

LLM_CSV = (
    "id;alumno;p1a;p1b;p2;total;comentario\n"
    "gomez-ruiz-marta;Gómez Ruiz, Marta;3;2;4;9;Bien\n"
    "lopez-diaz-pedro;López Díaz, Pedro;2;1,5;2,5;6;\n"
)


def test_full_flow(tmp_path):
    root = tmp_path / "data"
    client = TestClient(create_app(root))
    assert (root / "LEEME.md").is_file()

    # 1. Subject.
    resp = client.post("/asignaturas", data={"nombre": "Prueba"}, follow_redirects=False)
    assert resp.headers["location"] == "/a/prueba"

    # 2. Import three students.
    version = oob_value(client.get("/a/prueba").text, "version-lista")
    resp = client.post(
        "/a/prueba/importar-alumnos",
        data={
            "texto": "Gómez Ruiz, Marta\nLópez Díaz, Pedro\nSanz Mora, Julia\n",
            "version": version,
        },
    )
    assert "3 alumnos importados" in resp.text

    # 3. Exam, copying the students.
    resp = client.post(
        "/a/prueba/examenes",
        data={
            "nombre": "Examen final",
            "tipo": "examen",
            "fecha": "2027-01-20",
            "copiar_alumnos": "1",
        },
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/a/prueba/e/examen-final?tab=config"
    exam = "/a/prueba/e/examen-final"
    exam_dir = root / "prueba" / "examen-final"

    # 4. Presentado, threading the roster version through the inline edits.
    version = oob_value(client.get(f"{exam}?tab=alumnos").text, "version-lista")
    for sid, value in (
        ("gomez-ruiz-marta", "si"),
        ("lopez-diaz-pedro", "si"),
        ("sanz-mora-julia", "no"),
    ):
        resp = client.post(
            f"{exam}/alumnos/{sid}",
            data={"presentado": value, "observaciones": "", "version": version},
        )
        assert resp.status_code == 200
        version = oob_value(resp.text, "version-lista")

    # 5. Configuration.
    config = {
        "nombre": "Examen final",
        "tipo": "examen",
        "fecha": "2027-01-20",
        "nota_maxima": 10,
        "decimales": 2,
        "calculo_total": "suma",
        "criterios": [
            {
                "id": "p1",
                "nombre": "Pregunta 1",
                "peso": 1,
                "subcriterios": [
                    {"id": "p1a", "nombre": "a", "maximo": 3},
                    {"id": "p1b", "nombre": "b", "maximo": 2},
                ],
            },
            {"id": "p2", "nombre": "Pregunta 2", "maximo": 5, "peso": 1},
        ],
    }
    version = oob_value(client.get(f"{exam}?tab=config").text, "version-config")
    resp = client.post(
        f"{exam}/config",
        data={"config_json": json.dumps(config), "version": version},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # 6. Grader pablo and two rows.
    resp = client.post(f"{exam}/correctores", data={"nombre": "pablo"}, follow_redirects=False)
    assert resp.headers["location"] == f"{exam}?tab=notas&corrector=pablo"
    version = oob_value(client.get(resp.headers["location"]).text, "version-hoja")
    for sid, cells in (
        ("gomez-ruiz-marta", {"p1a": "3", "p1b": "1,5", "p2": "4"}),
        ("lopez-diaz-pedro", {"p1a": "2", "p1b": "2", "p2": "2,5"}),
    ):
        resp = client.post(
            f"{exam}/notas/pablo/{sid}", data={**cells, "comentario": "", "version": version}
        )
        assert resp.status_code == 200
        assert "hx-retarget" not in resp.headers
        version = oob_value(resp.text, "version-hoja")

    # 7. An LLM writes its own sheet with ";" and decimal commas.
    llm = exam_dir / "notas" / "llm.csv"
    llm.write_text(LLM_CSV, encoding="utf-8")

    # 8. Compare.
    resp = client.get(f"{exam}?tab=comparar")
    marta = row_html(resp.text, "gomez-ruiz-marta")
    assert "8,5" in marta and ">9<" in marta

    # 9. Bulk copy pablo, then use llm for Marta.
    resp = client.post(f"{exam}/final/copiar", data={"corrector": "pablo"}, follow_redirects=False)
    assert "copiadas-2" in resp.headers["location"]
    assert "2 filas copiadas a final" in client.get(resp.headers["location"]).text
    resp = client.post(
        f"{exam}/final/gomez-ruiz-marta/usar",
        data={"corrector": "llm"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200

    # 10. Revision session; revise Pedro.
    resp = client.post(f"{exam}/revisiones", follow_redirects=False)
    rev = f"01-{date.today().isoformat()}.csv"
    assert resp.headers["location"] == f"{exam}?tab=revisiones&rev={rev}"
    page = client.get(f"{exam}?tab=revisiones&rev={rev}&alumno=lopez-diaz-pedro")
    resp = client.post(
        f"{exam}/revisiones/{rev}/lopez-diaz-pedro",
        data={
            "p1a": "2",
            "p1b": "2",
            "p2": "3",
            "motivo": "Recontado",
            "version": oob_value(page.text, "version-revision"),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # 11. Summary.
    resp = client.get(exam)
    assert ">9<" in row_html(resp.text, "gomez-ruiz-marta")
    pedro = row_html(resp.text, "lopez-diaz-pedro")
    assert ">7<" in pedro and "revisada" in pedro
    assert "NP" in row_html(resp.text, "sanz-mora-julia")

    # 12. Files, byte for byte.
    assert (exam_dir / "notas" / "final.csv").read_text(encoding="utf-8") == (
        "id,alumno,p1a,p1b,p2,total,comentario,origen\n"
        'gomez-ruiz-marta,"Gómez Ruiz, Marta",3,2,4,9,Bien,llm\n'
        'lopez-diaz-pedro,"López Díaz, Pedro",2,2,2.5,6.5,,pablo\n'
    )
    assert (exam_dir / "revisiones" / rev).read_text(encoding="utf-8") == (
        'id,alumno,p1a,p1b,p2,total,motivo\nlopez-diaz-pedro,"López Díaz, Pedro",,,3,7,Recontado\n'
    )

    # 13. The LLM file is untouched.
    assert llm.read_text(encoding="utf-8") == LLM_CSV
