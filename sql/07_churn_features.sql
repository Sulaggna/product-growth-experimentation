-- churn model features
-- Scored on day 14 of a monthly subscription. Label: auto-renew switched off before
-- the first renewal on day 30.
--
-- To avoid leakage:
--   - features only use activity from days 0-13 of the subscription
--   - subscribers who cancelled before day 14 are dropped (already known at scoring time)
--   - only subscriptions with a complete 30-day label window are kept

CREATE OR REPLACE TABLE mart_churn_features AS
WITH subs AS (
    SELECT subscription_id, user_id, start_date, cancel_date, list_price_usd
    FROM stg_subscriptions
    WHERE plan = 'monthly'
      AND start_date + 30 <= DATE '{{ obs_end }}'
      AND (cancel_date IS NULL OR cancel_date >= start_date + 14)
),
first_14d AS (
    SELECT
        s.subscription_id,
        sum(f.workouts_completed) FILTER (WHERE f.activity_date <  s.start_date + 7) AS workouts_wk1,
        sum(f.workouts_completed) FILTER (WHERE f.activity_date >= s.start_date + 7) AS workouts_wk2,
        sum(f.workouts_started)                                                      AS workouts_started_14d,
        count(*) FILTER (WHERE f.is_active)                                          AS active_days_14d,
        sum(f.sessions)                                                              AS sessions_14d,
        sum(f.crashes)                                                               AS crashes_14d,
        max(f.activity_date) FILTER (WHERE f.is_active)                              AS last_active_date
    FROM subs AS s
    JOIN fct_user_daily AS f
      ON f.user_id = s.user_id
     AND f.activity_date >= s.start_date
     AND f.activity_date <  s.start_date + 14
    GROUP BY 1
),
trial AS (
    SELECT s.subscription_id, sum(f.workouts_completed) AS trial_workouts
    FROM subs AS s
    JOIN fct_user_daily AS f
      ON f.user_id = s.user_id
     AND f.activity_date >= s.start_date - {{ trial_days }}
     AND f.activity_date <  s.start_date
    GROUP BY 1
)
SELECT
    s.subscription_id,
    s.user_id,
    s.start_date,
    date_trunc('month', s.start_date)::DATE                              AS start_month,
    u.platform,
    u.acquisition_channel,
    u.region,
    u.age_band,
    u.device_tier,
    date_diff('day', u.signup_date, s.start_date)                        AS days_signup_to_subscribe,
    coalesce(t.trial_workouts, 0)                                        AS trial_workouts,
    coalesce(a.workouts_wk1, 0)                                          AS workouts_wk1,
    coalesce(a.workouts_wk2, 0)                                          AS workouts_wk2,
    coalesce(a.workouts_wk1, 0) + coalesce(a.workouts_wk2, 0)            AS workouts_14d,
    coalesce(a.workouts_wk2, 0) - coalesce(a.workouts_wk1, 0)            AS workout_trend,
    coalesce(a.workouts_started_14d, 0)                                  AS workouts_started_14d,
    coalesce(a.active_days_14d, 0)                                       AS active_days_14d,
    coalesce(a.sessions_14d, 0)                                          AS sessions_14d,
    coalesce(a.crashes_14d, 0)                                           AS crashes_14d,
    coalesce(date_diff('day', a.last_active_date, s.start_date + 13), 14) AS days_since_last_active,
    -- label
    (s.cancel_date IS NOT NULL AND s.cancel_date < s.start_date + 30)::INTEGER AS churned_first_renewal
FROM subs AS s
JOIN stg_users AS u USING (user_id)
LEFT JOIN first_14d AS a USING (subscription_id)
LEFT JOIN trial     AS t USING (subscription_id);
