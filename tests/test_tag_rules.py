from app.services.tag_rules import (
    DEFAULT_TAG_RULES,
    TagRule,
    evaluate_tags_for_row,
    get_tag_rules,
    hydrate_tag_rules,
    normalize_tags_field,
    rules_from_form,
    save_tag_rules,
)
import pytest


class _FakeCache:
    def __init__(self) -> None:
        self.payload: list[dict] | None = None

    async def get_tag_rules(self) -> list[dict] | None:
        return self.payload

    async def save_tag_rules(self, payload: list[dict]) -> None:
        self.payload = payload


def test_normalize_tags_field() -> None:
    assert normalize_tags_field("vip доволен") == "#vip #доволен"
    assert normalize_tags_field("#nik1 #nik2 #nik3") == "#nik1 #nik2 #nik3"
    assert normalize_tags_field("#vip, #vip #деньрождения") == "#vip #деньрождения"
    assert normalize_tags_field("") is None


def test_normalize_tags_field_accepts_ai_list_value() -> None:
    assert normalize_tags_field(["#vip", "#постоянный_клиент", "#8марта"]) == (
        "#vip #постоянный_клиент #8марта"
    )
    assert normalize_tags_field("['#vip', '#постоянный_клиент', '#8марта']") == (
        "#vip #постоянный_клиент #8марта"
    )
    assert normalize_tags_field("##vip #vip") == "#vip"


def test_evaluate_vip_from_avg_check() -> None:
    tags, reasons = evaluate_tags_for_row({"Средний чек": 20000, "Всего заказов": 1})
    assert "#vip" in (tags or "")
    assert "#vip" in reasons


def test_evaluate_postoyanny_from_orders() -> None:
    tags, reasons = evaluate_tags_for_row({"Всего заказов": 5})
    assert "#постоянный" in (tags or "")
    assert "5 заказов" in reasons["#постоянный"]


def test_rules_from_form_updates_description() -> None:
    key = DEFAULT_TAG_RULES[0].key
    rules = rules_from_form(
        {
            f"rule_{key}_enabled": "on",
            f"rule_{key}_tag": "#постоянный",
            f"rule_{key}_title": "Постоянный",
            f"rule_{key}_description": "Новое правило: 3+ заказа",
            f"rule_{key}_threshold": "3",
        }
    )
    assert rules[0].description == "Новое правило: 3+ заказа"
    assert rules[0].threshold == 3


def test_rules_from_form_adds_custom_tag() -> None:
    keys = ",".join(r.key for r in DEFAULT_TAG_RULES)
    rules = rules_from_form(
        {
            "rule_keys": keys,
            "new_tag": "#корпоратив",
            "new_title": "Корпоратив",
            "new_description": "Юрлица и ИП",
            "new_rule_type": "text_keywords",
            "new_keywords": "ооо, ип",
            "new_enabled": "on",
        }
    )
    custom = [r for r in rules if r.key.startswith("custom_")]
    assert len(custom) == 1
    assert custom[0].tag == "#корпоратив"
    assert custom[0].keywords == ["ооо", "ип"]
    assert custom[0].enabled is True


def test_rules_from_form_deletes_custom_tag() -> None:
    custom_rule = TagRule(
        key="custom_test",
        tag="#тест",
        title="Тест",
        description="Удаляем",
        rule_type="text_keywords",
        keywords=["тест"],
    )
    keys = "custom_test," + ",".join(r.key for r in DEFAULT_TAG_RULES)
    import asyncio

    async def _run() -> list:
        cache = _FakeCache()
        await save_tag_rules(cache, list(DEFAULT_TAG_RULES) + [custom_rule])  # type: ignore[arg-type]
        return rules_from_form(
            {
                "rule_keys": keys,
                "rule_custom_test_enabled": "on",
                "rule_custom_test_tag": "#тест",
                "rule_custom_test_title": "Тест",
                "rule_custom_test_description": "Удаляем",
                "rule_custom_test_rule_type": "text_keywords",
                "rule_custom_test_keywords": "тест",
                "rule_custom_test_delete": "on",
            }
        )

    rules = asyncio.run(_run())
    assert "custom_test" not in {r.key for r in rules}
    asyncio.run(save_tag_rules(_FakeCache(), list(DEFAULT_TAG_RULES)))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_hydrate_keeps_custom_rules() -> None:
    cache = _FakeCache()
    custom = {
        "key": "custom_korp",
        "tag": "#корпоратив",
        "title": "Корпоратив",
        "description": "Юрлица",
        "rule_type": "text_keywords",
        "enabled": True,
        "threshold": None,
        "keywords": ["ооо"],
        "sources": ["orders", "messenger"],
    }
    cache.payload = [r.to_dict() for r in DEFAULT_TAG_RULES] + [custom]
    await hydrate_tag_rules(cache)  # type: ignore[arg-type]
    keys = {r.key for r in get_tag_rules()}
    assert "custom_korp" in keys
    assert len(get_tag_rules()) == len(DEFAULT_TAG_RULES) + 1
    await save_tag_rules(cache, list(DEFAULT_TAG_RULES))  # type: ignore[arg-type]
