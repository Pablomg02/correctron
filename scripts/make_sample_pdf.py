"""Write a valid one-page PDF with a line of text in Helvetica.

Usage: python scripts/make_sample_pdf.py OUT TEXT

Only the standard library is used: the PDF objects are built by hand and the
cross-reference offsets are computed from the bytes written.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _pdf_string(text: str) -> bytes:
    """Encode text as a PDF literal string in WinAnsiEncoding (cp1252)."""
    out = bytearray(b"(")
    for byte in text.encode("cp1252", errors="replace"):
        if byte in (0x28, 0x29, 0x5C):  # ( ) \
            out += b"\\" + bytes([byte])
        elif 0x20 <= byte < 0x7F:
            out.append(byte)
        else:
            out += b"\\%03o" % byte
    out += b")"
    return bytes(out)


def build_pdf(text: str) -> bytes:
    content = b"BT /F1 18 Tf 72 720 Td " + _pdf_string(text) + b" Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_offset = len(pdf)
    pdf += b"xref\n0 %d\n" % (len(objects) + 1)
    pdf += b"0000000000 65535 f \n"
    for offset in offsets:
        pdf += b"%010d 00000 n \n" % offset
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    pdf += b"startxref\n%d\n%%%%EOF\n" % xref_offset
    return bytes(pdf)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("Uso: make_sample_pdf.py SALIDA TEXTO", file=sys.stderr)
        return 2
    out = Path(args[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_pdf(args[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
