"""Metric definitions checked on a tiny hand-made dataset."""

import duckdb
import pandas as pd
import pytest

from growth_analytics import config as C
from growth_analytics.warehouse import render, run_sql_file

PARAMS = {"raw_dir": "unused", "signup_start": "2025-01-01", "obs_end": "2025-03-31", "trial_days": "7",
          "exp2_pre_start": "2025-01-01", "exp2_pre_end": "2025-01-28", "exp2_start": "2025-01-29",
          "exp2_end": "2025-02-25"}


@pytest.fixture()
def con():
    c = duckdb.connect()
    users = pd.DataFrame({
        "user_id": [1, 2, 3],
        "signup_ts": pd.to_datetime(["2025-01-01 08:00", "2025-01-01 09:00", "2025-03-20 10:00"]),
        "signup_date": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-03-20"]).date,
        "acquisition_channel": ["organic", "search", "organic"],
        "platform": ["ios", "android", "ios"],
        "region": ["Europe"] * 3, "device_tier": ["high"] * 3, "age_band": ["25-34"] * 3,
    })
    ev = [
        # user 1: active day 0 and day 8 (inside the D7 window), one workout on day 8
        (1, "2025-01-01 08:00", "signup", None), (1, "2025-01-01 08:00", "app_open", None),
        (1, "2025-01-01 08:01", "onboarding_complete", None),
        (1, "2025-01-09 07:00", "app_open", None), (1, "2025-01-09 07:02", "workout_started", None),
        (1, "2025-01-09 07:30", "workout_completed", None),
        # user 2: active day 0, then only a billing event on day 8 (must not count as active)
        (2, "2025-01-01 09:00", "signup", None), (2, "2025-01-01 09:00", "app_open", None),
        (2, "2025-01-09 06:00", "subscription_start", '{"plan":"monthly"}'),
        # user 3: signs up late in the window, so D7 is not mature yet
        (3, "2025-03-20 10:00", "signup", None), (3, "2025-03-20 10:00", "app_open", None),
    ]
    events = pd.DataFrame(ev, columns=["user_id", "event_ts", "event_name", "event_props"])
    events["event_ts"] = pd.to_datetime(events["event_ts"])
    events["event_date"] = events["event_ts"].dt.date
    subs = pd.DataFrame({"subscription_id": [1], "user_id": [2], "plan": ["monthly"], "list_price_usd": [12.99],
                         "store": ["play_store"], "trial_start_date": [pd.Timestamp("2025-01-02").date()],
                         "start_date": [pd.Timestamp("2025-01-09").date()], "cancel_date": [None],
                         "end_date": [None], "status": ["active"], "mrr_usd": [12.99]})
    c.register("u", users)
    c.register("e", events)
    c.register("s", subs)
    c.execute("CREATE TABLE stg_users AS SELECT * FROM u")
    c.execute("CREATE TABLE stg_events AS SELECT * FROM e")
    c.execute("CREATE TABLE stg_subscriptions AS SELECT * REPLACE (CAST(cancel_date AS DATE) AS cancel_date, "
              "CAST(end_date AS DATE) AS end_date) FROM s")
    for f in ["02_core.sql", "03_engagement.sql", "04_funnel_retention.sql"]:
        run_sql_file(c, C.SQL_DIR / f, PARAMS)
    yield c
    c.close()


def test_render_rejects_unknown_placeholder():
    with pytest.raises(KeyError):
        render("SELECT '{{ nope }}'", PARAMS)


def test_user_daily_counts_and_billing_events_are_not_activity(con):
    f = con.execute("SELECT * FROM fct_user_daily ORDER BY user_id, activity_date").df()
    u1 = f[f["user_id"] == 1]
    assert list(u1["days_since_signup"]) == [0, 8]
    assert u1["workouts_completed"].sum() == 1
    # user 2 has no row on day 8: subscription_start is not a user action
    assert list(f.loc[f["user_id"] == 2, "days_since_signup"]) == [0]


def test_retention_flags_and_maturity(con):
    d = con.execute("SELECT user_id, d7_retained, d30_retained, d7_mature, onboarded FROM dim_users ORDER BY 1").df()
    assert d["d7_retained"].tolist() == [True, False, False]
    assert d["d7_mature"].tolist() == [True, True, False]
    assert d["onboarded"].tolist() == [True, False, False]


def test_dau_and_mau(con):
    e = con.execute("SELECT * FROM mart_engagement_daily WHERE day IN ('2025-01-01', '2025-01-09')").df()
    jan1, jan9 = e.iloc[0], e.iloc[1]
    assert jan1["dau"] == 2 and jan1["mau"] == 2
    # on Jan 9 only user 1 is active, but both were active in the trailing 30 days
    assert jan9["dau"] == 1 and jan9["mau"] == 2 and jan9["stickiness_dau_mau"] == pytest.approx(0.5)


def test_cohort_retention_is_censoring_aware(con):
    r = con.execute("SELECT * FROM mart_cohort_retention").df()
    jan_w1 = r[(r["cohort_month"].astype(str) == "2025-01-01") & (r["week_since_signup"] == 1)].iloc[0]
    assert jan_w1["cohort_users"] == 2 and jan_w1["retained_users"] == 1
    # the March user signed up 11 days before the end of data: week 0 (days 0-6) is
    # complete, week 1 (days 7-13) is not, so it must not appear yet
    mar = r[r["cohort_month"].astype(str) == "2025-03-01"]
    assert mar["week_since_signup"].max() == 0
