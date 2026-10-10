"""File-system primitives: atomic writes, safe paths, versions and trash."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

UTF8_BOM = b"\xef\xbb\xbf"
TRASH_DIR = ".papelera"
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class PathOutsideData(Exception):
    """A path resolves outside the data root."""


class VersionConflict(Exception):
    """The file changed since the client read it."""


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write through a temporary file in the same directory, fsync, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_text(path: Path, text: str, *, bom: bool = False, encoding: str = "utf-8") -> None:
    """Encode `text` (no newline translation) and write it atomically.

    The BOM is only written for UTF-8. A cp1252 text that holds characters
    cp1252 cannot encode is written as UTF-8 instead, so no data is lost.
    """
    if encoding.lower().replace("_", "-") in ("utf-8", "utf8"):
        data = (UTF8_BOM if bom else b"") + text.encode("utf-8")
    else:
        try:
            data = text.encode(encoding)
        except UnicodeEncodeError:
            data = text.encode("utf-8")
    atomic_write_bytes(path, data)


def safe_resolve(root: Path, rel: str) -> Path:
    """Resolve `root / rel`, raising PathOutsideData if it leaves the root."""
    base = root.resolve()
    target = (base / rel).resolve()
    if not target.is_relative_to(base):
        raise PathOutsideData(rel)
    return target


def file_version(path: Path) -> str:
    """First 16 hex chars of the SHA-256 of the file, or "" if it is missing."""
    try:
        data = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return ""
    return hashlib.sha256(data).hexdigest()[:16]


def check_version(path: Path, version: str) -> None:
    """Raise VersionConflict when the file's current version differs."""
    if file_version(path) != version:
        raise VersionConflict(str(path))


def _is_ignored(rel_parts: tuple[str, ...]) -> bool:
    return any(part.startswith(".") for part in rel_parts) or ".tmp-" in rel_parts[-1]


def tree_fingerprint(path: Path) -> str:
    """SHA-256 (16 hex chars) of (relative path, mtime_ns, size) of every file.

    Skips `.papelera`, any other name starting with `.`, and `*.tmp-*` files.
    """
    entries: list[tuple[str, int, int]] = []
    if path.is_dir():
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for name in filenames:
                full = Path(dirpath) / name
                rel = full.relative_to(path)
                if _is_ignored(rel.parts):
                    continue
                try:
                    st = full.stat()
                except FileNotFoundError:
                    continue
                entries.append((rel.as_posix(), st.st_mtime_ns, st.st_size))
    entries.sort()
    digest = hashlib.sha256()
    for rel, mtime, size in entries:
        digest.update(f"{rel}\0{mtime}\0{size}\n".encode())
    return digest.hexdigest()[:16]


def unique_path(directory: Path, name: str) -> Path:
    """`directory / name`, inserting " (2)", " (3)"… before the extension if taken."""
    candidate = directory / name
    if not candidate.exists():
        return candidate
    dot = name.rfind(".")
    stem, ext = (name[:dot], name[dot:]) if dot > 0 else (name, "")
    n = 2
    while True:
        candidate = directory / f"{stem} ({n}){ext}"
        if not candidate.exists():
            return candidate
        n += 1


def move_to_trash(root: Path, path: Path, *, now: datetime | None = None) -> Path:
    """Move a file to `root/.papelera/<YYYYMMDD-HHMMSS>/<relative path>`."""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = root.resolve()
    rel = path.resolve().relative_to(base)
    dest_dir = (base / TRASH_DIR / stamp / rel).parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_path(dest_dir, rel.name)
    shutil.move(str(path), str(dest))
    return root / dest.relative_to(base)


def sanitize_filename(name: str) -> str:
    """Last path component, no control characters, no leading/trailing spaces or dots."""
    last = re.split(r"[/\\]", name)[-1]
    cleaned = _CONTROL_RE.sub("", last).strip(" .")
    return cleaned or "archivo"
