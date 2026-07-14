import gzip
import json
from pathlib import Path

from app.services.telegram_export import (
    build_export_index,
    messages_for_row,
    normalize_export_phone,
    parse_telegram_export_bytes,
    parse_telegram_export_file,
    tg_conversation_label,
    tg_nick_for_row,
)

FIXTURE = Path(__file__).parent / "fixtures" / "telegram_export_sample.json"


def test_normalize_export_phone_formats() -> None:
    assert normalize_export_phone("0079163649615") == "9163649615"
    assert normalize_export_phone("+7 916 364-96-15") == "9163649615"
    assert normalize_export_phone("89163649615") == "9163649615"


def test_build_export_index_links_chat_by_phone() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    index = build_export_index(data)
    assert index["meta"]["chats_with_phone"] == 1
    assert "9163649615" in index["by_phone"]
    assert len(index["by_phone"]["9163649615"]) == 3


def test_build_export_index_stores_username() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["chats"]["list"][0]["username"] = "yulia_flowers"
    index = build_export_index(data)
    assert "yulia_flowers" in index["by_username"]
    assert index["phone_username"]["9163649615"] == "yulia_flowers"


def test_messages_for_row_matches_client_phone() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    index = build_export_index(data)
    row = {"Телефон": "+79163649615", "Наименование": "Юлия Зейналова"}
    msgs = messages_for_row(index, row)
    assert len(msgs) == 3
    assert msgs[0]["source"] == "telegram_export"


def test_tg_conversation_label() -> None:
    row = {
        "_tg_export_context": [
            {"text": "Привет, хочу букет"},
            {"text": "Добрый день"},
        ]
    }
    label = tg_conversation_label(row)
    assert "✓ 2 сообщ." in label
    assert "Добрый день" in label


def test_tg_nick_for_row_from_phone_username_map() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["chats"]["list"][0]["username"] = "yulia_flowers"
    index = build_export_index(data)
    nick = tg_nick_for_row(index, {"Телефон": "+79163649615"})
    assert nick == "@yulia_flowers"


def test_build_phone_username_lookup_messenger() -> None:
    from app.services.telegram_export import build_phone_username_lookup

    messenger_index = {
        "by_phone": {
            "9163649615": [
                {"channel": "telegram", "username": "danil_e", "text": "hi"},
            ]
        }
    }
    assert build_phone_username_lookup(None, messenger_index) == {"9163649615": "danil_e"}


def test_build_phone_username_lookup_merges_export_and_messenger() -> None:
    from app.services.telegram_export import build_phone_username_lookup

    export_index = {"phone_username": {"9163649615": "from_export"}}
    messenger_index = {
        "by_phone": {
            "9991112233": [
                {"channel": "telegram", "username": "other_user", "text": "hi"},
            ]
        }
    }
    merged = build_phone_username_lookup(export_index, messenger_index)
    assert merged["9163649615"] == "from_export"
    assert merged["9991112233"] == "other_user"


def test_parse_telegram_export_file(tmp_path: Path) -> None:
    target = tmp_path / "export.json"
    target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    index = parse_telegram_export_file(target)
    assert index["meta"]["phones_indexed"] == 1


def test_parse_telegram_export_gzip(tmp_path: Path) -> None:
    raw = FIXTURE.read_bytes()
    gz_path = tmp_path / "export.json.gz"
    gz_path.write_bytes(gzip.compress(raw))
    index = parse_telegram_export_bytes(gz_path.read_bytes())
    assert index["meta"]["compressed"] is True
    assert index["meta"]["phones_indexed"] == 1
