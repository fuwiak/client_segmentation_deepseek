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
    moysklad_sync_limit: int = 0  # 0 = все контрагенты
    moysklad_sync_orders_limit: int = 0  # 0 = все заказы
    clients_page_size: int = 25
    moysklad_auto_sync: bool = True

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
    telegram_bot_username: str = "my_veresk_bot"
    telegram_api_timeout_seconds: int = 10
    telegram_sync_on_attach: bool = False

    # --- Хранилище: "memory" сейчас, "postgres" на этапе прода ---
    repository_backend: str = "memory"
    database_url: str = ""
    db_persist_enabled: bool = False

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
    ai_auto_segment: bool = True
    ai_lazy_batch_size: int = 5
    # Полная AI-прокачка всей базы на старте — дорого; по умолчанию только активная страница.
    ai_lazy_full_on_startup: bool = False

    enrichment_chat_limit: int = 50
    enrichment_batch_size: int = 5
    enrichment_concurrency: int = 3
    messenger_live_fetch: bool = False
    messenger_cache_limit: int = 5000

    moysklad_positions_concurrency: int = 2
    moysklad_api_retry_max: int = 4
    moysklad_request_delay_ms: int = 250

    green_api_concurrency: int = 1
    green_api_retry_max: int = 4

    telegram_export_path: str = "data/telegram_export.json"
    telegram_export_auto_import: bool = True
    telegram_export_max_mb: int = 50

    # --- Railway / cold start ---
    warm_cache_on_startup: bool = True
    keep_alive_enabled: bool = True
    keep_alive_interval_seconds: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
