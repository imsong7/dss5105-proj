"""Entry point for the email-sorter Flask app.

Usage::

    python run.py                           # uses MODEL_BACKEND env or default (hybrid)
    python run.py -version 2                # use the dashboard v2 as the home page
    python run.py --backend bert            # category + action from BERT heads
    python run.py --backend hybrid          # ML category + BERT action (default)
    python run.py --backend llama --port 8080
    python run.py --provider graphtoken     # read mail with an Outlook Graph token
    python run.py --provider powerautomate  # pushed mail (default)

Compare classifiers from a terminal while the app is running::

    python run.py --compare --owner you@u.nus.edu --days 30 --backends llama,ml
"""

from __future__ import annotations

import argparse
import os

from app.classifier_base import list_backends
from app.config import settings
from app.server import create_app, normalize_provider

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the email-sorter Flask app.")
    parser.add_argument(
        "--backend",
        choices=list_backends(),
        default=None,
        help="Model backend to use (overrides MODEL_BACKEND env var / config). "
             f"Choices: {', '.join(list_backends())}",
    )
    parser.add_argument(
        "-version",
        "--version",
        dest="app_version",
        type=int,
        choices=(1, 2),
        default=1,
        help="Dashboard version to show at the home page (default: 1).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to")
    parser.add_argument(
        "--provider",
        default=None,
        choices=("graphtoken", "powerautomate"),
        metavar="SOURCE",
        help="Mail source fixed for this run: graphtoken (Outlook Graph token) "
             "or powerautomate (pushed mail, default). Overrides MAIL_PROVIDER.",
    )

    compare = parser.add_argument_group("compare (terminal, app must be running)")
    compare.add_argument(
        "--compare",
        action="store_true",
        help="Classify one batch with several backends and print a table. "
             "Fetches from the running app, so it does not start Flask.",
    )
    compare.add_argument(
        "--backends",
        default="all",
        metavar="LIST",
        help="Comma-separated backends for --compare (default: all). "
             f"Choices: {', '.join(list_backends())}",
    )
    compare.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum emails to compare (default: MAX_EMAILS).",
    )
    compare.add_argument(
        "--days",
        type=int,
        default=7,
        help="Only compare mail from the last N days (default: 7, 0 = no window).",
    )
    compare.add_argument(
        "--owner",
        default=None,
        help="Mailbox owner for pushed mail (default: MAIL_OWNER env).",
    )
    compare.add_argument(
        "--token",
        default=None,
        help="Outlook Graph token for --provider graphtoken (default: GRAPH_TOKEN env).",
    )
    compare.add_argument(
        "--url",
        default=None,
        metavar="URL",
        help="Running app to fetch from (default: http://127.0.0.1:PORT).",
    )
    compare.add_argument(
        "--output",
        default=None,
        metavar="CSV",
        help="Also write the results to this CSV file.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    port = args.port if args.port is not None else settings.port
    try:
        provider = normalize_provider(args.provider or settings.mail_provider)
    except ValueError as error:
        parser.error(str(error))

    if args.compare:
        from app.compare_cli import parse_backends, run_compare

        try:
            backends = parse_backends(args.backends)
        except ValueError as error:
            parser.error(str(error))
        raise SystemExit(
            run_compare(
                url=args.url or f"http://127.0.0.1:{port}",
                provider=provider,
                owner=args.owner or os.getenv("MAIL_OWNER", ""),
                token=args.token or os.getenv("GRAPH_TOKEN", ""),
                backends=backends,
                limit=args.limit if args.limit is not None else settings.max_emails,
                days=args.days,
                output=args.output,
            )
        )

    app = create_app(
        backend=args.backend,
        version=args.app_version,
        provider=provider,
    )
    # Bound to localhost only: your emails never leave this machine.
    app.run(host=args.host, port=port, debug=args.debug)
