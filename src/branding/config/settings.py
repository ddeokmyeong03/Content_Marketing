from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str = ""

    # Meta Graph API
    meta_access_token: str = ""
    meta_ig_user_id: str = ""
    meta_threads_user_id: str = ""

    # App
    data_dir: Path = Path("./data")
    brand_config_path: Path = Path("./brand/config.yaml")
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "content.db"


def get_settings() -> Settings:
    return Settings()
