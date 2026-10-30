"""Start and stop the ngrok tunnel used by the Power Automate mail source.

The tunnel is only needed when Power Automate has to reach the app from the
cloud. It is skipped for ``--provider graphtoken``, where the app makes
outbound Graph requests instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests

DEFAULT_DOMAIN = "chive-suitably-slingshot.ngrok-free.dev"
NGROK_API = "http://127.0.0.1:4040/api/tunnels"


def tunnels() -> list[tuple[str, str]]:
    """Return ``(public_url, local_addr)`` for the running ngrok agent."""
    try:
        data = requests.get(NGROK_API, timeout=1).json()
    except Exception:
        return []
    return [
        (
            str(tunnel.get("public_url") or ""),
            str((tunnel.get("config") or {}).get("addr") or ""),
        )
        for tunnel in data.get("tunnels", [])
    ]


def public_url_for(port: int) -> str | None:
    """Return the public URL of an existing ngrok tunnel to ``port``, if any."""
    for url, addr in tunnels():
        if addr.rstrip("/").endswith(f":{port}"):
            return url
    return None


def start(port: int, domain: str | None = None) -> tuple[subprocess.Popen | None, str | None]:
    """Start ngrok for ``port`` and wait for its public URL.

    Returns ``(process, url)``. ``process`` is ``None`` when an existing tunnel
    was reused or when ngrok could not be started.
    """
    domain = (domain or os.getenv("NGROK_DOMAIN") or DEFAULT_DOMAIN).strip()

    existing = public_url_for(port)
    if existing:
        print(f"[ngrok] reusing existing tunnel: {existing} -> localhost:{port}")
        return None, existing

    others = tunnels()
    if others:
        print("[ngrok] the static domain is already used by another tunnel:")
        for url, addr in others:
            print(f"[ngrok]   {url} -> {addr}")
        print("[ngrok] stop that ngrok process first, or pass a different --ngrok-domain.")
        return None, None

    executable = shutil.which("ngrok")
    if not executable:
        print("[ngrok] ngrok is not installed; Power Automate cannot reach this app.")
        print("[ngrok] install it with: brew install ngrok")
        return None, None

    command = [executable, "http", f"--domain={domain}", str(port)]
    print(f"[ngrok] starting: {' '.join(command)}")
    log = tempfile.NamedTemporaryFile(prefix="ngrok-", suffix=".log", delete=False)
    log_path = Path(log.name)
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    log.close()

    def print_tail() -> None:
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        for line in lines[-5:]:
            print(f"[ngrok] {line}")

    for _ in range(20):
        time.sleep(0.5)
        if process.poll() is not None:
            print("[ngrok] exited before the tunnel was ready:")
            print_tail()
            return None, None
        url = public_url_for(port)
        if url:
            print(f"[ngrok] public URL: {url}")
            print(f"[ngrok] webhook:    {url}/api/inbound/outlook")
            return process, url

    print("[ngrok] tunnel did not become ready in time:")
    print_tail()
    stop(process)
    return None, None


def stop(process: subprocess.Popen | None) -> None:
    """Stop a tunnel only when this process started it."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    print("[ngrok] tunnel stopped")
