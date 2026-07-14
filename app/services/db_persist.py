"""Фоновая персистентность данных из Redis в PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db.columns import (
    CUSTOMER_DB_COLUMNS,
    ORDER_DB_COLUMNS,
    customer_row_to_db,
    order_row_to_db,
)

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
LATEST_SEGMENTATION_KEY = "latest"
CUSTOMER_JSONB_COLUMNS = frozenset({"row_data"})
ORDER_JSONB_COLUMNS = frozenset({"row_data", "positions"})


class DbPersistService:
    """Сохраняет снимки DataHub в Postgres; подгружает при промахе Redis."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: Any | None = None
        self._init_lock = asyncio.Lock()
        self._schema_ready = False

    @property
    def enabled(self) -> bool:
        return bool(
            self._settings.db_persist_enabled and self._settings.database_url.strip()
        )

    async def _ensure_pool(self) -> Any | None:
        if not self.enabled:
            return None
        if self._pool is not None:
            return self._pool
        async with self._init_lock:
            if self._pool is not None:
                return self._pool
            try:
                import asyncpg

                dsn = self._settings.database_url.strip()
                self._pool = await asyncpg.create_pool(
                    dsn,
                    min_size=1,
                    max_size=5,
                    command_timeout=120,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Postgres pool unavailable: %s", exc)
                return None
        return self._pool

    async def init_schema(self) -> bool:
        pool = await self._ensure_pool()
        if not pool:
            return False
        if self._schema_ready:
            return True
        async with self._init_lock:
            if self._schema_ready:
                return True
            try:
                ddl = SCHEMA_PATH.read_text(encoding="utf-8")
                async with pool.acquire() as conn:
                    await conn.execute(ddl)
                self._schema_ready = True
                logger.info("Postgres schema initialized")
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("Postgres schema init failed: %s", exc)
                return False

    async def ping(self) -> bool:
        pool = await self._ensure_pool()
        if not pool:
            return False
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def persist_moysklad_sync(self, payload: dict[str, Any]) -> None:
        if not await self.init_schema():
            return
        pool = await self._ensure_pool()
        if not pool:
            return

        counterparty_rows = payload.get("counterparty_rows") or []
        order_rows = payload.get("order_rows") or []
        source = str(payload.get("source") or "moysklad")

        customer_records = [
            customer_row_to_db(row, source=source) for row in counterparty_rows
        ]
        order_records = [order_row_to_db(row, source=source) for row in order_rows]

        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("DELETE FROM orders")
                    await conn.execute("DELETE FROM customers")

                    if customer_records:
                        await self._insert_customers(conn, customer_records)
                    if order_records:
                        await self._insert_orders(conn, order_records)

                    workbook_key = (
                        f"moysklad:{len(counterparty_rows)}:{len(order_rows)}"
                    )
                    await conn.execute(
                        """
                        INSERT INTO sync_metadata (
                            id, source, schema_version, api_cp_total, api_orders_total,
                            max_counterparties, max_orders, positions_loaded, workbook_key,
                            synced_at, updated_at
                        ) VALUES (
                            'current', $1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW()
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            source = EXCLUDED.source,
                            schema_version = EXCLUDED.schema_version,
                            api_cp_total = EXCLUDED.api_cp_total,
                            api_orders_total = EXCLUDED.api_orders_total,
                            max_counterparties = EXCLUDED.max_counterparties,
                            max_orders = EXCLUDED.max_orders,
                            positions_loaded = EXCLUDED.positions_loaded,
                            workbook_key = EXCLUDED.workbook_key,
                            synced_at = NOW(),
                            updated_at = NOW()
                        """,
                        source,
                        payload.get("schema_version"),
                        payload.get("api_cp_total"),
                        payload.get("api_orders_total"),
                        payload.get("max_counterparties") or 0,
                        payload.get("max_orders") or 0,
                        bool(payload.get("positions_loaded")),
                        workbook_key,
                    )
            logger.info(
                "Persisted to Postgres: %s customers, %s orders",
                len(customer_records),
                len(order_records),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres moysklad persist failed: %s", exc)

    async def _insert_customers(self, conn: Any, records: list[dict[str, Any]]) -> None:
        await self._insert_rows(conn, "customers", CUSTOMER_DB_COLUMNS, CUSTOMER_JSONB_COLUMNS, records)

    async def _insert_orders(self, conn: Any, records: list[dict[str, Any]]) -> None:
        await self._insert_rows(conn, "orders", ORDER_DB_COLUMNS, ORDER_JSONB_COLUMNS, records)

    async def _insert_rows(
        self,
        conn: Any,
        table: str,
        cols: list[str],
        jsonb_cols: frozenset[str],
        records: list[dict[str, Any]],
    ) -> None:
        placeholders = ", ".join(
            f"${i + 1}::jsonb" if col in jsonb_cols else f"${i + 1}"
            for i, col in enumerate(cols)
        )
        col_list = ", ".join(cols)
        sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
        rows = [
            tuple(self._bind_column(col, record.get(col), jsonb_cols) for col in cols)
            for record in records
        ]
        await conn.executemany(sql, rows)

    @staticmethod
    def _bind_column(col: str, value: Any, jsonb_cols: frozenset[str]) -> Any:
        if value is None:
            return None
        if col in jsonb_cols or isinstance(value, (dict, list)):
            return json.dumps(value, default=str, ensure_ascii=False)
        return value

    async def load_moysklad_sync(self) -> dict[str, Any] | None:
        if not await self.init_schema():
            return None
        pool = await self._ensure_pool()
        if not pool:
            return None
        try:
            async with pool.acquire() as conn:
                meta = await conn.fetchrow(
                    "SELECT * FROM sync_metadata WHERE id = 'current'"
                )
                if not meta:
                    return None
                customer_rows = await conn.fetch(
                    "SELECT row_data FROM customers ORDER BY name NULLS LAST"
                )
                order_rows = await conn.fetch(
                    "SELECT row_data FROM orders ORDER BY order_date DESC NULLS LAST"
                )
            if not customer_rows:
                return None
            return {
                "schema_version": meta["schema_version"],
                "counterparty_rows": [dict(r["row_data"]) for r in customer_rows],
                "order_rows": [dict(r["row_data"]) for r in order_rows],
                "api_cp_total": meta["api_cp_total"],
                "api_orders_total": meta["api_orders_total"],
                "max_counterparties": meta["max_counterparties"] or 0,
                "max_orders": meta["max_orders"] or 0,
                "positions_loaded": bool(meta["positions_loaded"]),
                "source": meta["source"] or "moysklad",
                "from_postgres": True,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres moysklad load failed: %s", exc)
            return None

    async def persist_segmentation_results(self, payload: dict[str, Any]) -> None:
        if not await self.init_schema():
            return
        pool = await self._ensure_pool()
        if not pool:
            return
        workbook_key = str(payload.get("workbook_key") or LATEST_SEGMENTATION_KEY)
        results = payload.get("results") or []
        meta = payload.get("meta") or {}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for key in {workbook_key, LATEST_SEGMENTATION_KEY}:
                        await conn.execute(
                            """
                            INSERT INTO segmentation_snapshots (workbook_key, results, meta, saved_at)
                            VALUES ($1, $2::jsonb, $3::jsonb, NOW())
                            ON CONFLICT (workbook_key) DO UPDATE SET
                                results = EXCLUDED.results,
                                meta = EXCLUDED.meta,
                                saved_at = NOW()
                            """,
                            key,
                            json.dumps(results, default=str),
                            json.dumps(meta, default=str),
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres segmentation persist failed: %s", exc)

    async def load_segmentation_results(
        self, workbook_key: str | None = None
    ) -> dict[str, Any] | None:
        if not await self.init_schema():
            return None
        pool = await self._ensure_pool()
        if not pool:
            return None
        keys = [workbook_key, LATEST_SEGMENTATION_KEY] if workbook_key else [
            LATEST_SEGMENTATION_KEY
        ]
        try:
            async with pool.acquire() as conn:
                for key in keys:
                    if not key:
                        continue
                    row = await conn.fetchrow(
                        """
                        SELECT workbook_key, results, meta
                        FROM segmentation_snapshots
                        WHERE workbook_key = $1
                        """,
                        key,
                    )
                    if row:
                        results = row["results"]
                        meta = row["meta"]
                        return {
                            "workbook_key": row["workbook_key"],
                            "results": list(results) if results else [],
                            "meta": dict(meta) if meta else {},
                            "from_postgres": True,
                        }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres segmentation load failed: %s", exc)
        return None

    async def persist_auxiliary(self, cache_key: str, payload: Any) -> None:
        if not await self.init_schema():
            return
        pool = await self._ensure_pool()
        if not pool:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO auxiliary_cache (cache_key, payload, saved_at)
                    VALUES ($1, $2::jsonb, NOW())
                    ON CONFLICT (cache_key) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        saved_at = NOW()
                    """,
                    cache_key,
                    json.dumps(payload, default=str),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres auxiliary persist failed (%s): %s", cache_key, exc)

    async def load_auxiliary(self, cache_key: str) -> Any | None:
        if not await self.init_schema():
            return None
        pool = await self._ensure_pool()
        if not pool:
            return None
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT payload FROM auxiliary_cache WHERE cache_key = $1",
                    cache_key,
                )
                if row:
                    return row["payload"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres auxiliary load failed (%s): %s", cache_key, exc)
        return None


_db_persist: DbPersistService | None = None


def get_db_persist(settings: Settings | None = None) -> DbPersistService:
    global _db_persist
    if _db_persist is None:
        from app.config import get_settings

        _db_persist = DbPersistService(settings or get_settings())
    return _db_persist
