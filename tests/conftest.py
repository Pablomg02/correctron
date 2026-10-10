import re
import shutil
from html import unescape
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "ejemplo" / "data"


@pytest.fixture
def sample_data(tmp_path: Path) -> Path:
    """Copy of ejemplo/data in a temporary directory."""
    dest = tmp_path / "data"
    shutil.copytree(SAMPLE_DATA, dest)
    return dest


def oob_value(html: str, element_id: str) -> str:
    """Value of the `<input …>` tag whose id is `element_id` (any attribute order)."""
    for tag in re.findall(r"<input\b[^>]*>", html):
        attrs = dict(re.findall(r'([\w:-]+)="([^"]*)"', tag))
        if attrs.get("id") == element_id:
            return unescape(attrs.get("value", ""))
    pytest.fail(f"no <input id={element_id!r}> in the response")


def row_html(html: str, student_id: str) -> str:
    """The `<tr id="fila-<student_id>" …>…</tr>` fragment, nested tables included."""
    match = re.search(rf'<tr\b[^>]*\bid="fila-{re.escape(student_id)}"[^>]*>', html)
    if match is None:
        pytest.fail(f"no row fila-{student_id} in the response")
    depth = 0
    for tag in re.finditer(r"<(/?)tr\b[^>]*>", html[match.start() :]):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            return html[match.start() : match.start() + tag.end()]
    pytest.fail(f"row fila-{student_id} is not closed")


@pytest.fixture
def client(sample_data: Path) -> TestClient:
    """TestClient over a copy of the sample data."""
    from correctron.web.app import create_app

    return TestClient(create_app(sample_data))
