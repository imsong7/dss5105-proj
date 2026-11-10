"""Entry point for the email-sorter Flask app.

Usage::

    python run.py                           # start the app
    python run.py --backend encoder         # category + action from text-encoder heads
    python run.py --backend hybrid_claude   # ML category + Claude action (default)
    python run.py --backend hybrid          # ML category + text-encoder action
    python run.py --backend claude          # Claude backend
    python run.py --backend llama --port 8080
    python run.py --provider powerautomate  # sign-in; each student picks flow or token (default)
    python run.py --provider graphtoken     # no sign-in, Outlook Graph token only (single user)

Compare classifiers from a terminal while the app is running::

    python run.py --compare --owner you@u.nus.edu --days 30 --backends llama,ml
"""

from __future__ import annotations

import argparse
import os
import signal

from app.backends import list_backends
from app.config import settings
from app.ngrok import start as start_tunnel
from app.ngrok import stop as stop_tunnel
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
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to")
    parser.add_argument(
        "--provider",
        default=None,
        choices=("graphtoken", "powerautomate"),
        metavar="SOURCE",
        help="Mode for this run: powerautomate (default; sign-in, each student "
             "picks their Power Automate flow or a Graph token) or graphtoken "
             "(no sign-in, token only). Overrides MAIL_PROVIDER.",
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
    parser.add_argument(
        "--no-tunnel",
        action="store_true",
        help="Do not start ngrok (it starts by default).",
    )
    parser.add_argument(
        "--ngrok-domain",
        default=None,
        metavar="DOMAIN",
        help="ngrok static domain (default: NGROK_DOMAIN env or "
             "chive-suitably-slingshot.ngrok-free.dev).",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    if args.debug and not args.no_tunnel:
        # Flask's debugger runs any Python typed into an error page. Through
        # ngrok that would let anyone on the internet run code on this Mac.
        parser.error("--debug only works with --no-tunnel (the debugger must never be public).")

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
        provider=provider,
    )

    tunnel_process = None
    public_url = None
    if not args.no_tunnel:
        # With Flask's reloader the script runs twice; only the parent should
        # own the tunnel so Ctrl+C stops it once.
        if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            tunnel_process, public_url = start_tunnel(port, args.ngrok_domain)
            if provider != "powerautomate":
                print(
                    "[ngrok] WARNING: this mode has no login, so anyone with the "
                    "public URL can open the app. Use --no-tunnel to keep it local."
                )

    def stop_services_on_signal(_signum=None, _frame=None):
        stop_tunnel(tunnel_process)
        raise SystemExit(0)

    if tunnel_process is not None:
        # The VS Code stop button sends SIGTERM, which skips the finally block.
        signal.signal(signal.SIGTERM, stop_services_on_signal)

    # Make the address to share the last thing people read before Flask's own
    # "Running on http://127.0.0.1" lines, which only work on this Mac.
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        line = "=" * 64
        print(f"\n{line}")
        if public_url:
            print(f"  Open the app:   {public_url}")
            print("  (share this link; it works from phones and other computers)")
        elif args.no_tunnel:
            print(f"  ngrok is off (--no-tunnel). This Mac only: http://127.0.0.1:{port}")
        else:
            print("  ngrok did not start (see [ngrok] lines above).")
            print(f"  This Mac only: http://127.0.0.1:{port}")
        print(f"{line}\n")

    # Bound to localhost only: your emails never leave this machine.
    try:
        app.run(host=args.host, port=port, debug=args.debug)
    finally:
        stop_tunnel(tunnel_process)
