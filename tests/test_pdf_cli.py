import pytest

from correctron import pdf_cli


@pytest.fixture
def fake_server(monkeypatch):
    calls = {}

    def fake_run(app, host, port):
        calls["run"] = (app, host, port)

    def fake_open(url):
        calls["open"] = url

    class FakeTimer:
        def __init__(self, delay, func, args=()):
            calls["timer"] = delay
            self.func, self.args = func, args

        def start(self):
            self.func(*self.args)

    monkeypatch.setattr(pdf_cli.uvicorn, "run", fake_run)
    monkeypatch.setattr(pdf_cli.webbrowser, "open", fake_open)
    monkeypatch.setattr(pdf_cli.threading, "Timer", FakeTimer)
    return calls


def test_help_lists_options_and_default_port(capsys):
    with pytest.raises(SystemExit) as exc:
        pdf_cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for option in ("--data", "--host", "--port", "--no-abrir"):
        assert option in out
    assert "8766" in out


def test_runs_server_with_defaults(fake_server, capsys, tmp_path, monkeypatch):
    monkeypatch.delenv("CORRECTRON_PDF_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    pdf_cli.main(["--no-abrir"])
    out = capsys.readouterr().out
    assert f"Correctron PDF en http://127.0.0.1:8766 — datos: {tmp_path / 'pdfs'}" in out
    _, host, port = fake_server["run"]
    assert (host, port) == ("127.0.0.1", 8766)
    assert (tmp_path / "pdfs").is_dir()
    assert "open" not in fake_server


def test_env_variable_chooses_data_folder(fake_server, tmp_path, monkeypatch):
    monkeypatch.setenv("CORRECTRON_PDF_DATA", str(tmp_path / "env"))
    monkeypatch.chdir(tmp_path)
    pdf_cli.main(["--no-abrir"])
    assert (tmp_path / "env").is_dir()
    assert not (tmp_path / "pdfs").exists()


def test_opens_browser_unless_disabled(fake_server, tmp_path):
    pdf_cli.main(["--data", str(tmp_path / "d"), "--port", "8799"])
    assert fake_server["open"] == "http://127.0.0.1:8799"
    assert fake_server["timer"] == 1


def test_data_dir_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("CORRECTRON_PDF_DATA", str(tmp_path / "env"))
    assert pdf_cli.resolve_data_dir(str(tmp_path / "arg")) == (tmp_path / "arg").resolve()
    assert pdf_cli.resolve_data_dir(None) == (tmp_path / "env").resolve()
    monkeypatch.delenv("CORRECTRON_PDF_DATA")
    monkeypatch.chdir(tmp_path)
    assert pdf_cli.resolve_data_dir(None) == (tmp_path / "pdfs").resolve()
