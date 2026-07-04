-- staging: typed views over the raw parquet files, one per source table.
-- Nothing is filtered here. {{ raw_dir }} is filled in by warehouse.py.

CREATE OR REPLACE VIEW stg_users AS
SELECT
    user_id,
    CAST(signup_ts   AS TIMESTAMP) AS signup_ts,
    CAST(signup_date AS DATE)      AS signup_date,
    acquisition_channel,
    platform,
    region,
    device_tier,
    age_band
FROM read_parquet('{{ raw_dir }}/users.parquet');


CREATE OR REPLACE VIEW stg_events AS
SELECT
    user_id,
    CAST(event_ts   AS TIMESTAMP) AS event_ts,
    CAST(event_ts   AS DATE)      AS event_date,
    CAST(event_name AS VARCHAR)   AS event_name,
    event_props
FROM read_parquet('{{ raw_dir }}/events.parquet');


CREATE OR REPLACE VIEW stg_subscriptions AS
SELECT
    subscription_id,
    user_id,
    plan,
    list_price_usd,
    store,
    CAST(trial_start_date AS DATE) AS trial_start_date,
    CAST(start_date       AS DATE) AS start_date,
    CAST(cancel_date      AS DATE) AS cancel_date,   -- auto-renew switched off
    CAST(end_date         AS DATE) AS end_date,      -- paid access actually ends
    status,
    -- normalise every plan to a monthly recurring amount (MRR)
    CASE plan WHEN 'annual' THEN list_price_usd / 12.0 ELSE list_price_usd END AS mrr_usd
FROM read_parquet('{{ raw_dir }}/subscriptions.parquet');


CREATE OR REPLACE VIEW stg_charges AS
SELECT
    charge_id,
    subscription_id,
    user_id,
    CAST(charge_date AS DATE) AS charge_date,
    charge_type,                 -- 'new' | 'renewal'
    gross_usd,
    net_usd                      -- after app-store / payment fees
FROM read_parquet('{{ raw_dir }}/charges.parquet');


CREATE OR REPLACE VIEW stg_marketing_spend AS
SELECT
    CAST(date AS DATE) AS spend_date,
    channel,
    spend_usd,
    impressions,
    clicks
FROM read_parquet('{{ raw_dir }}/marketing_spend.parquet');


CREATE OR REPLACE VIEW stg_experiment_exposures AS
SELECT
    user_id,
    experiment,
    variant,
    CAST(exposed_at AS TIMESTAMP) AS exposed_at
FROM read_parquet('{{ raw_dir }}/experiment_exposures.parquet');
