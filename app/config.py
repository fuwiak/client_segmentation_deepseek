from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_model: str = "deepseek/deepseek-v4-pro"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    moysklad_api_token: str = ""
    moysklad_api_url: str = "https://api.moysklad.ru/api/remap/1.2"
    moysklad_enabled: bool = False

    app_title: str = "Сегментация клиентов"
    max_upload_mb: int = 20
    ai_batch_size: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
