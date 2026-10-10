from conftest import row_html

S = "mecanica-de-vuelo"
E = f"/a/{S}/e/parcial-1"


def final_csv(sample_data):
    return (sample_data / S / "parcial-1" / "notas" / "final.csv").read_text(encoding="utf-8")


def cell(row: str, cls: str) -> str:
    """Text of the first <td class="… cls …"> of a row (nested tags included)."""
    start = row.index(f'class="{cls}')
    return row[start : row.index("</td>", start)]


def test_compare_ana(client):
    resp = client.get(f"{E}?tab=comparar")
    assert resp.status_code == 200
    ana = row_html(resp.text, "alvarez-lopez-ana")
    assert ">9<" in cell(ana, "total-pablo")
    assert ">8,5<" in cell(ana, "total-claude")
    delta = cell(ana, "col-delta")
    assert "0,5" in delta
    assert "delta-fuerte" not in ana


def test_compare_lucia_has_blank_delta(client):
    resp = client.get(f"{E}?tab=comparar")
    lucia = row_html(resp.text, "garcia-perez-lucia")
    delta = cell(lucia, "col-delta")
    assert delta.split(">", 1)[1].strip() == ""
    assert "parcial" in cell(lucia, "total-pablo")


def test_strong_delta(client, sample_data):
    path = sample_data / S / "parcial-1" / "notas" / "claude.csv"
    path.write_text(
        path.read_text(encoding="utf-8").replace(",1,0.5,2,1.5,5,", ",0,0,1,1,2,"),
        encoding="utf-8",
    )
    resp = client.get(f"{E}?tab=comparar")
    carlos = row_html(resp.text, "fernandez-rey-carlos")
    assert "delta-fuerte" in carlos
    assert "3,5" in cell(carlos, "col-delta")


def test_discrepancy_filter(client):
    resp = client.get(f"{E}?tab=comparar&filtro=discrepancias")
    assert resp.status_code == 200
    row_html(resp.text, "alvarez-lopez-ana")
    row_html(resp.text, "fernandez-rey-carlos")
    assert 'id="fila-garcia-perez-lucia"' not in resp.text
    assert 'id="fila-otero-vidal-sara"' not in resp.text


def test_leaf_details_highlight_discrepancy(client):
    resp = client.get(f"{E}?tab=comparar")
    ana = row_html(resp.text, "alvarez-lopez-ana")
    assert "<details" in ana
    assert 'class="discrepa"' in ana
    assert "Error menor en ej2" in ana
    assert "/archivo/mecanica-de-vuelo/parcial-1/notas/claude/alvarez-lopez-ana.md" in ana


def test_use_grader(client, sample_data):
    resp = client.post(
        f"{E}/final/garcia-perez-lucia/usar",
        data={"corrector": "claude"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert 'garcia-perez-lucia,"García Pérez, Lucía",2,2,3,3,10,,claude\n' in final_csv(sample_data)
    row = row_html(resp.text, "garcia-perez-lucia")
    assert "claude" in cell(row, "col-final")
    assert "huella-actual" in resp.text


def test_use_grader_without_row_is_400(client):
    resp = client.post(f"{E}/final/ramos-gil-irene/usar", data={"corrector": "pablo"})
    assert resp.status_code == 400


def test_use_existing_final_asks_confirmation(client):
    resp = client.get(f"{E}?tab=comparar")
    ana = row_html(resp.text, "alvarez-lopez-ana")
    assert "hx-confirm" in ana
    lucia = row_html(resp.text, "garcia-perez-lucia")
    assert "hx-confirm" not in lucia


def test_bulk_copy(client, sample_data):
    path = sample_data / S / "parcial-1" / "notas" / "claude.csv"
    path.write_text(
        path.read_text(encoding="utf-8")
        + 'martinez-souto-diego,"Martínez Souto, Diego",1,1,1,1,4,\n',
        encoding="utf-8",
    )
    resp = client.post(f"{E}/final/copiar", data={"corrector": "claude"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "copiadas-2" in resp.headers["location"]
    text = final_csv(sample_data)
    assert "garcia-perez-lucia" in text and "otero-vidal-sara" in text
    assert "martinez-souto-diego" not in text
    assert 'alvarez-lopez-ana,"Álvarez López, Ana",2,1.5,3,2.5,9,Muy bien,pablo' in text
    page = client.get(resp.headers["location"])
    assert "2 filas copiadas a final" in page.text
