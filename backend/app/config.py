from pathlib import Path
import shutil

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+psycopg://paper_admin:paper_admin_dev@127.0.0.1:55432/paper_analyzer"
    )
    storage_dir: Path = Path(__file__).resolve().parents[1] / "storage"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "deepseek-chat"
    llm_timeout_s: float = 25.0
    xelatex_bin: str = Field(default_factory=lambda: shutil.which("xelatex") or "/opt/homebrew/bin/xelatex")
    soffice_bin: str = Field(default_factory=lambda: shutil.which("soffice") or "/opt/homebrew/bin/soffice")
    revisions_dir: Path = Path(__file__).resolve().parents[1] / "storage" / "revisions"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


settings = Settings()
