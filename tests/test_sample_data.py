import json
from pathlib import Path

from conftest import SAMPLE_DATA


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_parcial_config_is_json(sample_data):
    config = sample_data / "mecanica-de-vuelo" / "parcial-1" / "config.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["nombre"] == "Primer parcial"


def test_copy_does_not_modify_sample(sample_data):
    before = _snapshot(SAMPLE_DATA)
    assert _snapshot(sample_data) == before
    (sample_data / "mecanica-de-vuelo" / "alumnos.csv").write_text("id\n", encoding="utf-8")
    (sample_data / "nuevo.txt").write_text("x", encoding="utf-8")
    assert _snapshot(SAMPLE_DATA) == before
    assert sample_data != SAMPLE_DATA
