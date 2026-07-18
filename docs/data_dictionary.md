# Data dictionary

All data is simulated by `src/growth_analytics/simulate.py` and written to `data/raw/` as
parquet. The warehouse (`data/warehouse.duckdb`) is rebuilt from `sql/*.sql`.

## Raw tables

### users
One row per signup.

| column | type | notes |
|---|---|---|
| user_id | int | primary key |
| signup_ts | timestamp | |
| signup_date | date | |
| acquisition_channel | text | organic, paid_social, search, referral, influencer |
| platform | text | ios, android, web |
| region | text | North America, Europe, LATAM, APAC |
| device_tier | text | high, mid, low (Android), desktop (web) |
| age_band | text | 18-24, 25-34, 35-44, 45-54, 55+ |

### events
Raw event log, one row per event (about 5.8M rows).

| column | type | notes |
|---|---|---|
| user_id | int | |
| event_ts | timestamp | |
| event_name | text | see below |
| event_props | text (JSON) | only set for `onboarding_step` (`{"step": n}`) and `subscription_start` (`{"plan": ...}`) |

Event names:

- `signup`, `onboarding_step`, `onboarding_complete`
- `app_open` (one per session), `workout_started`, `workout_completed`, `app_crash`
- `paywall_view`, `trial_start`
- `subscription_start`, `subscription_renewal`, `subscription_cancel` (billing events, not user activity)

### subscriptions
One row per paid subscription.

| column | type | notes |
|---|---|---|
| subscription_id | int | primary key |
| user_id | int | |
| plan | text | monthly ($12.99) or annual ($79.99) |
| list_price_usd | float | |
| store | text | app_store, play_store, web_stripe |
| trial_start_date | date | 7-day free trial before the first charge |
| start_date | date | first paid day |
| cancel_date | date | day auto-renew was switched off, null if still renewing |
| end_date | date | last day of paid access, null if not cancelled |
| status | text | active, cancelled (access continues to end_date), expired |

### charges
One row per payment.

| column | type | notes |
|---|---|---|
| charge_id | int | |
| subscription_id | int | |
| user_id | int | |
| charge_date | date | |
| charge_type | text | new or renewal |
| gross_usd | float | list price |
| net_usd | float | after store fees (15% app stores, 3% web) |

### marketing_spend
One row per paid channel per day.

| column | type |
|---|---|
| date | date |
| channel | text (paid_social, search, influencer) |
| spend_usd | float |
| impressions | int |
| clicks | int |

### experiment_exposures
One row per user per experiment, as logged by the client.

| column | type | notes |
|---|---|---|
| user_id | int | |
| experiment | text | onboarding_v2 or smart_reminders |
| variant | text | control or treatment |
| exposed_at | timestamp | |

## Main models

| table | grain | built in |
|---|---|---|
| fct_user_daily | user x day with any activity | 02_core.sql |
| dim_users | user | 02_core.sql |
| mart_engagement_daily | day | 03_engagement.sql |
| mart_engagement_monthly | month | 03_engagement.sql |
| mart_funnel | signup month x channel x platform | 04_funnel_retention.sql |
| mart_activation | user (cohorts with a complete D30 window) | 04_funnel_retention.sql |
| mart_cohort_retention | signup month x week since signup | 04_funnel_retention.sql |
| mart_retention_curve | channel x day n | 04_funnel_retention.sql |
| mart_mrr_monthly | month | 05_revenue.sql |
| mart_channel_economics | channel | 05_revenue.sql |
| mart_channel_daily | paid channel x day | 05_revenue.sql |
| mart_exp_onboarding | exposed user | 06_experiments.sql |
| mart_exp_reminders | exposed user | 06_experiments.sql |
| mart_churn_features | monthly subscription | 07_churn_features.sql |
