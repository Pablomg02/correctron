"""Slugs for folder names, student ids and grader names (D2, D20)."""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase ASCII slug with '-' separators; "x" when nothing is left."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    slug = _NON_ALNUM_RE.sub("-", stripped.lower()).strip("-")
    return slug or "x"


def student_slug(apellidos: str, nombre: str, taken: set[str]) -> str:
    """Slug `apellidos-nombre`, with -2, -3… appended while it is taken."""
    base = slugify(f"{apellidos} {nombre}")
    candidate = base
    n = 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    return candidate
