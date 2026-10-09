from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    data_dir: Path = ROOT / "data"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    frontend_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    scheduler_enabled: bool = True
    worker_enabled: bool = True
    max_model_turns: int = 18
    max_tool_calls: int = 45
    run_timeout_seconds: int = 300
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    @property
    def db_path(self) -> Path:
        return self.data_dir / "news.sqlite3"


@lru_cache
def get_settings() -> Settings:
    return Settings()
