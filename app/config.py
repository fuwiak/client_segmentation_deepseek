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

    # --- Интеграции-источники (feature-flags; placeholder-коннекторы) ---
    onec_enabled: bool = False
    onec_odata_url: str = ""
    messenger_enabled: bool = False

    # --- Green API (WhatsApp) ---
    green_api_enabled: bool = False
    green_api_id_instance: str = ""
    green_api_token: str = ""
    green_api_url: str = "https://api.green-api.com"
    green_api_media_url: str = "https://media.green-api.com"

    # --- Telegram Bot API ---
    telegram_enabled: bool = False
    telegram_bot_token: str = ""

    # --- Хранилище: "memory" сейчас, "postgres" на этапе прода ---
    repository_backend: str = "memory"
    database_url: str = ""

    # --- Кэш загруженных Excel (Redis на Railway, иначе in-memory) ---
    redis_url: str = ""
    cache_ttl_seconds: int = 86400

    # --- Модули CRM (placeholder до реализации) ---
    leads_enabled: bool = False
    campaigns_enabled: bool = False

    app_title: str = "Client CRM"
    max_upload_mb: int = 20
    ai_batch_size: int = 10
    ai_concurrency: int = 4
    ai_max_retries: int = 2
    ai_temperature: float = 0.2
    ai_timeout_seconds: int = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()
