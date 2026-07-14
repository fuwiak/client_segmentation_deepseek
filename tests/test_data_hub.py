from app.services.data_hub import DataHub
from app.services.excel_parser import ParsedWorkbook


def _sample_hub() -> DataHub:
    hub = DataHub()
    hub.set_workbook(
        ParsedWorkbook(
            source_type="contragents",
            rows=[
                {
                    "UUID": "1",
                    "Наименование": "Анна",
                    "Телефон": "+79991112233",
                    "Тип продаж": "прямые продажи",
                    "Группы": "VIP",
                },
                {
                    "UUID": "2",
                    "Наименование": "+78887776655",
                    "Телефон": "",
                    "Тип продаж": "прямые продажи",
                    "Группы": "новый",
                },
                {
                    "UUID": "3",
                    "Наименование": "OBI",
                    "Телефон": "OBI",
                    "Тип продаж": "маркетплейс",
                    "Группы": "корп",
                },
            ],
            context_columns=["UUID", "Наименование", "Телефон", "Группы"],
            segment_columns=[],
            total_rows=3,
            meta={"source": "moysklad"},
        ),
        None,
    )
    return hub


def test_active_rows_merges_parsed_with_enrichment_overlay() -> None:
    hub = DataHub()
    hub.set_workbook(
        ParsedWorkbook(
            source_type="contragents",
            rows=[
                {"UUID": "1", "Наименование": "А"},
                {"UUID": "2", "Наименование": "Б"},
            ],
            context_columns=["UUID", "Наименование"],
            segment_columns=[],
            total_rows=2,
            meta={"source": "moysklad"},
        ),
        None,
    )
    hub.set_results(
        [{"UUID": "1", "Наименование": "А", "Группы": "VIP", "_enrichment_fields": ["Группы"]}],
        {"enriched": True},
    )

    rows = hub.active_rows()

    assert len(rows) == 2
    assert rows[0]["Группы"] == "VIP"
    assert rows[1]["Наименование"] == "Б"


def test_filter_rows_by_keyword_and_phone() -> None:
    hub = _sample_hub()
    by_name = hub.filter_rows(sales_filter="all", q="анна")
    assert len(by_name) == 1
    assert by_name[0]["UUID"] == "1"

    by_phone = hub.filter_rows(sales_filter="all", phone="8887776655")
    assert len(by_phone) == 1
    assert by_phone[0]["UUID"] == "2"


def test_filter_rows_sort_by_name() -> None:
    hub = _sample_hub()
    rows = hub.filter_rows(sales_filter="all", sort="Наименование", order="asc")
    names = [r["Наименование"] for r in rows]
    assert names == sorted(names, key=str.lower)


def test_filter_rows_by_group_exact_match() -> None:
    hub = _sample_hub()
    rows = hub.filter_rows(sales_filter="all", group="VIP")
    assert len(rows) == 1
    assert rows[0]["UUID"] == "1"

    rows_new = hub.filter_rows(sales_filter="all", group="новый")
    assert len(rows_new) == 1
    assert rows_new[0]["UUID"] == "2"


def test_get_client_matches_normalized_phone() -> None:
    hub = DataHub()
    hub.parsed = ParsedWorkbook(
        source_type="contragents",
        rows=[{
            "UUID": "cp-1",
            "Наименование": "89603002010",
            "Телефон": "+79603002010",
            "_orders_context": [{"№": "1"}],
            "_orders_count": 1,
        }],
        context_columns=["UUID", "Наименование", "Телефон"],
        segment_columns=[],
        total_rows=1,
    )
    client = hub.get_client("+79603002010")
    assert client is not None
    assert client["_orders_count"] == 1


def test_lookup_client_row_is_o1_indexed() -> None:
    hub = _sample_hub()
    row = hub.lookup_client_row("1")
    assert row is not None
    assert row["Наименование"] == "Анна"
    assert hub.lookup_client_row("missing-id") is None


def test_get_client_orders_resolves_full_order_entity() -> None:
    hub = DataHub()
    hub.set_workbook(
        ParsedWorkbook(
            source_type="contragents",
            rows=[{
                "UUID": "cp-orders",
                "Наименование": "Клиент",
                "_orders_context": [{"№": "100", "Дата": "2026-03-01", "Сумма": 5000}],
                "_orders_count": 1,
            }],
            context_columns=["UUID", "Наименование"],
            segment_columns=[],
            total_rows=1,
            meta={"source": "moysklad"},
        ),
        ParsedWorkbook(
            source_type="orders",
            rows=[{
                "№": "100",
                "Дата": "2026-03-01",
                "Сумма": 5000,
                "Канал продаж": "Витрина",
                "Позиции": "Розы ×10",
                "Статус": "Отгружен",
            }],
            context_columns=[],
            segment_columns=[],
            total_rows=1,
            meta={},
        ),
    )
    _, orders, _ = hub.get_client_orders("cp-orders")
    assert orders[0]["Канал продаж"] == "Витрина"
    assert orders[0]["Позиции"] == "Розы ×10"


def test_get_client_orders_returns_context_without_active_rows_scan() -> None:
    hub = DataHub()
    hub.set_workbook(
        ParsedWorkbook(
            source_type="contragents",
            rows=[{
                "UUID": "cp-orders",
                "Наименование": "Клиент",
                "_orders_context": [{"№": "100", "Дата": "2026-03-01", "Сумма": 5000}],
                "_orders_count": 3,
            }],
            context_columns=["UUID", "Наименование"],
            segment_columns=[],
            total_rows=1,
            meta={"source": "moysklad"},
        ),
        None,
    )
    client, orders, total = hub.get_client_orders("cp-orders")
    assert client is not None
    assert len(orders) == 1
    assert total == 3


def test_get_client_orders_finds_orders_from_cache_when_context_empty() -> None:
    hub = DataHub()
    orders_rows = [{
        "№": "55",
        "Контрагент": "Аренда",
        "_moysklad_agent_id": "cp-arenda",
        "Дата": "2026-03-01",
        "Сумма": 1000,
        "Статус": "OK",
    }]
    hub.set_workbook(
        ParsedWorkbook(
            source_type="contragents",
            rows=[{
                "UUID": "cp-arenda",
                "Наименование": "Аренда",
                "Всего заказов": 0,
            }],
            context_columns=["UUID", "Наименование"],
            segment_columns=[],
            total_rows=1,
            meta={"source": "moysklad"},
        ),
        ParsedWorkbook(
            source_type="orders",
            rows=orders_rows,
            context_columns=["№", "Контрагент"],
            segment_columns=[],
            total_rows=1,
            meta={},
        ),
    )
    hub.parsed.rows[0]["_orders_context"] = []
    hub.parsed.rows[0]["_orders_count"] = 0

    client, orders, total = hub.get_client_orders("cp-arenda")

    assert client is not None
    assert len(orders) == 1
    assert total == 1
    assert orders[0]["№"] == "55"
    assert client["_orders_context"][0]["№"] == "55"


def test_touch_bumps_version_and_clears_filter_cache() -> None:
    hub = _sample_hub()
    version_before = hub.version
    rows_first = hub.filter_rows(sales_filter="all", q="анна")
    assert len(rows_first) == 1
    hub.touch()
    assert hub.version == version_before + 1
    hub.set_results([{"UUID": "9", "Наименование": "Новый"}], {"processed": 1})
    assert hub.version == version_before + 2


def test_filter_rows_with_groups_single_pass() -> None:
    hub = _sample_hub()
    rows, group_options, groups_total = hub.filter_rows_with_groups(
        sales_filter="all",
        group="VIP",
    )
    assert len(rows) == 1
    assert rows[0]["UUID"] == "1"
    assert groups_total == 3
    assert any(item["name"] == "VIP" for item in group_options)


def test_filter_rows_with_groups_includes_sales_channels() -> None:
    hub = DataHub()
    hub.set_workbook(
        ParsedWorkbook(
            source_type="contragents",
            rows=[
                {
                    "UUID": "cp-1",
                    "Наименование": "Анна",
                    "Группы": "VIP",
                },
                {
                    "UUID": "cp-2",
                    "Наименование": "Борис",
                    "Группы": "новый",
                },
            ],
            context_columns=["UUID", "Наименование", "Группы"],
            segment_columns=[],
            total_rows=2,
            meta={"source": "moysklad"},
        ),
        ParsedWorkbook(
            source_type="orders",
            rows=[
                {
                    "№": "100",
                    "Контрагент": "Анна",
                    "_moysklad_agent_id": "cp-1",
                    "Канал продаж": "Flowwow",
                },
                {
                    "№": "101",
                    "Контрагент": "Борис",
                    "_moysklad_agent_id": "cp-2",
                    "Канал продаж": "Ozon",
                },
            ],
            context_columns=[],
            segment_columns=[],
            total_rows=2,
            meta={},
        ),
    )
    rows, group_options, groups_total = hub.filter_rows_with_groups(sales_filter="all")
    names = {item["name"] for item in group_options}
    assert "Flowwow" in names
    assert "Ozon" in names
    assert "VIP" in names
    filtered, _, _ = hub.filter_rows_with_groups(sales_filter="all", group="Flowwow")
    assert len(filtered) == 1
    assert filtered[0]["UUID"] == "cp-1"


def test_filter_rows_with_groups_includes_sales_channel_types() -> None:
    from app.services.fields import SALES_CHANNEL_TYPE_MARKETPLACE

    hub = DataHub()
    hub.set_workbook(
        ParsedWorkbook(
            source_type="contragents",
            rows=[
                {"UUID": "cp-1", "Наименование": "Анна"},
                {"UUID": "cp-2", "Наименование": "Борис"},
            ],
            context_columns=["UUID", "Наименование"],
            segment_columns=[],
            total_rows=2,
            meta={"source": "moysklad"},
        ),
        ParsedWorkbook(
            source_type="orders",
            rows=[
                {
                    "№": "100",
                    "_moysklad_agent_id": "cp-1",
                    "Канал продаж": "Flowwow",
                },
                {
                    "№": "101",
                    "_moysklad_agent_id": "cp-2",
                    "Канал продаж": "Витрина",
                },
            ],
            context_columns=[],
            segment_columns=[],
            total_rows=2,
            meta={},
        ),
    )
    _, group_options, _ = hub.filter_rows_with_groups(sales_filter="all")
    names = {item["name"] for item in group_options}
    assert SALES_CHANNEL_TYPE_MARKETPLACE in names
    assert "прямые продажи" in names
    filtered, _, _ = hub.filter_rows_with_groups(
        sales_filter="all",
        group=SALES_CHANNEL_TYPE_MARKETPLACE,
    )
    assert len(filtered) == 1
    assert filtered[0]["UUID"] == "cp-1"
