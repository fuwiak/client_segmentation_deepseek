"""Выгрузка AI-сегментов обратно в теги контрагентов Мой Склад."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.moysklad.client import MoySkladClientBase

CRM_TAG_PREFIX = "crm:"


@dataclass
class MoySkladPushResult:
    success: bool
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    message: str = ""


def counterparty_id_for_row(row: dict[str, Any]) -> str | None:
    ms_id = row.get("_moysklad_id")
    if ms_id:
        return str(ms_id)
    if row.get("_source") == "moysklad":
        uid = row.get("UUID")
        if uid:
            return str(uid)
    return None


def build_ai_tags(row: dict[str, Any]) -> list[str]:
    tags: list[str] = []

    groups = str(row.get("Группы") or "").strip()
    if groups:
        for part in re.split(r"[,/]", groups):
            token = part.strip()
            if token:
                tags.append(_as_crm_tag(token))

    for token in str(row.get("Теги") or "").split():
        cleaned = token.strip().lstrip("#").strip()
        if cleaned:
            tags.append(_as_crm_tag(cleaned))

    return _unique(tags)


def merge_counterparty_tags(
    existing: list[str] | None,
    row: dict[str, Any],
) -> list[str]:
    base = [str(tag) for tag in (existing or []) if str(tag).strip()]
    preserved = [
        tag
        for tag in base
        if not tag.lower().startswith(CRM_TAG_PREFIX)
    ]
    return _unique(preserved + build_ai_tags(row))


def _as_crm_tag(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    if normalized.lower().startswith(CRM_TAG_PREFIX):
        return normalized
    return f"{CRM_TAG_PREFIX}{normalized}"


def _unique(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        key = tag.lower()
        if not tag or key in seen:
            continue
        seen.add(key)
        result.append(tag)
    return result


async def push_segments_to_moysklad(
    client: MoySkladClientBase,
    results: list[dict[str, Any]],
) -> MoySkladPushResult:
    if not client.enabled:
        return MoySkladPushResult(
            success=False,
            message="Мой Склад не настроен (MOYSKLAD_API_TOKEN / MOYSKLAD_ENABLED)",
        )
    if not results:
        return MoySkladPushResult(
            success=False,
            message="Нет результатов сегментации для выгрузки",
        )

    updated = 0
    skipped = 0
    failed = 0
    errors: list[str] = []

    for row in results:
        counterparty_id = counterparty_id_for_row(row)
        if not counterparty_id:
            skipped += 1
            continue

        tags = merge_counterparty_tags(row.get("_moysklad_tags"), row)
        if not tags:
            skipped += 1
            continue

        try:
            await client.update_counterparty_groups(counterparty_id, tags)
            updated += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            name = row.get("Наименование") or counterparty_id
            errors.append(f"{name}: {exc}")
            if len(errors) >= 5:
                errors.append("…")
                break

    if failed and not updated:
        success = False
        message = f"Не удалось обновить теги ({failed} ошибок)"
    elif failed:
        success = True
        message = (
            f"Обновлено {updated} контрагентов, пропущено {skipped}, "
            f"ошибок {failed}"
        )
    else:
        success = True
        message = f"Теги отправлены в Мой Склад: {updated} контрагентов"
        if skipped:
            message += f", пропущено {skipped}"

    return MoySkladPushResult(
        success=success,
        updated=updated,
        skipped=skipped,
        failed=failed,
        errors=errors,
        message=message,
    )
