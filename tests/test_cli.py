from pathlib import Path

import pytest

from correctron import cli


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

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    monkeypatch.setattr(cli.webbrowser, "open", fake_open)
    monkeypatch.setattr(cli.threading, "Timer", FakeTimer)
    return calls


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for option in ("--data", "--host", "--port", "--no-abrir"):
        assert option in out


def test_runs_server_with_defaults(fake_server, capsys, tmp_path, monkeypatch):
    monkeypatch.delenv("CORRECTRON_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    cli.main(["--no-abrir"])
    out = capsys.readouterr().out
    assert f"Correctron en http://127.0.0.1:8765 — datos: {tmp_path / 'data'}" in out
    _, host, port = fake_server["run"]
    assert (host, port) == ("127.0.0.1", 8765)
    assert (tmp_path / "data" / "LEEME.md").is_file()
    assert "open" not in fake_server


def test_opens_browser_unless_disabled(fake_server, tmp_path):
    cli.main(["--data", str(tmp_path / "d"), "--port", "8799"])
    assert fake_server["open"] == "http://127.0.0.1:8799"
    assert fake_server["timer"] == 1


def test_data_dir_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("CORRECTRON_DATA", str(tmp_path / "env"))
    assert cli.resolve_data_dir(str(tmp_path / "arg")) == (tmp_path / "arg").resolve()
    assert cli.resolve_data_dir(None) == (tmp_path / "env").resolve()
    monkeypatch.delenv("CORRECTRON_DATA")
    monkeypatch.chdir(tmp_path)
    assert cli.resolve_data_dir(None) == Path(tmp_path / "data").resolve()
