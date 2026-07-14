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
