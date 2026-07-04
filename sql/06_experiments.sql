-- experiment tables, one row per exposed user
--   mart_exp_onboarding: onboarding_v2 (new users)
--   mart_exp_reminders:  smart_reminders (existing users, pre and post windows)

CREATE OR REPLACE TABLE mart_exp_onboarding AS
WITH first_week AS (
    SELECT
        user_id,
        sum(sessions) FILTER (WHERE days_since_signup <= 6) AS sessions_7d,
        sum(crashes)  FILTER (WHERE days_since_signup <= 6) AS crashes_7d
    FROM fct_user_daily
    GROUP BY 1
)
SELECT
    x.user_id,
    x.variant,
    x.exposed_at,
    u.signup_date,
    u.platform,
    u.acquisition_channel,
    u.region,
    u.device_tier,
    u.age_band,
    d.onboarded::INTEGER                                                        AS onboarded,
    d.d7_retained::INTEGER                                                      AS d7_retained,
    d.d30_retained::INTEGER                                                     AS d30_retained,
    (d.trial_started_at IS NOT NULL
        AND date_diff('day', u.signup_date, CAST(d.trial_started_at AS DATE)) <= 6)::INTEGER AS trial_7d,
    -- guardrail: conversion of the trials that did start (NULL = no trial)
    CASE WHEN d.trial_started_at IS NOT NULL THEN (d.subscribed_at IS NOT NULL)::INTEGER END AS trial_converted,
    coalesce(w.sessions_7d, 0)                                                  AS sessions_7d,
    coalesce(w.crashes_7d, 0)                                                   AS crashes_7d
FROM stg_experiment_exposures AS x
JOIN stg_users  AS u USING (user_id)
JOIN dim_users  AS d USING (user_id)
LEFT JOIN first_week AS w USING (user_id)
WHERE x.experiment = 'onboarding_v2';


CREATE OR REPLACE TABLE mart_exp_reminders AS
WITH x AS (
    SELECT user_id, variant
    FROM stg_experiment_exposures
    WHERE experiment = 'smart_reminders'
),
windows AS (
    SELECT
        f.user_id,
        -- pre-period (28 days before launch), used as the CUPED covariate
        sum(f.workouts_completed) FILTER (WHERE f.activity_date BETWEEN DATE '{{ exp2_pre_start }}' AND DATE '{{ exp2_pre_end }}') AS pre_workouts,
        count(*) FILTER (WHERE f.is_active AND f.activity_date BETWEEN DATE '{{ exp2_pre_start }}' AND DATE '{{ exp2_pre_end }}')  AS pre_active_days,
        -- experiment window (28 days), the outcome
        sum(f.workouts_completed) FILTER (WHERE f.activity_date BETWEEN DATE '{{ exp2_start }}' AND DATE '{{ exp2_end }}')         AS workouts_28d,
        count(*) FILTER (WHERE f.is_active AND f.activity_date BETWEEN DATE '{{ exp2_start }}' AND DATE '{{ exp2_end }}')          AS active_days_28d,
        -- weekly split for the novelty check
        sum(f.workouts_completed) FILTER (WHERE f.activity_date BETWEEN DATE '{{ exp2_start }}'      AND DATE '{{ exp2_start }}' + 6)  AS workouts_wk1,
        sum(f.workouts_completed) FILTER (WHERE f.activity_date BETWEEN DATE '{{ exp2_start }}' + 7  AND DATE '{{ exp2_start }}' + 13) AS workouts_wk2,
        sum(f.workouts_completed) FILTER (WHERE f.activity_date BETWEEN DATE '{{ exp2_start }}' + 14 AND DATE '{{ exp2_start }}' + 20) AS workouts_wk3,
        sum(f.workouts_completed) FILTER (WHERE f.activity_date BETWEEN DATE '{{ exp2_start }}' + 21 AND DATE '{{ exp2_start }}' + 27) AS workouts_wk4
    FROM fct_user_daily AS f
    WHERE f.user_id IN (SELECT user_id FROM x)
    GROUP BY 1
)
SELECT
    x.user_id,
    x.variant,
    u.platform,
    u.acquisition_channel,
    u.region,
    coalesce(w.pre_workouts, 0)     AS pre_workouts,
    coalesce(w.pre_active_days, 0)  AS pre_active_days,
    coalesce(w.workouts_28d, 0)     AS workouts_28d,
    coalesce(w.active_days_28d, 0)  AS active_days_28d,
    coalesce(w.workouts_wk1, 0)     AS workouts_wk1,
    coalesce(w.workouts_wk2, 0)     AS workouts_wk2,
    coalesce(w.workouts_wk3, 0)     AS workouts_wk3,
    coalesce(w.workouts_wk4, 0)     AS workouts_wk4
FROM x
JOIN stg_users AS u USING (user_id)
LEFT JOIN windows AS w USING (user_id);
