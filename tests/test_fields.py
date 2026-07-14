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


def test_sales_channel_type_marketplace_if_any_order_not_direct() -> None:
    row = {
        "UUID": "1",
        "_orders_context": [
            {"Канал продаж": "Ozon"},
            {"Канал продаж": "Витрина"},
        ],
        "_order_channels_all": ["Ozon", "Витрина"],
    }
    assert sales_channel_type_for_row(row) == SALES_CHANNEL_TYPE_MARKETPLACE


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


def test_sales_channel_type_marketplace_for_missing_channel() -> None:
    row = {
        "UUID": "3",
        "_order_channels_all": ["Витрина", ""],
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
