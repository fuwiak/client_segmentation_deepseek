from app.services.data_hub import DataHub
from app.services.excel_parser import ParsedWorkbook


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
