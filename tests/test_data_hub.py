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
