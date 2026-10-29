"""Run from email-sorter: python tools/configure_multiuser.py"""
import getpass
import json
import os
import secrets
from pathlib import Path
from werkzeug.security import generate_password_hash

root = Path(__file__).resolve().parent.parent
path = root / "private" / "multiuser.json"
email = input("User email: ").strip().lower()
if "@" not in email:
    raise SystemExit("Invalid email.")
password = getpass.getpass("New app-only password (not your Outlook password): ")
confirm = getpass.getpass("Repeat password: ")
if len(password) < 8 or password != confirm:
    raise SystemExit("Use a matching password of at least 16 characters.")
url = getpass.getpass("Power Automate HTTPS trigger URL (blank = disable refresh): ").strip()
if url and not url.startswith("https://"):
    raise SystemExit("An HTTPS URL is required.")
accounts = json.loads(path.read_text()) if path.exists() else {}
if email in accounts:
    raise SystemExit("Account already exists. Edit/remove it intentionally before replacing credentials.")
token = secrets.token_urlsafe(32)
accounts[email] = {"password_hash": generate_password_hash(password), "webhook_token": token, "refresh_url": url}
path.parent.mkdir(parents=True, exist_ok=True)
os.chmod(path.parent, 0o700)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as handle:
    json.dump(accounts, handle, indent=2)
    handle.write("\n")
os.chmod(path, 0o600)
print("Created account:", email)
print("Power Automate X-Webhook-Token (keep private):", token)
print("Power Automate X-User-Email:", email)
