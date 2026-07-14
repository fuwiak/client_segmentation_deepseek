-- Схема Postgres для персистентности данных CRM (фаза 1 → фаза 2).

CREATE TABLE IF NOT EXISTS sync_metadata (
    id              TEXT PRIMARY KEY DEFAULT 'current',
    source          TEXT NOT NULL DEFAULT 'moysklad',
    schema_version  INTEGER,
    api_cp_total    INTEGER,
    api_orders_total INTEGER,
    max_counterparties INTEGER DEFAULT 0,
    max_orders      INTEGER DEFAULT 0,
    positions_loaded BOOLEAN NOT NULL DEFAULT FALSE,
    workbook_key    TEXT,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS customers (
    id                      TEXT PRIMARY KEY,
    moysklad_id             TEXT,
    name                    TEXT,
    phone                   TEXT,
    email                   TEXT,
    status                  TEXT,
    sales_type              TEXT,
    sales_channel_type      TEXT,
    sales_channel           TEXT,
    average_check           NUMERIC(14, 2),
    last_order_date         TIMESTAMPTZ,
    total_orders            INTEGER,
    bonus_points            NUMERIC(14, 2),
    groups_text             TEXT,
    customer_or_recipient   TEXT,
    gender                  TEXT,
    telegram_nick           TEXT,
    tags                    TEXT,
    summary                 TEXT,
    actual_address          TEXT,
    actual_address_comment  TEXT,
    counterparty_type       TEXT,
    code                    TEXT,
    external_code           TEXT,
    full_name               TEXT,
    last_name               TEXT,
    first_name              TEXT,
    middle_name             TEXT,
    legal_address           TEXT,
    legal_address_comment   TEXT,
    inn                     TEXT,
    kpp                     TEXT,
    okpo                    TEXT,
    fax                     TEXT,
    bik                     TEXT,
    bank                    TEXT,
    location                TEXT,
    corr_account            TEXT,
    bank_account            TEXT,
    discount_card           TEXT,
    ogrn                    TEXT,
    ogrnip                  TEXT,
    certificate_number      TEXT,
    certificate_date        TEXT,
    birth_date              DATE,
    archived_label          TEXT,
    comment_text            TEXT,
    last_order_status       TEXT,
    is_vip                  BOOLEAN,
    is_regular              BOOLEAN,
    ordered_positions_text  TEXT,
    source                  TEXT NOT NULL DEFAULT 'moysklad',
    row_data                JSONB NOT NULL DEFAULT '{}',
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers (phone);
CREATE INDEX IF NOT EXISTS idx_customers_moysklad_id ON customers (moysklad_id);
CREATE INDEX IF NOT EXISTS idx_customers_name ON customers (name);
CREATE INDEX IF NOT EXISTS idx_customers_last_order_date ON customers (last_order_date);
CREATE INDEX IF NOT EXISTS idx_customers_average_check ON customers (average_check);
CREATE INDEX IF NOT EXISTS idx_customers_sales_type ON customers (sales_type);
CREATE INDEX IF NOT EXISTS idx_customers_source ON customers (source);

CREATE TABLE IF NOT EXISTS orders (
    id                  TEXT PRIMARY KEY,
    moysklad_id         TEXT,
    order_number        TEXT,
    customer_name       TEXT,
    moysklad_agent_id   TEXT,
    agent_phone         TEXT,
    order_date          TIMESTAMPTZ,
    amount              NUMERIC(14, 2),
    status              TEXT,
    comment_text        TEXT,
    sales_channel       TEXT,
    positions_text      TEXT,
    positions           JSONB NOT NULL DEFAULT '[]',
    source              TEXT NOT NULL DEFAULT 'moysklad',
    row_data            JSONB NOT NULL DEFAULT '{}',
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_moysklad_id ON orders (moysklad_id);
CREATE INDEX IF NOT EXISTS idx_orders_agent_id ON orders (moysklad_agent_id);
CREATE INDEX IF NOT EXISTS idx_orders_order_date ON orders (order_date);
CREATE INDEX IF NOT EXISTS idx_orders_amount ON orders (amount);
CREATE INDEX IF NOT EXISTS idx_orders_customer_name ON orders (customer_name);

CREATE TABLE IF NOT EXISTS segmentation_snapshots (
    workbook_key    TEXT PRIMARY KEY,
    results         JSONB NOT NULL DEFAULT '[]',
    meta            JSONB NOT NULL DEFAULT '{}',
    saved_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_segmentation_saved_at ON segmentation_snapshots (saved_at DESC);

CREATE TABLE IF NOT EXISTS auxiliary_cache (
    cache_key   TEXT PRIMARY KEY,
    payload     JSONB NOT NULL DEFAULT '{}',
    saved_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
