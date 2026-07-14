from app.services.fields import extract_tg_nick_from_messages


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
