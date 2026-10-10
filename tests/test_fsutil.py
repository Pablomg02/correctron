import os
from datetime import datetime
from pathlib import Path

import pytest

from correctron.fsutil import (
    PathOutsideData,
    atomic_write_bytes,
    atomic_write_text,
    file_version,
    move_to_trash,
    safe_resolve,
    sanitize_filename,
    tree_fingerprint,
    unique_path,
)


def test_atomic_write_text_creates_parents_and_no_tmp(tmp_path):
    target = tmp_path / "a" / "b" / "f.txt"
    atomic_write_text(target, "hola\n")
    assert target.read_bytes() == b"hola\n"
    assert [p.name for p in target.parent.iterdir()] == ["f.txt"]


def test_atomic_write_text_bom_and_encoding(tmp_path):
    target = tmp_path / "f.csv"
    atomic_write_text(target, "Pérez\n", bom=True)
    assert target.read_bytes() == b"\xef\xbb\xbfP\xc3\xa9rez\n"
    atomic_write_text(target, "Pérez\n", encoding="cp1252")
    assert target.read_bytes() == b"P\xe9rez\n"


def test_atomic_write_bytes_replaces(tmp_path):
    target = tmp_path / "f.bin"
    target.write_bytes(b"old")
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"


def test_safe_resolve_inside(tmp_path):
    (tmp_path / "a").mkdir()
    assert safe_resolve(tmp_path, "a/b.txt") == (tmp_path / "a" / "b.txt").resolve()
    assert safe_resolve(tmp_path, "") == tmp_path.resolve()


@pytest.mark.parametrize("rel", ["../x", "/etc/passwd", "a/../../x"])
def test_safe_resolve_rejects_outside(tmp_path, rel):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(PathOutsideData):
        safe_resolve(root, rel)


def test_safe_resolve_rejects_symlink_outside(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    (root / "link.txt").symlink_to(outside)
    with pytest.raises(PathOutsideData):
        safe_resolve(root, "link.txt")


def test_file_version(tmp_path):
    target = tmp_path / "f.txt"
    assert file_version(target) == ""
    target.write_bytes(b"abc")
    version = file_version(target)
    assert len(version) == 16
    assert version == "ba7816bf8f01cfea"
    target.write_bytes(b"abd")
    assert file_version(target) != version


def test_tree_fingerprint_changes_on_modify(tmp_path):
    (tmp_path / "sub").mkdir()
    f = tmp_path / "sub" / "f.txt"
    f.write_text("a")
    first = tree_fingerprint(tmp_path)
    assert len(first) == 16
    assert tree_fingerprint(tmp_path) == first
    f.write_text("abc")
    assert tree_fingerprint(tmp_path) != first


def test_tree_fingerprint_ignores_trash_tmp_and_dotfiles(tmp_path):
    (tmp_path / "f.txt").write_text("a")
    first = tree_fingerprint(tmp_path)
    (tmp_path / ".papelera" / "x").mkdir(parents=True)
    (tmp_path / ".papelera" / "x" / "g.txt").write_text("b")
    (tmp_path / f"f.txt.tmp-{os.getpid()}").write_text("c")
    (tmp_path / ".gitkeep").write_text("")
    assert tree_fingerprint(tmp_path) == first


def test_move_to_trash(tmp_path):
    root = tmp_path / "data"
    src = root / "asig" / "ex" / "enunciado" / "a.pdf"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"%PDF-")
    dest = move_to_trash(root, src, now=datetime(2026, 11, 3, 9, 5, 7))
    assert dest == root / ".papelera" / "20261103-090507" / "asig" / "ex" / "enunciado" / "a.pdf"
    assert dest.read_bytes() == b"%PDF-"
    assert not src.exists()


def test_move_to_trash_never_overwrites(tmp_path):
    root = tmp_path / "data"
    now = datetime(2026, 11, 3, 9, 5, 7)
    for content in (b"1", b"2"):
        src = root / "a.txt"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(content)
        move_to_trash(root, src, now=now)
    trash = root / ".papelera" / "20261103-090507"
    assert sorted(p.read_bytes() for p in trash.iterdir()) == [b"1", b"2"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../evil.pdf", "evil.pdf"),
        ("C:\\Users\\x\\examen.pdf", "examen.pdf"),
        ("  .hidden.  ", "hidden"),
        ("a\x00b\x1f.txt", "ab.txt"),
        ("...", "archivo"),
        ("", "archivo"),
        ("dir/", "archivo"),
    ],
)
def test_sanitize_filename(name, expected):
    assert sanitize_filename(name) == expected


def test_unique_path(tmp_path: Path):
    assert unique_path(tmp_path, "evil.pdf") == tmp_path / "evil.pdf"
    (tmp_path / "evil.pdf").write_text("x")
    assert unique_path(tmp_path, "evil.pdf") == tmp_path / "evil (2).pdf"
    (tmp_path / "evil (2).pdf").write_text("x")
    assert unique_path(tmp_path, "evil.pdf") == tmp_path / "evil (3).pdf"
    (tmp_path / "LEEME").write_text("x")
    assert unique_path(tmp_path, "LEEME") == tmp_path / "LEEME (2)"
