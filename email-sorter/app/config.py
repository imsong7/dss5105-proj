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
    max_emails: int = int(os.getenv("MAX_EMAILS", "100"))
    port: int = int(os.getenv("PORT", "5000"))
    inbound_max_emails: int = int(os.getenv("INBOUND_MAX_EMAILS", "500"))
    inbound_webhook_token: str = os.getenv("POWER_AUTOMATE_WEBHOOK_TOKEN", "")
    powerautomate_refresh_url: str = os.getenv("POWER_AUTOMATE_REFRESH_URL", "")
    mail_provider: str = os.getenv("MAIL_PROVIDER", "graphtoken")
    body_char_limit: int = 3000  # how much of each email the model reads
    model_backend: str = os.getenv("MODEL_BACKEND", "hybrid_claude")  # hybrid_claude | hybrid | llama | bert | ml | claude


settings = Settings()
