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
    max_emails: int = int(os.getenv("MAX_EMAILS", "50"))
    port: int = int(os.getenv("PORT", "5000"))
    body_char_limit: int = 3000  # how much of each email the model reads


settings = Settings()
