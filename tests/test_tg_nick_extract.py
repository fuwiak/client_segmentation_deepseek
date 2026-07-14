from app.services.fields import extract_tg_nick_from_messages, extract_tg_nick_from_row, extract_tg_nick_from_text


def test_extract_tg_nick_from_telegram_messages() -> None:
    messages = [
        {
            "channel": "telegram",
            "username": "anna_flowers",
            "sender": "anna_flowers",
            "text": "Привет",
        }
    ]
    assert extract_tg_nick_from_messages(messages) == "@anna_flowers"


def test_extract_tg_nick_ignores_display_names() -> None:
    messages = [
        {
            "channel": "telegram",
            "sender": "Юлия Зейналова",
            "text": "Привет",
        }
    ]
    assert extract_tg_nick_from_messages(messages) is None


def test_extract_tg_nick_from_naimenovanie() -> None:
    assert extract_tg_nick_from_text("@sigrifmeow") == "@sigrifmeow"
    assert extract_tg_nick_from_text("@ab") is None
    assert extract_tg_nick_from_text("Клиент @anna_flowers") == "@anna_flowers"


def test_extract_tg_nick_from_row_naimenovanie() -> None:
    row = {"Наименование": "@sigrifmeow", "ТГ ник": ""}
    assert extract_tg_nick_from_row(row) == "@sigrifmeow"


def test_enrich_row_computed_sets_tg_nick_from_naimenovanie() -> None:
    from app.services.fields import enrich_row_computed

    row = {"Наименование": "@sigrifmeow"}
    enriched = enrich_row_computed(row)
    assert enriched["ТГ ник"] == "@sigrifmeow"
