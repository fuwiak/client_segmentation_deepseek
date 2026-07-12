"""Пояснения для AI-тегов клиента (tooltip при наведении)."""

from __future__ import annotations

from typing import Any

from app.services.tag_rules import evaluate_tags_for_row, get_tag_rules


def explain_tags_for_row(row: dict[str, Any]) -> dict[str, str]:
    """Вернуть пояснение для каждого тега в поле «Теги»."""
    stored = row.get("_ai_tag_reasons") or {}
    reasons: dict[str, str] = {str(k): str(v) for k, v in stored.items()}
    tags_raw = str(row.get("Теги") or "").strip()
    if not tags_raw:
        return reasons

    _, evaluated = evaluate_tags_for_row(row)
    rule_by_tag = {_normalize_display_tag(r.tag): r for r in get_tag_rules()}

    refs = row.get("_ai_refs") or {}
    tags_ref = refs.get("Теги")
    reasoning = str(row.get("_reasoning") or "").strip()
    fallback = str(tags_ref or reasoning or "Тег добавлен AI по правилам ниже")

    for token in tags_raw.split():
        if not token or token in reasons:
            continue
        if token in evaluated:
            reasons[token] = evaluated[token]
            continue
        rule = rule_by_tag.get(token)
        if rule:
            reasons[token] = rule.description
        else:
            reasons[token] = fallback

    return reasons


def _normalize_display_tag(tag: str) -> str:
    tag = tag.strip()
    return tag if tag.startswith("#") else f"#{tag}"


def explain_single_tag(tag: str, row: dict[str, Any]) -> str | None:
    reasons = explain_tags_for_row({**row, "Теги": tag})
    return reasons.get(tag)
