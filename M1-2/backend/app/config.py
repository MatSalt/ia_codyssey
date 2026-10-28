"""Read server-only configuration without initializing external clients."""
from dataclasses import dataclass, field
import os
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    allowed_origins: tuple[str, ...]
    firebase_project_id: str | None = None
    google_application_credentials: str | None = field(default=None, repr=False)
    openai_api_key: str | None = field(default=None, repr=False)
    openai_base_url: str | None = None
    openai_model: str | None = None
    openai_max_output_tokens: int = 2048
    openai_timeout_seconds: float = 45
    openai_max_retries: int = 0


def get_settings() -> Settings:
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    origins = tuple(origin.strip() for origin in os.getenv('ALLOWED_ORIGINS', '').split(',') if origin.strip())
    return Settings(
        allowed_origins=origins,
        firebase_project_id=os.getenv('FIREBASE_PROJECT_ID') or None,
        google_application_credentials=os.getenv('GOOGLE_APPLICATION_CREDENTIALS') or None,
        openai_api_key=os.getenv('OPENAI_API_KEY') or None,
        openai_base_url=os.getenv('OPENAI_BASE_URL') or None,
        openai_model=os.getenv('OPENAI_MODEL') or None,
    )
