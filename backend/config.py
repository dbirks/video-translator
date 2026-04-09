from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/db.sqlite3"
    media_dir: str = "./data/media"
    openai_api_key: str = ""
    mistral_api_key: str = ""
    elevenlabs_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
