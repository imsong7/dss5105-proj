"""Entry point for the email-sorter Flask app.

Usage::

    python run.py                           # start the app on this computer only
    python run.py --tunnel                  # also share it publicly through ngrok (live app)
    python run.py --backend hybrid_claude   # ML category + Claude action (default)
    python run.py --provider powerautomate  # sign-in; each student picks flow or token (default)
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
from pathlib import Path

from app.classifiers.backends import list_backends
from app.config import settings
from app.ngrok import start as start_tunnel
from app.ngrok import stop as stop_tunnel
from app.server import create_app, normalize_provider


FRONTEND = Path(__file__).resolve().parent / "frontend"
BUILD_INDEX = Path(__file__).resolve().parent / "static" / "app" / "index.html"


def frontend_is_stale() -> bool:
    """True when frontend/ has changed since static/app/ was last built."""
    if not BUILD_INDEX.is_file():
        return True
    built = BUILD_INDEX.stat().st_mtime
    sources = [FRONTEND / "index.html", FRONTEND / "package.json", FRONTEND / "vite.config.ts"]
    sources += [path for path in (FRONTEND / "src").rglob("*") if path.is_file()]
    sources += [path for path in (FRONTEND / "public").rglob("*") if path.is_file()]
    return any(path.exists() and path.stat().st_mtime > built for path in sources)


def build_frontend_if_needed() -> None:
    """Rebuild the React app when its code is newer than the build, so
    `python run.py` always serves the current screens."""
    if not frontend_is_stale():
        return
    npm = shutil.which("npm")
    if not npm or not (FRONTEND / "node_modules").is_dir():
        print("[frontend] The app screens are out of date. Run: cd frontend && npm install && npm run build")
        return
    print("[frontend] Code changed since the last build; building the app (about 10 seconds)...")
    result = subprocess.run([npm, "run", "build"], cwd=FRONTEND, capture_output=True, text=True)
    if result.returncode != 0:
        print("[frontend] Build failed; serving the previous build. Last lines:")
        print("\n".join((result.stdout + result.stderr).strip().splitlines()[-15:]))
    else:
        print("[frontend] Build ready.")


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

    parser.add_argument(
        "--tunnel",
        action="store_true",
        help="Share the app publicly through ngrok. Off by default, so teammates "
             "can run it locally; the live machine sets USE_NGROK=1 in .env instead.",
    )
    parser.add_argument(
        "--no-tunnel",
        action="store_true",
        help="Never start ngrok, even when USE_NGROK=1 (the default is already off).",
    )
    parser.add_argument(
        "--ngrok-domain",
        default=None,
        metavar="DOMAIN",
        help="ngrok static domain (default: NGROK_DOMAIN env or "
             "agile-problem-luxury.ngrok-free.dev).",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Do not rebuild the React app even if frontend/ changed (default: rebuild when needed).",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    use_tunnel = not args.no_tunnel and (
        args.tunnel or os.getenv("USE_NGROK", "").strip().lower() in {"1", "true", "yes"}
    )

    if args.debug and use_tunnel:
        # Flask's debugger runs any Python typed into an error page. Through
        # ngrok that would let anyone on the internet run code on this Mac.
        parser.error("--debug cannot be used with ngrok (the debugger must never be public).")

    port = args.port if args.port is not None else settings.port
    try:
        provider = normalize_provider(args.provider or settings.mail_provider)
    except ValueError as error:
        parser.error(str(error))

    # With Flask's reloader the script runs twice; build only in the parent.
    if not args.no_build and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        build_frontend_if_needed()

    app = create_app(
        backend=args.backend,
        provider=provider,
    )

    tunnel_process = None
    public_url = None
    if use_tunnel:
        # With Flask's reloader the script runs twice; only the parent should
        # own the tunnel so Ctrl+C stops it once.
        if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
            tunnel_process, public_url = start_tunnel(port, args.ngrok_domain)
            if provider != "powerautomate":
                print(
                    "[ngrok] WARNING: this mode has no login, so anyone with the "
                    "public URL can open the app. Run without --tunnel to keep it local."
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
        elif not use_tunnel:
            print(f"  Open the app:   http://127.0.0.1:{port}  (this computer only)")
            print("  (to share it publicly through ngrok, run with --tunnel)")
        else:
            print("  ngrok did not start (see [ngrok] lines above).")
            print(f"  This Mac only: http://127.0.0.1:{port}")
        print(f"{line}\n")

    # Bound to localhost only: your emails never leave this machine.
    try:
        app.run(host=args.host, port=port, debug=args.debug)
    finally:
        stop_tunnel(tunnel_process)
