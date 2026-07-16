import pytest

from app.services.fields import (
    SALES_CHANNEL_TYPE_DIRECT,
    SALES_CHANNEL_TYPE_HYBRID,
    SALES_CHANNEL_TYPE_MARKETPLACE,
    apply_ai_field,
    channel_type_from_channel,
    client_status_from_orders,
    enrich_row_computed,
    guess_gender,
    infer_gender_heuristic,
    is_direct_sales_channel,
    is_marketplace_channel,
    normalize_gender_label,
    order_count_for_row,
    recipient_name_from_row,
    sales_channel_type_for_row,
    sales_type_from_channel,
)
from app.services.moysklad.mapper import order_to_row


def test_apply_ai_field_stores_original_when_changed() -> None:
    row: dict = {"Группы": "старый"}
    ai_fields: list[str] = []
    apply_ai_field(row, "Группы", "новый", ai_fields)
    assert row["Группы"] == "новый"
    assert row["_ai_original"]["Группы"] == "старый"
    assert ai_fields == ["Группы"]


def test_apply_ai_field_skips_original_when_empty_before() -> None:
    row: dict = {"Группы": None}
    ai_fields: list[str] = []
    apply_ai_field(row, "Группы", "новый", ai_fields)
    assert row["Группы"] == "новый"
    assert "_ai_original" not in row


def test_marketplace_channels() -> None:
    for channel in (
        "Яндекс.Маркет",
        "Ozon",
        "Flowwow",
        "FLOW WOW",
        "Flawery",
        "Флавери",
        "Wildberries",
        "Авито",
    ):
        assert is_marketplace_channel(channel) is True
        assert is_direct_sales_channel(channel) is False
        assert channel_type_from_channel(channel) == SALES_CHANNEL_TYPE_MARKETPLACE
        assert sales_type_from_channel(channel) == SALES_CHANNEL_TYPE_MARKETPLACE


def test_direct_sales_channels() -> None:
    for channel in (
        "Витрина",
        "Telegram",
        "WhatsApp",
        "WhatsApp/MAX",
        "Прямые продажи",
        "Сайт vereskflowers.ru",
        "https://vereskflowers.ru/",
    ):
        assert is_direct_sales_channel(channel) is True
        assert is_marketplace_channel(channel) is False
        assert channel_type_from_channel(channel) == SALES_CHANNEL_TYPE_DIRECT
        assert sales_type_from_channel(channel) == SALES_CHANNEL_TYPE_DIRECT


def test_sales_channel_type_hybrid_when_direct_and_marketplace() -> None:
    row = {
        "UUID": "1",
        "_orders_context": [
            {"Канал продаж": "Ozon"},
            {"Канал продаж": "Витрина"},
        ],
        "_order_channels_all": ["Ozon", "Витрина"],
    }
    assert sales_channel_type_for_row(row) == SALES_CHANNEL_TYPE_HYBRID


def test_sales_channel_lists_all_unique_channels() -> None:
    from app.services.fields import enrich_row_computed, sales_channel_for_row

    row = {
        "UUID": "1",
        "_orders_context": [
            {"Канал продаж": "Витрина", "Дата": "01.01.2026"},
            {"Канал продаж": "Ozon", "Дата": "02.01.2026"},
            {"Канал продаж": "Витрина", "Дата": "03.01.2026"},
        ],
        "_order_channels_all": ["Витрина", "Ozon", "Витрина"],
    }
    assert sales_channel_for_row(row) == "Витрина, Ozon"
    enriched = enrich_row_computed(row)
    assert enriched["Канал продаж"] == "Витрина, Ozon"
    assert enriched["Тип канала продаж"] == SALES_CHANNEL_TYPE_HYBRID


def test_last_order_date_without_time() -> None:
    from app.services.fields import last_order_date

    row = {
        "_orders_context": [
            {"Дата": "15.03.2026 18:30:00", "Канал продаж": "Витрина"},
        ],
    }
    assert last_order_date(row) == "15.03.2026"


def test_sales_channel_type_direct_only_for_whitelist_channels() -> None:
    row = {
        "UUID": "2",
        "_order_channels_all": [
            "Telegram",
            "WhatsApp/MAX",
            "Витрина",
            "Прямые продажи",
            "Сайт vereskflowers.ru",
        ],
    }
    assert sales_channel_type_for_row(row) == SALES_CHANNEL_TYPE_DIRECT


def test_sales_channel_type_hybrid_for_missing_channel_with_direct() -> None:
    row = {
        "UUID": "3",
        "_order_channels_all": ["Витрина", ""],
    }
    assert sales_channel_type_for_row(row) == SALES_CHANNEL_TYPE_HYBRID


def test_row_matches_sales_filter_by_channel_rules() -> None:
    from app.services.fields import row_matches_sales_filter

    direct = {
        "_order_channels_all": ["Витрина", "Telegram"],
    }
    market = {
        "_order_channels_all": ["Flowwow"],
    }
    hybrid = {
        "_order_channels_all": ["Витрина", "Ozon"],
    }
    assert row_matches_sales_filter(direct, "direct") is True
    assert row_matches_sales_filter(direct, "marketplace") is False
    assert row_matches_sales_filter(market, "marketplace") is True
    assert row_matches_sales_filter(market, "direct") is False
    assert row_matches_sales_filter(hybrid, "marketplace") is True
    assert row_matches_sales_filter(hybrid, "direct") is False


def test_sales_filter_reuses_precomputed_classification() -> None:
    from app.services.fields import ensure_sales_classification, row_matches_sales_filter

    class NoIteration(list):
        def __iter__(self):
            raise AssertionError("filter must reuse the precomputed sales type")

    row = ensure_sales_classification({"_order_channels_all": ["Flowwow", "Ozon"]})
    row["_order_channels_all"] = NoIteration(row["_order_channels_all"])

    assert row_matches_sales_filter(row, "marketplace") is True
    assert row_matches_sales_filter(row, "direct") is False


def test_sales_channel_type_marketplace_for_only_missing_channel() -> None:
    row = {
        "UUID": "3b",
        "_order_channels_all": ["", ""],
    }
    assert sales_channel_type_for_row(row) == SALES_CHANNEL_TYPE_MARKETPLACE


@pytest.mark.parametrize(
    ("orders", "expected"),
    [
        (0, "новый"),
        (1, "новый"),
        (2, "повторный"),
        (3, "постоянный"),
        (10, "постоянный"),
    ],
)
def test_client_status_from_orders(orders: int, expected: str) -> None:
    row = {"Всего заказов": orders}
    assert client_status_from_orders(row) == expected
    assert order_count_for_row(row) == orders


def test_order_count_prefers_orders_context_over_zero_stored() -> None:
    row = {"_orders_count": 0, "Всего заказов": 0, "_orders_context": [{"№": "1"}]}
    assert order_count_for_row(row) == 1


def test_order_count_trusts_linked_orders_over_stale_vsego() -> None:
    row = {
        "_orders_context": [{"№": "1"}],
        "_orders_count": 1,
        "Всего заказов": 8,
    }
    assert order_count_for_row(row) == 1
    assert client_status_from_orders(row) == "новый"


def test_enrich_with_orders_syncs_vsego_with_linked_count() -> None:
    from app.services.excel_parser import ParsedWorkbook, enrich_with_orders

    contragents = ParsedWorkbook(
        source_type="contragents",
        rows=[{
            "UUID": "cp-1",
            "Наименование": "Султанова Лилия",
            "Всего заказов": 8,
        }],
        context_columns=["UUID", "Наименование"],
        segment_columns=[],
        total_rows=1,
        meta={},
    )
    orders = ParsedWorkbook(
        source_type="orders",
        rows=[{
            "№": "1",
            "Контрагент": "Султанова Лилия",
            "_moysklad_agent_id": "cp-1",
            "Дата": "2026-03-01",
            "Сумма": 1000,
        }],
        context_columns=["№", "Контрагент"],
        segment_columns=[],
        total_rows=1,
        meta={},
    )
    enriched = enrich_with_orders(contragents, orders)
    row = enriched.rows[0]
    assert row["Всего заказов"] == 1
    assert row["_orders_count"] == 1
    assert client_status_from_orders(row) == "новый"


def test_merge_enriched_rows_keeps_base_order_stats_over_stale_overlay() -> None:
    from app.services.export_format import merge_enriched_rows

    base = [{
        "UUID": "cp-1",
        "Наименование": "Султанова Лилия",
        "Всего заказов": 1,
        "_orders_count": 1,
        "_orders_context": [{"№": "1"}],
    }]
    overlay = [{
        "UUID": "cp-1",
        "Всего заказов": 8,
        "_orders_count": 8,
        "_ai_processed": True,
    }]
    merged = merge_enriched_rows(base, overlay, key_fn=lambda r: r["UUID"])
    assert merged[0]["Всего заказов"] == 1
    assert merged[0]["_orders_count"] == 1
    assert merged[0]["Статус"] == "новый"


def test_build_client_history_summary_includes_profile_and_orders() -> None:
    from app.services.fields import build_client_history_summary, ensure_ai_client_summary

    row = {
        "Наименование": "Султанова Лилия",
        "Заказчик или получатель": "получатель",
        "Пол": "Женский",
        "Группы": "премиум, постоянный клиент",
        "Теги": "#vip #8марта",
        "ВИП": "да",
        "Всего заказов": 8,
        "_orders_count": 8,
        "Средний чек": 12000,
        "Статус": "постоянный",
        "Канал продаж": "Telegram",
        "_orders_context": [
            {"№": "100", "Дата": "2026-03-01", "Сумма": 15000, "Канал продаж": "Telegram"},
            {"№": "101", "Дата": "2026-02-01", "Сумма": 9000, "Канал продаж": "Витрина"},
        ],
        "Заказанные позиции": "Розы ×15",
    }
    summary = build_client_history_summary(row)
    assert summary is not None
    assert "Султанова Лилия" in summary or "Султанова" in summary
    assert "8 заказ" in summary
    assert "постоянный" in summary.lower() or "VIP" in summary
    assert "Лояльность:" not in summary
    assert "Сегменты:" not in summary
    assert "История заказов:" not in summary
    assert "12 000" in summary or "12000" in summary or "средний чек" in summary.lower()
    assert "Роз" in summary or "сезонност" in summary.lower() or "повод" in summary.lower()

    enriched = ensure_ai_client_summary(row)
    assert enriched["_ai_client_summary"] == summary


def test_build_client_history_summary_avoids_phone_as_name() -> None:
    from app.services.fields import build_client_history_summary

    row = {
        "Наименование": "+79037179210",
        "Статус": "новый",
        "Всего заказов": 1,
        "_orders_count": 1,
        "Средний чек": 1929,
        "_orders_context": [
            {"Дата": "2025-08-27", "Сумма": 1929, "Позиции": "Коралловая роза в горшке"},
        ],
    }
    summary = build_client_history_summary(row)
    assert summary is not None
    assert not summary.startswith("+79037179210")
    assert "Лояльность:" not in summary
    assert "Теги:" not in summary
    assert "Клиент" in summary


def test_enrich_row_computed_sets_client_status() -> None:
    row = {"UUID": "1", "_orders_count": 5, "Статус": "Новый"}
    enriched = enrich_row_computed(row)
    assert enriched["Статус"] == "постоянный"
    assert enriched["Постоянный клиент"] == "да"


def test_enrich_row_computed_uses_order_sales_channel() -> None:
    row = {
        "UUID": "1",
        "_orders_context": [
            {
                "Дата": "2026-06-23T19:04:00",
                "Канал продаж": "Ozon",
            }
        ],
    }
    enriched = enrich_row_computed(row)
    assert enriched["Канал продаж"] == "Ozon"
    assert enriched["Тип канала продаж"] == SALES_CHANNEL_TYPE_MARKETPLACE
    assert enriched["Тип продаж"] == SALES_CHANNEL_TYPE_MARKETPLACE


def test_order_to_row_maps_sales_channel() -> None:
    row = order_to_row(
        {
            "id": "43e4bf7d-3961-11ef-0a80-09d400192095",
            "name": "00011",
            "moment": "2025-06-01T12:00:00.000",
            "sum": 150000,
            "salesChannel": {"name": "Витрина"},
            "agent": {"meta": {"href": "https://api.moysklad.ru/api/remap/1.2/entity/counterparty/cp-1"}},
        },
        {"cp-1": "Клиент"},
    )
    assert row["№"] == "00011"
    assert row["Канал продаж"] == "Витрина"


def test_order_to_row_resolves_sales_channel_by_id() -> None:
    channel_id = "61d6519a-ec0b-11ee-0a80-1751000827ea"
    row = order_to_row(
        {
            "id": "order-1",
            "name": "24255345",
            "sum": 0,
            "salesChannel": {
                "meta": {
                    "href": f"https://api.moysklad.ru/api/remap/1.2/entity/saleschannel/{channel_id}",
                }
            },
            "agent": {"id": "cp-1", "name": "Клиент"},
        },
        {"cp-1": "Клиент"},
        {channel_id: "Flowwow"},
    )
    assert row["Канал продаж"] == "Flowwow"


def test_guess_gender_from_name_and_patronymic() -> None:
    assert guess_gender("Иван Петров") == "Мужской"
    assert guess_gender("Ольга") == "Женский"
    assert guess_gender("Ермаков Данил") == "Мужской"
    assert guess_gender("Данил Ермаков") == "Мужской"
    assert guess_gender("Ростислав") == "Мужской"
    assert guess_gender("Ростислав Патерюхин") == "Мужской"
    assert guess_gender("Патерюхин Ростислав") == "Мужской"
    assert guess_gender("Ростислава Патерюхина") == "Женский"
    assert guess_gender("Петровна") == "Женский"
    assert guess_gender("Сергеевич") == "Мужской"
    assert guess_gender("Саша") is None
    assert guess_gender("Vladislav Koroteev") == "Мужской"
    assert guess_gender("Александра М") == "Женский"
    assert guess_gender("Алексей коллега") == "Мужской"
    assert guess_gender("маша") == "Женский"
    assert guess_gender("ИП Иванов") == "Мужской"
    assert guess_gender("ООО Иванов") == "Мужской"
    assert guess_gender("ИП Иванова") == "Женский"
    assert guess_gender("ООО Иванов Иван") == "Мужской"
    assert guess_gender("Покупатель с улицы") == "Мужской"
    assert guess_gender("покупатель с улицы") == "Мужской"
    assert guess_gender("Покупатель") == "Мужской"


def test_guess_gender_skips_service_and_company_labels() -> None:
    from app.services.fields import GENDER_NOT_APPLICABLE, guess_gender, is_non_person_label

    assert guess_gender("Аренда") is None
    assert guess_gender("Доставка") is None
    assert guess_gender("ООО Аренда") is None
    assert is_non_person_label("Аренда") is True
    assert is_non_person_label("Доставка") is True
    assert is_non_person_label("ООО Аренда") is True
    assert is_non_person_label("Ольга") is False
    assert is_non_person_label("Иван Петров") is False


def test_enrich_row_corrects_wrong_gender_for_rostislav() -> None:
    from app.services.fields import enrich_row_computed

    row = {
        "Наименование": "Ростислав Патерюхин",
        "Пол": "Женский",
        "_orders_count": 1,
    }
    enriched = enrich_row_computed(row)
    assert enriched["Пол"] == "Мужской"


def test_enrich_gender_marks_service_labels_not_applicable() -> None:
    from app.services.fields import GENDER_NOT_APPLICABLE, enrich_gender_by_unique_naimenovanie

    rows = [
        {"UUID": "1", "Наименование": "Аренда"},
        {"UUID": "2", "Наименование": "Доставка"},
        {"UUID": "3", "Наименование": "Иван Петров"},
    ]
    enriched = enrich_gender_by_unique_naimenovanie(rows)
    assert enriched[0]["Пол"] == GENDER_NOT_APPLICABLE
    assert enriched[1]["Пол"] == GENDER_NOT_APPLICABLE
    assert enriched[2]["Пол"] == "Мужской"


def test_unique_naimenovanie_excludes_service_labels() -> None:
    from app.services.fields import unique_naimenovanie_missing_gender

    rows = [
        {"Наименование": "Аренда"},
        {"Наименование": "Доставка"},
        {"Наименование": "маша"},
    ]
    names = unique_naimenovanie_missing_gender(rows)
    assert "Аренда" not in names
    assert "Доставка" not in names
    assert "маша" in names


def test_normalize_gender_label_accepts_not_applicable() -> None:
    from app.services.fields import GENDER_NOT_APPLICABLE, normalize_gender_label

    assert normalize_gender_label("не применимо") == GENDER_NOT_APPLICABLE
    assert normalize_gender_label("N/A") == GENDER_NOT_APPLICABLE


def test_enrich_gender_pokupatel_s_ulitsy() -> None:
    from app.services.fields import enrich_gender_by_unique_naimenovanie

    rows = [{"UUID": "1", "Наименование": "Покупатель с улицы"}]
    enriched = enrich_gender_by_unique_naimenovanie(rows)
    assert enriched[0]["Пол"] == "Мужской"


def test_strip_legal_entity_prefixes() -> None:
    from app.services.fields import strip_legal_entity_prefixes

    assert strip_legal_entity_prefixes("ИП Иванов") == "Иванов"
    assert strip_legal_entity_prefixes("ООО Иванов") == "Иванов"
    assert strip_legal_entity_prefixes('ООО "Ромашка"') == '"Ромашка"'
    assert strip_legal_entity_prefixes("Иван Петров") == "Иван Петров"


def test_unique_naimenovanie_missing_gender() -> None:
    from app.services.fields import unique_naimenovanie_missing_gender

    rows = [
        {"Наименование": "Vladislav Koroteev"},
        {"Наименование": "маша", "Пол": ""},
        {"Наименование": "ООО Ромашка"},
        {"Наименование": "Иван", "Пол": "Мужской"},
        {"Наименование": "@sigrifmeow"},
    ]
    names = unique_naimenovanie_missing_gender(rows)
    assert "Vladislav Koroteev" in names
    assert "маша" in names
    assert "@sigrifmeow" in names
    assert "ООО Ромашка" not in names
    assert "Иван" not in names

    ip_rows = [{"Наименование": "ИП Иванов"}, {"Наименование": "ООО Иванова"}]
    ip_names = unique_naimenovanie_missing_gender(ip_rows)
    assert "ИП Иванов" in ip_names
    assert "ООО Иванова" in ip_names


def test_enrich_gender_by_unique_naimenovanie() -> None:
    from app.services.fields import enrich_gender_by_unique_naimenovanie

    rows = [
        {"UUID": "1", "Наименование": "Ермаков Данил"},
        {"UUID": "2", "Наименование": "Ермаков Данил"},
        {"UUID": "3", "Наименование": "ООО Ромашка"},
    ]
    enriched = enrich_gender_by_unique_naimenovanie(rows)
    assert enriched[0]["Пол"] == "Мужской"
    assert enriched[1]["Пол"] == "Мужской"
    assert enriched[2].get("Пол") in (None, "")

    ip_rows = [{"UUID": "4", "Наименование": "ИП Иванов"}]
    ip_enriched = enrich_gender_by_unique_naimenovanie(ip_rows)
    assert ip_enriched[0]["Пол"] == "Мужской"


def test_infer_gender_from_moysklad_and_patronymic() -> None:
    row = {
        "Пол": "MALE",
        "Имя (для ИП и физ. лиц)": "Анна",
    }
    assert normalize_gender_label(row["Пол"]) == "Мужской"
    assert infer_gender_heuristic(row) == "Мужской"

    row = {"Отчество (для ИП и физ. лиц)": "Ивановна"}
    assert infer_gender_heuristic(row) == "Женский"


def test_infer_gender_from_orders_and_telegram() -> None:
    row = {
        "Наименование": "ООО Аренда",
        "_orders_context": [{"Комментарий": "Получатель\tМария"}],
        "_messenger_context": [
            {"channel": "telegram", "display_name": "Екатерина Смирнова", "text": "здравствуйте"},
        ],
    }
    assert recipient_name_from_row(row) == "Мария"
    assert infer_gender_heuristic(row) == "Женский"

    enriched = enrich_row_computed(row)
    assert enriched["Пол"] == "Женский"


def test_infer_gender_from_message_text() -> None:
    row = {
        "Наименование": "Клиент 1",
        "_messenger_context": [
            {"channel": "telegram", "text": "Меня зовут Дмитрий, букет для мамы"},
        ],
    }
    assert infer_gender_heuristic(row) == "Мужской"
