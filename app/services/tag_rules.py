"""Правила присвоения AI-тегов — настраиваемые и сохраняемые в кэше."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.cache import CacheService


@dataclass
class TagRule:
    key: str
    tag: str
    title: str
    description: str
    rule_type: str
    enabled: bool = True
    threshold: float | None = None
    keywords: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=lambda: ["orders", "messenger"])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TagRule:
        return cls(
            key=str(data["key"]),
            tag=str(data.get("tag") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            rule_type=str(data.get("rule_type") or "text_keywords"),
            enabled=bool(data.get("enabled", True)),
            threshold=float(data["threshold"]) if data.get("threshold") not in (None, "") else None,
            keywords=[str(k).strip() for k in (data.get("keywords") or []) if str(k).strip()],
            sources=[str(s) for s in (data.get("sources") or ["orders", "messenger"])],
        )


DEFAULT_TAG_RULES: list[TagRule] = [
    TagRule(
        key="postoyanny",
        tag="#постоянный",
        title="Постоянный клиент",
        description="Более 2 заказов в истории",
        rule_type="orders_min",
        threshold=2,
        sources=["orders"],
    ),
    TagRule(
        key="vip_avg",
        tag="#vip",
        title="VIP по среднему чеку",
        description="Средний чек от 15 000 ₽",
        rule_type="avg_check_min",
        threshold=15000,
        sources=["orders"],
    ),
    TagRule(
        key="vip_order",
        tag="#vip",
        title="VIP по сумме заказа",
        description="Хотя бы один заказ от 15 000 ₽",
        rule_type="order_amount_min",
        threshold=15000,
        sources=["orders"],
    ),
    TagRule(
        key="denrozhdeniya",
        tag="#деньрождения",
        title="День рождения",
        description="В комментарии к заказу или переписке упоминается день рождения",
        rule_type="text_keywords",
        keywords=["день рождения", "др", "birthday"],
    ),
    TagRule(
        key="8marta",
        tag="#8марта",
        title="8 марта",
        description="В данных клиента есть упоминание 8 марта",
        rule_type="text_keywords",
        keywords=["8 марта", "8марта"],
    ),
    TagRule(
        key="dovolen",
        tag="#доволен",
        title="Доволен",
        description="В переписке позитивный отзыв",
        rule_type="messenger_positive",
        keywords=["спасибо", "отлично", "супер", "класс"],
        sources=["messenger"],
    ),
    TagRule(
        key="problemny",
        tag="#проблемный",
        title="Проблемный",
        description="В переписке жалоба или недовольство",
        rule_type="messenger_negative",
        keywords=["жалоб", "плох", "разочар", "верните"],
        sources=["messenger"],
    ),
    TagRule(
        key="svadba",
        tag="#свадьба",
        title="Свадьба",
        description="В заказе или переписке упоминается свадьба",
        rule_type="text_keywords",
        keywords=["свадьб"],
    ),
]

RULE_TYPE_OPTIONS: list[tuple[str, str]] = [
    ("text_keywords", "Ключевые слова в заказе / переписке"),
    ("messenger_positive", "Позитив в переписке"),
    ("messenger_negative", "Негатив в переписке"),
    ("orders_min", "Мин. число заказов"),
    ("avg_check_min", "Мин. средний чек"),
    ("order_amount_min", "Мин. сумма одного заказа"),
]

NUMERIC_RULE_TYPES = {"orders_min", "avg_check_min", "order_amount_min"}

_rules: list[TagRule] = [TagRule.from_dict(r.to_dict()) for r in DEFAULT_TAG_RULES]


def is_custom_rule(rule: TagRule) -> bool:
    return rule.key.startswith("custom_")


def get_tag_rules() -> list[TagRule]:
    return list(_rules)


def get_tag_rule_map() -> dict[str, TagRule]:
    return {r.key: r for r in _rules}


def _normalize_tag(tag: str) -> str:
    tag = tag.strip()
    if not tag:
        return ""
    return tag if tag.startswith("#") else f"#{tag}"


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


def _snippet(text: str, needle: str, *, width: int = 50) -> str | None:
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return None
    start = max(0, idx - 15)
    end = min(len(text), idx + len(needle) + width)
    snippet = text[start:end].strip()
    if len(snippet) > 80:
        snippet = snippet[:77] + "…"
    return snippet


def _match_rule(rule: TagRule, row: dict[str, Any]) -> str | None:
    comments = _order_comments(row)
    messages = _messenger_text(row)
    orders = _orders_count(row)
    avg = _avg_check(row)
    threshold = float(rule.threshold or 0)

    if rule.rule_type == "orders_min":
        if orders > threshold:
            return f"{orders} заказов"
        return None

    if rule.rule_type == "avg_check_min":
        if avg >= threshold:
            return f"средний чек {avg:,.0f} ₽".replace(",", " ")
        return None

    if rule.rule_type == "order_amount_min":
        for order in row.get("_orders_context") or []:
            try:
                amount = float(order.get("Сумма") or 0)
            except (TypeError, ValueError):
                amount = 0
            if amount >= threshold:
                num = order.get("№") or order.get("Номер") or "—"
                return f"заказ №{num} на {amount:,.0f} ₽".replace(",", " ")
        return None

    if rule.rule_type == "messenger_positive":
        if "messenger" not in rule.sources:
            return None
        for word in rule.keywords:
            if word.lower() in messages:
                return f"в переписке: «{word}»"
        return None

    if rule.rule_type == "messenger_negative":
        if "messenger" not in rule.sources:
            return None
        for word in rule.keywords:
            if word.lower() in messages:
                return f"в переписке: «{word}»"
        return None

    if rule.rule_type == "text_keywords":
        for word in rule.keywords:
            if "orders" in rule.sources:
                hit = _snippet(comments, word)
                if hit:
                    return f"в заказе: «{hit}»"
            if "messenger" in rule.sources:
                hit = _snippet(messages, word)
                if hit:
                    return f"в переписке: «{hit}»"
        return None

    return None


def evaluate_tags_for_row(
    row: dict[str, Any],
    rules: list[TagRule] | None = None,
) -> tuple[str | None, dict[str, str]]:
    """Вернуть строку тегов и пояснения по каждому тегу."""
    active_rules = rules or get_tag_rules()
    tags: list[str] = []
    reasons: dict[str, str] = {}
    for rule in active_rules:
        if not rule.enabled:
            continue
        detail = _match_rule(rule, row)
        if not detail:
            continue
        tag = _normalize_tag(rule.tag)
        if tag not in tags:
            tags.append(tag)
        reasons[tag] = f"{rule.description} ({detail})"
    return (" ".join(tags) if tags else None, reasons)


def rule_label(rule: TagRule) -> str:
    labels = {
        "orders_min": "Мин. число заказов",
        "avg_check_min": "Мин. средний чек, ₽",
        "order_amount_min": "Мин. сумма заказа, ₽",
        "text_keywords": "Ключевые слова",
        "messenger_positive": "Позитив в переписке",
        "messenger_negative": "Негатив в переписке",
    }
    return labels.get(rule.rule_type, rule.rule_type)


async def hydrate_tag_rules(cache: CacheService) -> None:
    global _rules
    raw = await cache.get_tag_rules()
    if not raw:
        return
    by_key = {str(r["key"]): TagRule.from_dict(r) for r in raw}
    merged: list[TagRule] = []
    default_keys = {d.key for d in DEFAULT_TAG_RULES}
    for default in DEFAULT_TAG_RULES:
        merged.append(by_key.get(default.key, default))
    for key, rule in by_key.items():
        if key not in default_keys:
            merged.append(rule)
    _rules = merged


async def save_tag_rules(cache: CacheService, rules: list[TagRule]) -> None:
    global _rules
    _rules = rules
    await cache.save_tag_rules([r.to_dict() for r in rules])


def _slug_from_tag(tag: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", tag.lstrip("#").lower().replace("ё", "е"))
    return slug.strip("_") or "tag"


def _unique_custom_key(tag: str, used: set[str]) -> str:
    base = f"custom_{_slug_from_tag(tag)}"
    key = base
    n = 2
    while key in used:
        key = f"{base}_{n}"
        n += 1
    return key


def _sources_for_type(rule_type: str) -> list[str]:
    if rule_type in {"messenger_positive", "messenger_negative"}:
        return ["messenger"]
    if rule_type in NUMERIC_RULE_TYPES:
        return ["orders"]
    return ["orders", "messenger"]


def _parse_rule_from_form(form: dict[str, str], key: str, base: TagRule) -> TagRule | None:
    if form.get(f"rule_{key}_delete") == "on":
        return None
    keywords_raw = form.get(f"rule_{key}_keywords", "")
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    threshold_raw = form.get(f"rule_{key}_threshold", "").strip()
    threshold = float(threshold_raw) if threshold_raw else None
    rule_type = form.get(f"rule_{key}_rule_type", base.rule_type).strip() or base.rule_type
    tag = _normalize_tag(form.get(f"rule_{key}_tag", base.tag).strip() or base.tag)
    title = form.get(f"rule_{key}_title", base.title).strip() or base.title
    return TagRule(
        key=key,
        tag=tag,
        title=title,
        description=form.get(f"rule_{key}_description", base.description).strip() or base.description,
        rule_type=rule_type,
        enabled=form.get(f"rule_{key}_enabled") == "on",
        threshold=threshold if threshold is not None else base.threshold,
        keywords=keywords or base.keywords,
        sources=_sources_for_type(rule_type),
    )


def rules_from_form(form: dict[str, str]) -> list[TagRule]:
    current = get_tag_rule_map()
    keys_raw = form.get("rule_keys", "")
    keys = [k.strip() for k in keys_raw.split(",") if k.strip()]
    if not keys:
        keys = [r.key for r in get_tag_rules()]

    updated: list[TagRule] = []
    used_keys: set[str] = set()
    for key in keys:
        base = current.get(key)
        if not base:
            continue
        parsed = _parse_rule_from_form(form, key, base)
        if parsed:
            updated.append(parsed)
            used_keys.add(key)

    new_tag = _normalize_tag(form.get("new_tag", "").strip())
    if new_tag:
        new_type = form.get("new_rule_type", "text_keywords").strip() or "text_keywords"
        new_key = _unique_custom_key(new_tag, used_keys)
        keywords_raw = form.get("new_keywords", "")
        keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
        threshold_raw = form.get("new_threshold", "").strip()
        threshold = float(threshold_raw) if threshold_raw else None
        updated.append(
            TagRule(
                key=new_key,
                tag=new_tag,
                title=form.get("new_title", "").strip() or new_tag.lstrip("#"),
                description=form.get("new_description", "").strip()
                or f"Пользовательское правило для {new_tag}",
                rule_type=new_type,
                enabled=form.get("new_enabled") == "on",
                threshold=threshold,
                keywords=keywords,
                sources=_sources_for_type(new_type),
            )
        )
    return updated
