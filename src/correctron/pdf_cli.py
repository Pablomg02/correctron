"""Command-line entry point: starts the local PDF tools web server."""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from pathlib import Path

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="correctron-pdf",
        description="Herramienta local para dividir y anonimizar PDFs escaneados.",
    )
    parser.add_argument(
        "--data",
        help="carpeta de los PDF (por defecto: $CORRECTRON_PDF_DATA o ./pdfs)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="dirección (por defecto: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8766, help="puerto (por defecto: 8766)")
    parser.add_argument(
        "--no-abrir",
        action="store_true",
        help="no abrir el navegador automáticamente",
    )
    return parser


def resolve_data_dir(arg: str | None) -> Path:
    """--data, then $CORRECTRON_PDF_DATA, then ./pdfs."""
    chosen = arg or os.environ.get("CORRECTRON_PDF_DATA") or "pdfs"
    return Path(chosen).expanduser().resolve()


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    data_dir = resolve_data_dir(args.data)

    from .pdfweb.app import create_app

    app = create_app(data_dir)
    url = f"http://{args.host}:{args.port}"
    print(f"Correctron PDF en {url} — datos: {data_dir}", flush=True)
    if not args.no_abrir:
        threading.Timer(1, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
