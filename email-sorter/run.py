"""Entry point for the email-sorter Flask app.

Usage::

    python run.py                           # uses MODEL_BACKEND env or default (llama)
    python run.py --backend bert            # force BERT backend
    python run.py --backend llama --port 8080
"""

from __future__ import annotations

import argparse

from app.config import settings
from app.server import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the email-sorter Flask app.")
    parser.add_argument(
        "--backend",
        choices=["llama", "bert"],
        default=None,
        help="Model backend to use (overrides MODEL_BACKEND env var / config). "
             "Choices: llama, bert",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    app = create_app(backend=args.backend)
    port = args.port if args.port is not None else settings.port
    # Bound to localhost only: your emails never leave this machine.
    app.run(host=args.host, port=port, debug=args.debug)
