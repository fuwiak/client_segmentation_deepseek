"""Пояснения для AI-тегов клиента (tooltip при наведении)."""

from __future__ import annotations

from typing import Any


def _orders_count(row: dict[str, Any]) -> int:
    try:
        return int(row.get("Всего заказов") or row.get("_orders_count") or 0)
    except (TypeError, ValueError):
        return 0


def _avg_check(row: dict[str, Any]) -> float:
    try:
        return float(row.get("Средний чек") or 0)
    except (TypeError, ValueError):
        return 0.0


def _order_comments(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for order in row.get("_orders_context") or []:
        comment = str(order.get("Комментарий") or order.get("Описание") or "").strip()
        if comment:
            parts.append(comment)
    return " ".join(parts).lower()


def _messenger_text(row: dict[str, Any]) -> str:
    return " ".join(
        str(m.get("text") or "") for m in row.get("_messenger_context") or []
    ).lower()


def _snippet(text: str, needle: str, *, width: int = 60) -> str | None:
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return None
    start = max(0, idx - 20)
    end = min(len(text), idx + len(needle) + width)
    snippet = text[start:end].strip()
    if len(snippet) > 90:
        snippet = snippet[:87] + "…"
    return snippet


def explain_single_tag(tag: str, row: dict[str, Any]) -> str | None:
    key = tag.lstrip("#").lower().replace("ё", "е")
    orders = _orders_count(row)
    avg = _avg_check(row)
    comments = _order_comments(row)
    messages = _messenger_text(row)

    if key in {"постоянный", "postoyannyj"}:
        if orders > 2:
            return f"Постоянный клиент: {orders} заказов (больше 2)"
        return None

    if key == "vip":
        if avg >= 15000:
            return f"VIP: средний чек {avg:,.0f} ₽ (от 15 000 ₽)".replace(",", " ")
        for order in row.get("_orders_context") or []:
            try:
                amount = float(order.get("Сумма") or 0)
            except (TypeError, ValueError):
                amount = 0
            if amount >= 15000:
                num = order.get("№") or order.get("Номер") or "—"
                return f"VIP: заказ №{num} на {amount:,.0f} ₽".replace(",", " ")
        return None

    if key in {"деньрождения", "denrozhdeniya", "деньрождение"}:
        for word in ("день рождения", "др", "birthday"):
            hit = _snippet(comments, word) or _snippet(messages, word)
            if hit:
                return f"День рождения: «{hit}»"
        return None

    if key in {"8марта", "8marta"}:
        for word in ("8 марта", "8марта"):
            hit = _snippet(comments, word) or _snippet(messages, word)
            if hit:
                return f"8 марта: «{hit}»"
        return None

    if key == "доволен":
        if any(w in messages for w in ("спасибо", "отлично", "супер", "класс")):
            hit = next(
                (w for w in ("спасибо", "отлично", "супер", "класс") if w in messages),
                None,
            )
            return f"Доволен: в переписке («{hit}» и позитивный тон)"
        return None

    if key == "проблемный":
        if any(w in messages for w in ("жалоб", "плох", "разочар", "верните")):
            hit = next(
                (
                    w
                    for w in ("жалоб", "плох", "разочар", "верните")
                    if w in messages
                ),
                None,
            )
            return f"Проблемный: в переписке («{hit}»)"
        return None

    if key in {"свадьба", "svadba"}:
        hit = _snippet(comments, "свадьб") or _snippet(messages, "свадьб")
        if hit:
            return f"Свадьба: «{hit}»"
        return None

    return None


def explain_tags_for_row(row: dict[str, Any]) -> dict[str, str]:
    """Вернуть пояснение для каждого тега в поле «Теги»."""
    stored = row.get("_ai_tag_reasons") or {}
    reasons: dict[str, str] = {str(k): str(v) for k, v in stored.items()}
    tags_raw = str(row.get("Теги") or "").strip()
    if not tags_raw:
        return reasons

    refs = row.get("_ai_refs") or {}
    tags_ref = refs.get("Теги")
    reasoning = str(row.get("_reasoning") or "").strip()
    fallback = str(tags_ref or reasoning or "Тег добавлен AI по данным клиента и заказов")

    for token in tags_raw.split():
        if not token or token in reasons:
            continue
        explained = explain_single_tag(token, row)
        reasons[token] = explained or fallback

    return reasons
