"""Command-line entry point: starts the local web server."""

from __future__ import annotations

import argparse
import os
import threading
import webbrowser
from pathlib import Path

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="correctron",
        description="Herramienta local para corregir exámenes y trabajos.",
    )
    parser.add_argument(
        "--data",
        help="carpeta de datos (por defecto: $CORRECTRON_DATA o ./data)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="dirección (por defecto: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="puerto (por defecto: 8765)")
    parser.add_argument(
        "--no-abrir",
        action="store_true",
        help="no abrir el navegador automáticamente",
    )
    return parser


def resolve_data_dir(arg: str | None) -> Path:
    """D12: --data, then $CORRECTRON_DATA, then ./data."""
    chosen = arg or os.environ.get("CORRECTRON_DATA") or "data"
    return Path(chosen).expanduser().resolve()


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    data_dir = resolve_data_dir(args.data)

    from .web.app import create_app

    app = create_app(data_dir)
    url = f"http://{args.host}:{args.port}"
    print(f"Correctron en {url} — datos: {data_dir}", flush=True)
    if not args.no_abrir:
        threading.Timer(1, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
