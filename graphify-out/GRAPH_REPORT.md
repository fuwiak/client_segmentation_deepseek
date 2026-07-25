# Graph Report - .  (2026-07-25)

## Corpus Check
- 140 files · ~67,614 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1614 nodes · 4365 edges · 75 communities (68 shown, 7 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 149 edges (avg confidence: 0.63)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- HTMX Vendor Minified
- AI Narrative Style
- AI Tag Explanations
- Excel Parse Dedup
- MoySklad Mapper
- MoySklad API Client
- CRM UI Shell Templates
- Segmentation UI Flow
- Client Card Messengers
- DataHub Core
- Data Source Connectors
- Telegram Export Parse
- App Settings Config
- Sales Channel Rules
- Frontend App Shell JS
- Domain Models Repo
- Postgres Persist Layer
- Computed Sales Fields
- AI Agent Interface
- DataHub Unit Tests
- Dashboard Service
- Cache Service API
- Gender Heuristics
- Performance UI Tests
- DB Column Mapping
- Domain Enums Models
- App Lifespan Keepalive
- Hub AI Merge Ops
- CRM Page Routes
- Export Hydrate Routes
- Background Job Queue
- Clients Group Filters
- Gender AI Enrichment
- Export Format Helpers
- MoySklad Tag Push
- Clients Table WS JS
- Main Health WebSocket
- TG Nick Enrichment
- GreenAPI WhatsApp
- Campaigns Placeholder
- AI Cell Coverage
- VIP Order Computed
- InMemory Cache Fallback
- MoySklad Sync Pipeline
- Excel Connector
- DataHub Filters
- Cache Backend Redis
- Gender Map Apply
- Telegram Bot Client
- HTMX Preload Ext
- Telegram Export Import
- Clients Page Cache
- HTTP Retry Helper
- Messenger Connector
- Auto Comm Rules
- Integration Status Cache
- Leads Placeholder
- Priority Card AI
- Compact Orders Display
- Messenger Message Store
- Clients Pagination UI
- Excel Export Columns
- Workbook Upload Cache
- Logging Config
- WebSocket Connections
- Money RUB Format
- Nav Sidebar Partials
- DB Package Init
- asyncpg Dependency
- pandas Dependency
- Redis Dependency

## God Nodes (most connected - your core abstractions)
1. `Settings` - 89 edges
2. `DataHub` - 80 edges
3. `SegmentationService` - 58 edges
4. `CacheService` - 53 edges
5. `ParsedWorkbook` - 51 edges
6. `pipeline_log()` - 49 edges
7. `MessengerEnrichmentService` - 49 edges
8. `enrich_row_computed()` - 39 edges
9. `BackgroundJobService` - 31 edges
10. `DbPersistService` - 30 edges

## Surprising Connections (you probably didn't know these)
- `_NoopCache` --uses--> `Settings`  [INFERRED]
  tests/test_background_jobs.py → app/config.py
- `test_compute_home_kpis_skips_order_scan()` --calls--> `DashboardService`  [EXTRACTED]
  tests/test_performance.py → app/crm/dashboard.py
- `test_row_ws_patch_running_state()` --calls--> `row_ws_patch()`  [EXTRACTED]
  tests/test_background_jobs.py → app/services/background_jobs.py
- `_NoopCache` --uses--> `DataHub`  [INFERRED]
  tests/test_background_jobs.py → app/services/data_hub.py
- `test_hub_upsert_results()` --calls--> `DataHub`  [EXTRACTED]
  tests/test_background_jobs.py → app/services/data_hub.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Client CRM UI Shell** — app_templates_base_client_crm, app_templates_boosted_boosted_layout, app_templates_base_htmx_boost, requirements_jinja2 [INFERRED 0.85]
- **AI Segmentation Pipeline UI** — app_templates_clients_ai_resegment, app_templates_partials_ai_progress_ai_segmentation, app_templates_partials_ai_cell_ai_cell_macro, app_templates_partials_ai_tags_ai_tag_chips, app_templates_partials_ai_cell_deepseek [INFERRED 0.85]
- **MoySklad Integration Flow** — app_templates_moysklad_settings_moysklad_admin, app_templates_clients_moysklad_sync, app_templates_moysklad_settings_push_tags, app_templates_segment_data_sources, app_templates_moysklad_settings_remap_api [INFERRED 0.85]
- **Excel Import Export Stack** — app_templates_index_excel_upload, app_templates_segment_data_sources, app_templates_base_upload_modal, requirements_openpyxl, requirements_pandas [INFERRED 0.75]
- **Messenger Campaign Channels** — app_templates_campaigns_whatsapp_channel, app_templates_campaigns_telegram_channel, app_templates_settings_green_api, app_templates_clients_messenger_enrich, app_templates_communications_comm_rules [INFERRED 0.75]
- **ClientOrdersUI** — app_templates_partials_client_orders_clientorders, app_templates_partials_client_orders_list_clientorderslist, app_templates_partials_client_orders_modal_clientordersmodal, app_templates_partials_client_card_body_ordersmodalendpoint [EXTRACTED 1.00]
- **ClientsListPage** — app_templates_partials_clients_page_frame_clientspageframe, app_templates_partials_clients_pagination_clientspagination, app_templates_partials_clients_table_clientstable, app_templates_partials_group_filter_cloud_groupfiltercloud [INFERRED 0.85]
- **MessengerIntegrations** — app_templates_partials_messenger_sidebar_messengersidebar, app_templates_partials_messenger_status_messengerstatus, app_templates_partials_messenger_sidebar_whatsapp, app_templates_partials_messenger_sidebar_telegram, app_templates_partials_client_card_body_greenapi [INFERRED 0.85]
- **ClientCardDrawerStack** — app_templates_partials_client_card_drawer_clientcarddrawer, app_templates_partials_client_card_body_clientcardbody, app_templates_partials_clients_table_clientdrawerendpoint [EXTRACTED 1.00]
- **AISegmentationUIFlow** — app_templates_partials_preview_preview_panel, app_templates_partials_preview_ai_segmentation_start, app_templates_partials_segment_modal_segment_modal, app_templates_partials_segment_progress_segment_progress, app_templates_partials_results_segmentation_results [EXTRACTED 1.00]
- **DockerDeployStack** — deploy_docker_compose_web_service, deploy_docker_compose_redis_service, deploy_docker_compose_postgres_service, deploy_docker_compose_caddy_service [EXTRACTED 1.00]
- **DevelopmentPhases** — docs_plan_phase1_unified_client_base, docs_plan_phase2_nl_analytics, docs_plan_phase3_communications [EXTRACTED 1.00]
- **CoreDomainEntities** — docs_spec_customer, docs_spec_recipient, docs_spec_order, docs_spec_preference_profile, docs_spec_important_date [EXTRACTED 1.00]
- **AgentLayer** — docs_spec_segmentation_agent, docs_spec_enrichment_agent, docs_spec_campaign_agent, docs_spec_hermes_agent [INFERRED 0.85]

## Communities (75 total, 7 thin omitted)

### Community 0 - "HTMX Vendor Minified"
Cohesion: 0.08
Nodes (101): A(), ae(), an(), at(), B(), be(), bn(), bt() (+93 more)

### Community 1 - "AI Narrative Style"
Cohesion: 0.05
Nodes (55): Стиль и few-shot для AI-текстов: саммари клиента, повод/intent, рекомендация., apply_ai_client_summary(), apply_ai_field(), apply_name_parts(), build_client_history_summary(), collect_client_comments(), empty_fillable_columns(), extract_email_from_row() (+47 more)

### Community 2 - "AI Tag Explanations"
Cohesion: 0.08
Nodes (49): explain_single_tag(), explain_tags_for_row(), _normalize_display_tag(), Any, Пояснения для AI-тегов клиента (tooltip при наведении)., Вернуть пояснение для каждого тега в поле «Теги»., _avg_check(), _client_comments() (+41 more)

### Community 3 - "Excel Parse Dedup"
Cohesion: 0.08
Nodes (30): normalize_phone(), Ключ для склейки записей из разных источников., Приводит телефон к формату +7XXXXXXXXXX — стабильный ключ для склейки.      Осно, _client_lookup_keys(), _detect_header_row(), enrich_with_orders(), _index_orders_for_clients(), _normalize() (+22 more)

### Community 4 - "MoySklad Mapper"
Cohesion: 0.09
Nodes (51): _accounts_list(), _address_full(), aggregate_client_positions(), apply_order_stats(), apply_positions_to_orders(), _archived_label(), _bank_fields(), _bonus_points() (+43 more)

### Community 5 - "MoySklad API Client"
Cohesion: 0.09
Nodes (7): MoySkladClient, MoySkladClientBase, MoySkladStub, ABC, Any, Абстракция для интеграции с API Мой Склад., Заглушка до подключения реального токена Мой Склад.

### Community 6 - "CRM UI Shell Templates"
Cohesion: 0.06
Nodes (44): AI API Key Status Footer, Client CRM Shell, Client Drawer, HTMX Boost Navigation, AI Tag Rules Drawer, Excel Upload Modal, Boosted Partial Layout, AI Targeting Assistant WIP (+36 more)

### Community 7 - "Segmentation UI Flow"
Cohesion: 0.06
Nodes (44): MoySkladStatusBlock, MoySkladSync, RedisCache, AISegmentationStart, PreviewPanel, MoySkladPushTags, SegmentationResults, SegmentModal (+36 more)

### Community 8 - "Client Card Messengers"
Cohesion: 0.06
Nodes (42): AIRecommendation, AISummary, ClientCardBody, ClientContacts, GreenAPI, MessengerContext, OrdersModalEndpoint, ClientCardDrawer (+34 more)

### Community 9 - "DataHub Core"
Cohesion: 0.10
Nodes (13): DataHub, Any, Перепривязать заказы к контрагентам (обновление каналов и статистики)., Sales snapshot without expensive AI display/recommendation overlays., Добавить или обновить AI-результаты по ключу строки (lazy evaluation)., O(1) поиск строки клиента без полного active_rows()., Подтянуть полные строки заказов из orders_parsed (позиции, канал, статус)., Быстрый путь для HTMX-раскрытия заказов в карточке клиента. (+5 more)

### Community 10 - "Data Source Connectors"
Cohesion: 0.09
Nodes (17): DataSourceConnector, ABC, Any, Абстракция источника данных.  Любой источник (Excel, Мой Склад, 1С, мессенджер), Готов ли коннектор отдавать данные (настроен ли доступ)., Переписки/звонки. По умолчанию источник их не отдаёт., Коннекторы источников данных.  Активен: ExcelConnector. Остальные — placeholder, Коннектор мессенджеров — Green API (WhatsApp) + Telegram Bot API. (+9 more)

### Community 11 - "Telegram Export Parse"
Cohesion: 0.14
Nodes (33): _normalize_name(), _normalize_phone(), _normalize_tg(), build_export_index(), build_phone_username_lookup(), _extract_message_text(), _message_direction(), messages_for_row() (+25 more)

### Community 12 - "App Settings Config"
Cohesion: 0.12
Nodes (18): get_settings(), Settings, file_hash(), get_cache(), Кэш загруженных Excel-файлов.  Хранит результат разбора workbook по SHA-256 соде, get_db_persist(), Фоновая персистентность данных из Redis в PostgreSQL., get_green_api_client() (+10 more)

### Community 13 - "Sales Channel Rules"
Cohesion: 0.09
Nodes (34): channel_type_from_channel(), client_status_from_orders(), enrich_gender_by_unique_naimenovanie(), ensure_ai_client_summary(), is_direct_sales_channel(), is_marketplace_channel(), is_permanent(), _normalize_channel() (+26 more)

### Community 14 - "Frontend App Shell JS"
Cohesion: 0.11
Nodes (28): activateLazyWidgets(), closeClientDrawer(), closeDiagPanel(), closeModal(), closeTagRulesDrawer(), currentNavPath(), disableBoostOnDownloads(), ensureTagRulesPanel() (+20 more)

### Community 15 - "Domain Models Repo"
Cohesion: 0.10
Nodes (12): Customer, Interaction, Центральная сущность. `external_ids` хранит id клиента в каждом источнике,     ч, CustomerRepository, ABC, Абстракция хранилища клиентской базы.  UI и агенты работают только через этот ин, Добавляет/обновляет клиентов, склеивая по dedup_key. Возвращает число., get_repository() (+4 more)

### Community 16 - "Postgres Persist Layer"
Cohesion: 0.16
Nodes (9): DbPersistService, Any, Сохраняет снимки DataHub в Postgres; подгружает при промахе Redis., Тесты сериализации значений для Postgres., test_bind_column_jsonb_as_string(), test_bind_column_list_for_positions(), test_coerce_json_list_from_string(), test_coerce_json_object_from_dict() (+1 more)

### Community 17 - "Computed Sales Fields"
Cohesion: 0.11
Nodes (29): ensure_sales_classification(), _looks_like_sales_type_label(), _order_channels(), _order_channels_for_type(), Вычисляемые поля клиента и заказов (не AI)., Канал продаж по каждому заказу (пустая строка, если не задан)., Тип по набору каналов: прямые / маркетплейс / смесь обоих., Уникальные каналы продаж клиента (из заказов и поля строки). (+21 more)

### Community 18 - "AI Agent Interface"
Cohesion: 0.17
Nodes (15): Agent, AgentContext, AgentResult, ABC, Базовый интерфейс AI-агента.  Все агенты (сегментация, обогащение, кампании) реа, Вход агента: доменные данные + произвольные параметры., Выход агента: результат + метаданные (уверенность, обоснование)., CampaignAgent (+7 more)

### Community 19 - "DataHub Unit Tests"
Cohesion: 0.13
Nodes (27): ParsedWorkbook, Вкладки Маркетплейс/Прямые — по правилам каналов, даже без поля Тип продаж., _sample_hub(), test_active_rows_merges_parsed_with_enrichment_overlay(), test_ai_upsert_invalidates_ai_sensitive_filters_only(), test_ai_upsert_patches_stable_pagination_cache_in_place(), test_cached_ai_overlay_cannot_replace_current_sales_classification(), test_dashboard_rows_use_source_snapshot_without_ai_merge() (+19 more)

### Community 20 - "Dashboard Service"
Cohesion: 0.15
Nodes (15): _DashboardCache, DashboardData, DashboardService, _growth(), MetricBlock, _month_key(), _parse_date(), _period_bounds() (+7 more)

### Community 21 - "Cache Service API"
Cohesion: 0.18
Nodes (7): CacheService, Any, Фасад кэша: пробует Redis, иначе in-memory. Хранит разобранные workbook., Сохранить сгенерированные записи сегментации., Сохранить результаты по ключу workbook и как latest., Вернуть результаты для workbook или последние сохранённые., _schedule()

### Community 22 - "Gender Heuristics"
Cohesion: 0.13
Nodes (25): build_heuristic_gender_map(), confident_gender_from_row(), gender_analysis_payload(), gender_from_patronymic(), gender_from_role_label(), gender_from_surname(), _gender_from_token(), guess_gender() (+17 more)

### Community 23 - "Performance UI Tests"
Cohesion: 0.08
Nodes (8): test_apply_cached_results_does_not_bulk_enrich(), test_client_card_drawer_resolves_encoded_phone_name(), test_client_card_drawer_shows_ai_summary_and_recommendation(), test_client_orders_modal_returns_all_orders_from_cache(), test_client_orders_uses_cache_only_hydrate(), test_clients_page_partial_is_short_cached_for_preload(), test_compute_home_kpis_skips_order_scan(), test_home_recent_clients_open_uses_drawer()

### Community 24 - "DB Column Mapping"
Cohesion: 0.20
Nodes (22): _as_text(), customer_row_to_db(), order_row_to_db(), _parse_bool_label(), _parse_date(), _parse_datetime(), _parse_decimal(), _parse_int() (+14 more)

### Community 25 - "Domain Enums Models"
Cohesion: 0.21
Nodes (22): Доменные модели — единая структура клиентской базы., CampaignStatus, Gender, ImportantDate, ImportantDateSource, InteractionChannel, LeadStatus, OrderItem (+14 more)

### Community 26 - "App Lifespan Keepalive"
Cohesion: 0.13
Nodes (23): pipeline_log(), _app_lifespan(), _attach_messenger_for_ai(), _backfill_postgres_from_redis(), _keep_alive_loop(), Response, Быстрая подгрузка hub из Redis/Postgres до первого запроса пользователя., Исходящий ping Redis/Postgres — Railway Serverless не усыпляет сервис. (+15 more)

### Community 27 - "Hub AI Merge Ops"
Cohesion: 0.18
Nodes (7): Any, Строки без завершённой AI-обработки. Если rows задан — только среди них., Эвристика + LLM по уникальным Наименование без пола (все клиенты, не только pend, ТГ ник по телефону из TG export и кэша Bot API., Запустить lazy AI. priority=True — прервать фон и сначала обработать rows., Компактное представление строки для обновления ячеек в браузере., row_ws_patch()

### Community 28 - "CRM Page Routes"
Cohesion: 0.24
Nodes (22): campaign_create(), campaigns_page(), client_card(), client_orders(), clients_ai_start(), communications_page(), communications_update(), _ctx() (+14 more)

### Community 29 - "Export Hydrate Routes"
Cohesion: 0.14
Nodes (22): download_clients_xlsx(), download_xlsx(), _ensure_hub_ready(), _ensure_moysklad_data(), _export_rows(), _fetch_moysklad_positions_background(), _hydrate_hub_from_cache(), _moysklad_push_available() (+14 more)

### Community 30 - "Background Job Queue"
Cohesion: 0.14
Nodes (16): BackgroundJobService, get_background_jobs(), JobProgress, Фоновые задачи: lazy AI-сегментация и push-обновления через WebSocket., In-process очередь фоновых задач (тонкий backend без отдельного worker)., Дешёвый счётчик из текущего прогресса (без скана всей базы)., _NoopCache, test_hub_upsert_results() (+8 more)

### Community 31 - "Clients Group Filters"
Cohesion: 0.13
Nodes (20): build_clients_query(), client_url_id(), collect_group_counts(), group_chip_hue(), Отдельные группы клиента из поля «Группы» (МойСклад / AI)., Сегменты для фильтра «Группы»: теги, каналы и типы канала продаж., Уникальные группы, каналы и типы канала продаж с числом клиентов., ID клиента для URL path (percent-encoded). (+12 more)

### Community 32 - "Gender AI Enrichment"
Cohesion: 0.14
Nodes (21): apply_gender_not_applicable_labels(), apply_resolved_gender(), _client_display_name(), collect_gender_name_candidates(), ensure_ai_recommendation(), _format_rub_short(), infer_gender_heuristic(), _looks_like_person_name() (+13 more)

### Community 33 - "Export Format Helpers"
Cohesion: 0.19
Nodes (19): _cell_value(), display_cell_value(), format_messenger_history(), _format_order_date(), _normalize_phone_digits(), _parse_sort_date(), Any, datetime (+11 more)

### Community 34 - "MoySklad Tag Push"
Cohesion: 0.19
Nodes (16): _as_crm_tag(), build_ai_tags(), counterparty_id_for_row(), merge_counterparty_tags(), MoySkladPushResult, push_segments_to_moysklad(), Any, Выгрузка AI-сегментов обратно в теги контрагентов Мой Склад. (+8 more)

### Community 35 - "Clients Table WS JS"
Cohesion: 0.21
Nodes (19): applyColumnOrder(), applyColumnVisibility(), currentColumnOrder(), esc(), initClientsTable(), initColumnDragDrop(), initColumnVisibility(), loadColumnOrder() (+11 more)

### Community 36 - "Main Health WebSocket"
Cohesion: 0.14
Nodes (16): _append_vary(), clients_ai_poll(), clients_ai_status(), clients_websocket(), health_ready(), healthcheck(), _mask_secret(), _moysklad_config_ctx() (+8 more)

### Community 37 - "TG Nick Enrichment"
Cohesion: 0.19
Nodes (17): apply_tg_nick_by_phone_to_hub(), enrich_tg_nick_by_phone(), extract_tg_nick_from_messages(), extract_tg_nick_from_row(), extract_tg_nick_from_text(), @username из строки: целиком «@nick» или встроенный в текст., @username по телефону из TG Data Export или кэша Bot API (не lookup по API)., ТГ ник из телефона, Наименования, комментариев и переписки. (+9 more)

### Community 38 - "GreenAPI WhatsApp"
Cohesion: 0.21
Nodes (5): _get_request_semaphore(), GreenApiClient, Response, Green API — WhatsApp (и опционально Telegram-инстанс Green API)., Semaphore

### Community 39 - "Campaigns Placeholder"
Cohesion: 0.17
Nodes (8): CampaignService, Управление рекламными кампаниями — PLACEHOLDER.  Задача (по ТЗ): создание кампан, # TODO: валидация сегментов, привязка CampaignAgent для оффера, CRM-слой: бизнес-логика поверх репозитория.  Активно: StatsService. LeadService, CrmStats, Статистика CRM — базовая реализация поверх репозитория.  Считает то, что доступн, StatsService, Campaign

### Community 40 - "AI Cell Coverage"
Cohesion: 0.20
Nodes (14): client_cell_state(), client_cell_value(), Состояние ячейки: value | running | unknown | empty., Значение ячейки для таблицы клиентов и экспорта., finalize_ai_coverage_row(), После AI/обогащения пометить незаполненные AI-поля как no data., test_client_cell_state_empty_after_ai(), test_client_cell_state_running_before_ai() (+6 more)

### Community 41 - "VIP Order Computed"
Cohesion: 0.15
Nodes (15): enrich_row_computed(), format_last_order_date_display(), is_vip(), last_order_date(), last_order_status(), _parse_date(), datetime, Добавляет вычисляемые поля к строке клиента. (+7 more)

### Community 42 - "InMemory Cache Fallback"
Cohesion: 0.20
Nodes (9): InMemoryCache, Fallback-кэш в памяти процесса (без TTL-инвалидации, ограничен размером)., _service(), test_backend_falls_back_to_memory_without_redis(), test_get_results_missing_key_returns_none(), test_inmemory_cache_evicts_oldest(), test_save_and_get_moysklad_sync_round_trip(), test_save_and_get_results_round_trip() (+1 more)

### Community 43 - "MoySklad Sync Pipeline"
Cohesion: 0.23
Nodes (13): Справочник каналов продаж: id → наименование., sales_channels_by_id(), _apply_rows_to_hub(), _cache_matches_limits(), _load_from_cache(), MoySkladSyncResult, Any, Синхронизация данных Мой Склад → DataHub. (+5 more)

### Community 44 - "Excel Connector"
Cohesion: 0.31
Nodes (7): customer_from_row(), ExcelConnector, order_from_row(), Any, Excel-коннектор — единственный полностью рабочий на текущем этапе.  Использует с, _to_float(), _to_int()

### Community 45 - "DataHub Filters"
Cohesion: 0.22
Nodes (10): get_data_hub(), Центральное хранилище данных CRM в памяти процесса., _rows_need_gender_enrich(), merge_enriched_rows(), row_keyword_text(), sort_client_rows(), Пересчитать поля из заказов МойСклад и убрать ложные AI-метки., refresh_row_for_display() (+2 more)

### Community 47 - "Gender Map Apply"
Cohesion: 0.21
Nodes (12): apply_gender_map_to_hub(), apply_gender_map_to_rows(), is_empty_cell(), normalize_naimenovanie_key(), _normalized_cell(), Уникальные Наименование без пола — кандидаты для эвристики и LLM., Уникальные Наименование, похожие на ФИО физлица., Записать Пол в parsed/results и вернуть обновлённые строки results. (+4 more)

### Community 48 - "Telegram Bot Client"
Cohesion: 0.26
Nodes (3): TelegramBotClient, Тесты Telegram Bot API., test_get_updates_returns_empty_on_connect_timeout()

### Community 49 - "HTMX Preload Ext"
Cohesion: 0.40
Nodes (10): forceFormDataInOrder(), getClosestAttribute(), getEventHandler(), init(), isPreloadableFormElement(), isValidNodeForPreloading(), load(), processResponse() (+2 more)

### Community 50 - "Telegram Export Import"
Cohesion: 0.33
Nodes (10): _apply_tg_export_to_hub(), _bootstrap_telegram_export(), _import_telegram_export_from_path(), Path, Привязать TG export ко всем клиентам в hub и сохранить в кэш., _save_upload_stream(), static_asset(), telegram_export_import() (+2 more)

### Community 51 - "Clients Page Cache"
Cohesion: 0.29
Nodes (10): _clients_ctx_with_tg(), clients_page(), clients_page_partial(), clients_table_partial(), _ensure_hub_cache_only(), _hydrate_moysklad_from_cache(), Быстрая подгрузка hub только из Redis/Postgres — без API МойСклад., Быстрая подгрузка МойСклад только из Redis/Postgres — без API. (+2 more)

### Community 52 - "HTTP Retry Helper"
Cohesion: 0.29
Nodes (8): Any, Response, Повтор HTTP-запросов при rate limit и временных ошибках., request_with_retry(), _retry_delay_seconds(), AsyncClient, Тесты retry для HTTP-клиентов., test_request_with_retry_on_429()

### Community 54 - "Auto Comm Rules"
Cohesion: 0.31
Nodes (5): AutoCommRule, CommunicationsSettings, get_comm_settings(), Any, Настройки автокоммуникации с клиентом.

### Community 55 - "Integration Status Cache"
Cohesion: 0.28
Nodes (5): _CacheEntry, get_status_cache(), Короткий in-memory кэш для статусов интеграций (без лишних API-вызовов)., StatusCache, T

### Community 56 - "Leads Placeholder"
Cohesion: 0.32
Nodes (4): LeadService, Управление лидами и воронкой — PLACEHOLDER.  Задача (по ТЗ): приём входящих лидо, # TODO: матчинг с существующим клиентом, назначение оператора, Lead

### Community 57 - "Priority Card AI"
Cohesion: 0.25
Nodes (8): Any, Сразу обновить бриф эвристикой, пока приоритетный AI догоняет., Приоритет открытой карточки: прервать/отложить фон, при необходимости force., _recommendation_needs_refresh(), _refresh_client_recommendation(), _run_enrichment(), _schedule_client_priority_ai(), _workflow_ctx()

### Community 58 - "Compact Orders Display"
Cohesion: 0.36
Nodes (7): compact_orders_for_display(), Компактные строки заказов для быстрого HTMX-рендера., _truncate_text(), Тесты компактного отображения заказов., test_compact_orders_includes_sales_channel(), test_compact_orders_sorted_newest_first(), test_compact_orders_truncates_long_text()

### Community 60 - "Clients Pagination UI"
Cohesion: 0.43
Nodes (6): _clients_ctx(), _pagination_pages(), Номера страниц для UI; None — многоточие., test_pagination_pages_near_start(), test_pagination_pages_single_page(), test_pagination_pages_with_ellipsis()

### Community 61 - "Excel Export Columns"
Cohesion: 0.29
Nodes (7): export_columns(), Порядок колонок: как во входном Excel + AI-поля., row_for_export(), test_export_columns_preserves_excel_order_and_adds_ai_fields(), test_row_for_export_maps_tg_nick_and_history(), test_export_columns_for_moysklad_matches_excel_plus_ai(), test_row_for_export_preserves_excel_structure()

### Community 62 - "Workbook Upload Cache"
Cohesion: 0.47
Nodes (3): parse_workbook(), test_parse_workbook_reads_contragents_file(), test_upload_cache_round_trip()

### Community 63 - "Logging Config"
Cohesion: 0.40
Nodes (3): configure_logging(), RailwayColorFormatter, LogRecord

### Community 64 - "WebSocket Connections"
Cohesion: 0.40
Nodes (3): ConnectionManager, WebSocket, Подписчики WebSocket для live-обновлений таблицы клиентов.

### Community 65 - "Money RUB Format"
Cohesion: 0.50
Nodes (4): format_money_rub(), _format_order_amount(), Формат суммы: «5 760 р.», test_format_money_rub_uses_space_and_r_suffix()

### Community 66 - "Nav Sidebar Partials"
Cohesion: 0.50
Nodes (4): HtmxNavItems, MainNav, SettingsSubnav, LeftSidebar

## Ambiguous Edges - Review These
- `EnrichProgress` → `ErrorPartial`  [AMBIGUOUS]
  app/templates/partials/error.html · relation: conceptually_related_to
- `MoySkladPushTags` → `MoySkladConnector`  [AMBIGUOUS]
  docs/SPEC.md · relation: conceptually_related_to

## Knowledge Gaps
- **33 isolated node(s):** `Uvicorn`, `openpyxl`, `pandas`, `httpx`, `Pydantic` (+28 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `EnrichProgress` and `ErrorPartial`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `MoySkladPushTags` and `MoySkladConnector`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `Settings` connect `App Settings Config` to `AI Narrative Style`, `Excel Parse Dedup`, `MoySklad API Client`, `Data Source Connectors`, `Postgres Persist Layer`, `AI Agent Interface`, `Cache Service API`, `Hub AI Merge Ops`, `Export Hydrate Routes`, `Background Job Queue`, `MoySklad Tag Push`, `GreenAPI WhatsApp`, `InMemory Cache Fallback`, `MoySklad Sync Pipeline`, `Cache Backend Redis`, `Telegram Bot Client`, `Messenger Connector`, `Messenger Message Store`, `Workbook Upload Cache`, `WebSocket Connections`?**
  _High betweenness centrality (0.106) - this node is a cross-community bridge._
- **Why does `DataHub` connect `DataHub Core` to `WebSocket Connections`, `MoySklad Tag Push`, `MoySklad Sync Pipeline`, `App Settings Config`, `DataHub Filters`, `DataHub Unit Tests`, `Performance UI Tests`, `Hub AI Merge Ops`, `Export Hydrate Routes`, `Background Job Queue`?**
  _High betweenness centrality (0.065) - this node is a cross-community bridge._
- **Why does `SegmentationService` connect `AI Narrative Style` to `Main Health WebSocket`, `App Settings Config`, `Computed Sales Fields`, `AI Agent Interface`, `App Lifespan Keepalive`, `Hub AI Merge Ops`, `Background Job Queue`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `Settings` (e.g. with `CampaignAgent` and `EnrichmentAgent`) actually correct?**
  _`Settings` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 6 inferred relationships involving `DataHub` (e.g. with `BackgroundJobService` and `ConnectionManager`) actually correct?**
  _`DataHub` has 6 INFERRED edges - model-reasoned connections that need verification._