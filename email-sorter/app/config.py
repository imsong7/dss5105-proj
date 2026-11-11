import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    max_emails: int = int(os.getenv("MAX_EMAILS", "500"))
    port: int = int(os.getenv("PORT", "5001"))  # 5000 clashes with macOS AirPlay
    # Largest request body the server accepts (one pushed email is far smaller).
    max_request_bytes: int = int(os.getenv("MAX_REQUEST_BYTES", str(8 * 1024 * 1024)))
    inbound_max_emails: int = int(os.getenv("INBOUND_MAX_EMAILS", "500"))
    # Emails the Power Automate flow reads per refresh. 0 keeps the flow's own
    # default (TOP in flow_package.py). Changes need no flow re-import, only a restart.
    flow_refresh_top: int = int(os.getenv("FLOW_REFRESH_TOP", "0"))
    # Pushed mail and refresh bookkeeping are saved here so a restart does not lose
    # them. An empty value turns saving off (tests do that).
    pushed_mail_file: str = os.getenv("PUSHED_MAIL_FILE", str(ROOT / "private" / "pushed_mail.json"))
    refresh_state_file: str = os.getenv("REFRESH_STATE_FILE", str(ROOT / "private" / "refresh_state.json"))
    # After one complete refresh, later refreshes only ask the flow for newer mail.
    flow_incremental: bool = os.getenv("FLOW_INCREMENTAL", "1") != "0"
    # powerautomate = sign-in mode; each student then picks their flow or a Graph token.
    mail_provider: str = os.getenv("MAIL_PROVIDER", "powerautomate")
    body_char_limit: int = 3000  # how much of each email the model reads
    model_backend: str = os.getenv("MODEL_BACKEND", "hybrid_claude")  # hybrid_claude | hybrid | llama | encoder | ml | claude


settings = Settings()
