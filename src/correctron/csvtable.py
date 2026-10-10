"""Tolerant CSV reading and writing that keeps the dialect and unknown columns (D9)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

from .fsutil import UTF8_BOM, atomic_write_text

_CANDIDATES = (",", ";", "\t")


class CsvMalformed(Exception):
    """The table has rows with more cells than the header and cannot be written."""

    def __init__(self, path: Path | str, lines: list[int]):
        self.path = path
        self.lines = list(lines)
        joined = ", ".join(str(n) for n in self.lines)
        super().__init__(f"{path}: filas con más celdas que la cabecera (líneas {joined})")


@dataclass
class Table:
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    delimiter: str = ","
    bom: bool = False
    encoding: str = "utf-8"
    malformed: list[int] = field(default_factory=list)


def _decode(data: bytes) -> tuple[str, bool, str]:
    bom = data.startswith(UTF8_BOM)
    if bom:
        data = data[len(UTF8_BOM) :]
    try:
        return data.decode("utf-8"), bom, "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), False, "cp1252"


def _detect_delimiter(text: str) -> str:
    header = next((line for line in text.splitlines() if line.strip()), "")
    counts = {c: header.count(c) for c in _CANDIDATES}
    best = max(counts.values())
    winners = [c for c, n in counts.items() if n == best]
    if best == 0 or len(winners) > 1:
        return ","
    return winners[0]


def read_table(path: Path) -> Table:
    """Read a CSV tolerantly. A missing file gives an empty Table()."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return Table()
    text, bom, encoding = _decode(data)
    delimiter = _detect_delimiter(text)
    table = Table(delimiter=delimiter, bom=bom, encoding=encoding)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    header_seen = False
    try:
        for record in reader:
            cells = [cell.strip() for cell in record]
            if not any(cells):
                continue
            if not header_seen:
                table.columns = [cell.lower() for cell in cells]
                header_seen = True
                continue
            width = len(table.columns)
            if len(cells) > width:
                table.malformed.append(reader.line_num)
                cells = cells[:width]
            cells += [""] * (width - len(cells))
            table.rows.append(dict(zip(table.columns, cells, strict=True)))
    except csv.Error:
        # Structural damage the csv module cannot read past (e.g. a huge field):
        # keep what was read and block writes.
        table.malformed.append(reader.line_num + 1)
    return table


def write_table(path: Path, table: Table) -> None:
    """Write header plus rows in column order, keeping delimiter, encoding and BOM."""
    if table.malformed:
        raise CsvMalformed(path, table.malformed)
    buf = io.StringIO()
    writer = csv.writer(
        buf, delimiter=table.delimiter, lineterminator="\n", quoting=csv.QUOTE_MINIMAL
    )
    writer.writerow(table.columns)
    for row in table.rows:
        writer.writerow([row.get(col, "") for col in table.columns])
    atomic_write_text(path, buf.getvalue(), bom=table.bom, encoding=table.encoding)
