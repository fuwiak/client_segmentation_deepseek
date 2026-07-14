"""Импорт переписок из Telegram Data Export (result.json) и привязка к клиентам по телефону."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.messenger_store import _normalize_name, _normalize_phone, _normalize_tg

_PHONE_RE = re.compile(
    r"(?:\+?(?:7|8)|00?7)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
)
_EXPORT_PREFIX = "muner"


def normalize_export_phone(raw: str | None) -> str:
    """Единый ключ для сопоставления: последние 10 цифр российского номера."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if len(digits) == 11 and digits[0] == "7":
        return digits[1:]
    if len(digits) >= 10:
        return digits[-10:]
    return ""


def _extract_message_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
        return "".join(parts).strip()
    return ""


def _phones_in_text(text: str) -> set[str]:
    found: set[str] = set()
    for match in _PHONE_RE.findall(text):
        key = normalize_export_phone(match)
        if len(key) == 10:
            found.add(key)
    return found


def _phones_in_message(msg: dict[str, Any]) -> set[str]:
    phones: set[str] = set()
    raw_text = msg.get("text")
    if isinstance(raw_text, list):
        for part in raw_text:
            if isinstance(part, dict) and part.get("type") == "phone":
                key = normalize_export_phone(str(part.get("text") or ""))
                if len(key) == 10:
                    phones.add(key)
    text = _extract_message_text(raw_text)
    phones |= _phones_in_text(text)
    contact = msg.get("contact") or {}
    if contact.get("phone_number"):
        key = normalize_export_phone(str(contact["phone_number"]))
        if len(key) == 10:
            phones.add(key)
    return phones


def _parse_export_json(text: str) -> dict[str, Any]:
    stripped = text.lstrip("\ufeff").strip()
    if stripped.startswith(_EXPORT_PREFIX):
        stripped = "{" + stripped[len(_EXPORT_PREFIX) :]
    return json.loads(stripped)


def _message_direction(
    msg: dict[str, Any],
    *,
    business_user_id: int | None,
    business_names: set[str],
) -> str:
    from_name = str(msg.get("from") or "").strip().lower()
    from_id = str(msg.get("from_id") or "")
    if business_user_id and from_id == f"user{business_user_id}":
        return "out"
    if from_name and from_name in business_names:
        return "out"
    if "veresk" in from_name:
        return "out"
    return "in"


def build_export_index(data: dict[str, Any]) -> dict[str, Any]:
    """Собрать компактный индекс сообщений по телефону клиента."""
    personal = (data.get("personal_information") or {})
    business_user_id = personal.get("user_id")
    business_names = {
        _normalize_name(personal.get("first_name")),
        _normalize_name(personal.get("last_name")),
        _normalize_name(
            " ".join(
                part
                for part in [personal.get("first_name"), personal.get("last_name")]
                if part
            )
        ),
    }
    business_names.discard("")

    chats = [
        chat
        for chat in (data.get("chats") or {}).get("list") or []
        if chat.get("type") == "personal_chat"
    ]

    by_phone: dict[str, list[dict[str, Any]]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    by_username: dict[str, list[dict[str, Any]]] = {}
    phone_username: dict[str, str] = {}
    chats_with_phone = 0
    messages_total = 0

    for chat in chats:
        chat_id = chat.get("id")
        chat_name = str(chat.get("name") or "").strip()
        chat_username = _normalize_tg(chat.get("username"))
        phones: set[str] = set()
        if chat_name:
            phones |= _phones_in_text(chat_name)

        parsed_messages: list[dict[str, Any]] = []
        for msg in chat.get("messages") or []:
            if msg.get("type") != "message":
                continue
            text = _extract_message_text(msg.get("text"))
            if not text:
                continue
            phones |= _phones_in_message(msg)
            parsed_messages.append(
                {
                    "channel": "telegram",
                    "source": "telegram_export",
                    "direction": _message_direction(
                        msg,
                        business_user_id=business_user_id,
                        business_names=business_names,
                    ),
                    "text": text,
                    "sender": chat_username or str(msg.get("from") or chat_name or ""),
                    "username": chat_username,
                    "date": str(msg.get("date") or ""),
                    "chat_id": chat_id,
                    "chat_name": chat_name,
                }
            )

        if not parsed_messages:
            continue

        if not phones and chat_name:
            name_key = _normalize_name(chat_name)
            if name_key:
                bucket = by_name.setdefault(name_key, [])
                bucket.extend(parsed_messages)

        if phones:
            chats_with_phone += 1
            messages_total += len(parsed_messages)
            for phone in phones:
                bucket = by_phone.setdefault(phone, [])
                bucket.extend(parsed_messages)
                if chat_username:
                    phone_username[phone] = chat_username

        if chat_username:
            bucket = by_username.setdefault(chat_username, [])
            bucket.extend(parsed_messages)

    for phone, messages in by_phone.items():
        messages.sort(key=lambda m: m.get("date") or "")
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for msg in messages:
            key = f"{msg.get('date')}:{msg.get('text')}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(msg)
        by_phone[phone] = deduped

    for name, messages in by_name.items():
        messages.sort(key=lambda m: m.get("date") or "")
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for msg in messages:
            key = f"{msg.get('date')}:{msg.get('text')}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(msg)
        by_name[name] = deduped

    return {
        "meta": {
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "chats_total": len(chats),
            "chats_with_phone": chats_with_phone,
            "messages_total": messages_total,
            "phones_indexed": len(by_phone),
            "names_indexed": len(by_name),
            "usernames_indexed": len(by_username),
        },
        "by_phone": by_phone,
        "by_name": by_name,
        "by_username": by_username,
        "phone_username": phone_username,
    }



def parse_telegram_export_bytes(raw: bytes) -> dict[str, Any]:
    compressed = raw[:2] == b"\x1f\x8b"
    payload = gzip.decompress(raw) if compressed else raw
    text = payload.decode("utf-8")
    data = _parse_export_json(text)
    index = build_export_index(data)
    index["meta"]["file_size"] = len(raw)
    index["meta"]["file_hash"] = hashlib.sha256(raw).hexdigest()[:16]
    index["meta"]["compressed"] = compressed
    return index


def parse_telegram_export_file(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    raw_bytes = file_path.read_bytes()
    index = parse_telegram_export_bytes(raw_bytes)
    index["meta"]["source_path"] = str(file_path)
    return index


def tg_nick_for_row(index: dict[str, Any], row: dict[str, Any]) -> str | None:
    tg = _normalize_tg(row.get("ТГ ник"))
    if tg:
        return f"@{tg}"
    phone = normalize_export_phone(str(row.get("Телефон") or ""))
    if not phone:
        phone = _normalize_phone(str(row.get("Телефон") or ""))
    if phone:
        username = (index.get("phone_username") or {}).get(phone)
        if username:
            return f"@{username}"
    return None


def messages_for_row(index: dict[str, Any], row: dict[str, Any], *, limit: int = 50) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(items: list[dict[str, Any]] | None) -> None:
        for item in items or []:
            key = f"{item.get('date')}:{item.get('text')}"
            if key not in seen:
                seen.add(key)
                matched.append(item)

    phone = normalize_export_phone(str(row.get("Телефон") or ""))
    if not phone:
        phone = _normalize_phone(str(row.get("Телефон") or ""))
    if phone:
        _add((index.get("by_phone") or {}).get(phone))

    name = _normalize_name(row.get("Наименование"))
    if name:
        _add((index.get("by_name") or {}).get(name))

    tg = _normalize_tg(row.get("ТГ ник"))
    if tg:
        _add((index.get("by_username") or {}).get(tg))
        _add((index.get("by_name") or {}).get(tg))

    matched.sort(key=lambda m: m.get("date") or "")
    return matched[-limit:]


def tg_conversation_label(row: dict[str, Any]) -> str:
    msgs = row.get("_tg_export_context") or []
    if not msgs:
        return "—"
    count = len(msgs)
    last = str((msgs[-1] or {}).get("text") or "").replace("\n", " ").strip()
    if len(last) > 48:
        last = last[:45] + "…"
    return f"✓ {count} сообщ. · {last}" if last else f"✓ {count} сообщ."
