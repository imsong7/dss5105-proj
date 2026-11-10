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
    # powerautomate = sign-in mode; each student then picks their flow or a Graph token.
    mail_provider: str = os.getenv("MAIL_PROVIDER", "powerautomate")
    body_char_limit: int = 3000  # how much of each email the model reads
    model_backend: str = os.getenv("MODEL_BACKEND", "hybrid_claude")  # hybrid_claude | hybrid | llama | encoder | ml | claude


settings = Settings()
