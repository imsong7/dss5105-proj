"""Start and stop the ngrok tunnel used by the Power Automate mail source.

The tunnel is only needed when Power Automate has to reach the app from the
cloud. It is skipped for ``--provider graphtoken``, where the app makes
outbound Graph requests instead.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import requests

DEFAULT_DOMAIN = "chive-suitably-slingshot.ngrok-free.dev"
NGROK_API = "http://127.0.0.1:4040/api/tunnels"


def public_url_for(port: int) -> str | None:
    """Return the public URL of an existing ngrok tunnel to ``port``, if any."""
    try:
        data = requests.get(NGROK_API, timeout=1).json()
    except Exception:
        return None
    for tunnel in data.get("tunnels", []):
        addr = (tunnel.get("config") or {}).get("addr", "")
        if str(addr).rstrip("/").endswith(f":{port}"):
            return tunnel.get("public_url")
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

    executable = shutil.which("ngrok")
    if not executable:
        print("[ngrok] ngrok is not installed; Power Automate cannot reach this app.")
        print("[ngrok] install it with: brew install ngrok")
        return None, None

    command = [executable, "http", f"--domain={domain}", str(port)]
    print(f"[ngrok] starting: {' '.join(command)}")
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(20):
        time.sleep(0.5)
        if process.poll() is not None:
            print("[ngrok] exited before the tunnel was ready. Is the domain reserved?")
            return None, None
        url = public_url_for(port)
        if url:
            print(f"[ngrok] public URL: {url}")
            print(f"[ngrok] webhook:    {url}/api/inbound/outlook")
            return process, url

    print("[ngrok] tunnel did not become ready in time.")
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
