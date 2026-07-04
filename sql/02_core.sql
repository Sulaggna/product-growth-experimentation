-- core models
--   fct_user_daily: one row per user per day with any activity
--   dim_users:      one row per user with milestones and retention flags

-- User-day fact table built from the raw events. Only user-initiated events count
-- as activity. Billing events (subscription_start, renewal) are left out.
CREATE OR REPLACE TABLE fct_user_daily AS
SELECT
    *,
    sessions > 0 AS is_active
FROM (
    SELECT
        e.user_id,
        e.event_date                                               AS activity_date,
        date_diff('day', u.signup_date, e.event_date)              AS days_since_signup,
        count(*) FILTER (WHERE e.event_name = 'app_open')          AS sessions,
        count(*) FILTER (WHERE e.event_name = 'workout_started')   AS workouts_started,
        count(*) FILTER (WHERE e.event_name = 'workout_completed') AS workouts_completed,
        count(*) FILTER (WHERE e.event_name = 'app_crash')         AS crashes
    FROM stg_events AS e
    JOIN stg_users  AS u USING (user_id)
    WHERE e.event_name IN ('app_open', 'workout_started', 'workout_completed', 'app_crash')
    GROUP BY ALL
);


CREATE OR REPLACE TABLE dim_users AS
WITH milestones AS (
    SELECT
        user_id,
        min(event_ts) FILTER (WHERE event_name = 'onboarding_complete') AS onboarded_at,
        max(CAST(json_extract_string(event_props, '$.step') AS INTEGER))
            FILTER (WHERE event_name = 'onboarding_step')                AS max_onboarding_step,
        min(event_ts) FILTER (WHERE event_name = 'workout_completed')   AS first_workout_at,
        min(event_ts) FILTER (WHERE event_name = 'paywall_view')        AS first_paywall_at,
        min(event_ts) FILTER (WHERE event_name = 'trial_start')         AS trial_started_at,
        min(event_ts) FILTER (WHERE event_name = 'subscription_start')  AS subscribed_at
    FROM stg_events
    WHERE event_name IN ('onboarding_step', 'onboarding_complete', 'workout_completed',
                         'paywall_view', 'trial_start', 'subscription_start')
    GROUP BY user_id
),
activity AS (
    SELECT
        user_id,
        coalesce(sum(workouts_completed) FILTER (WHERE days_since_signup BETWEEN 0 AND 6), 0) AS workouts_first_7d,
        count(*) FILTER (WHERE is_active AND days_since_signup BETWEEN 0 AND 6)               AS active_days_first_7d,
        coalesce(bool_or(is_active AND days_since_signup = 1), FALSE)                         AS d1_retained,
        -- Dn retention = active at least once in days n to n+6. A week window avoids
        -- the day-of-week noise of the single-day definition
        coalesce(bool_or(is_active AND days_since_signup BETWEEN 7  AND 13), FALSE)           AS d7_retained,
        coalesce(bool_or(is_active AND days_since_signup BETWEEN 30 AND 36), FALSE)           AS d30_retained,
        max(activity_date) FILTER (WHERE is_active)                                          AS last_active_date,
        count(*) FILTER (WHERE is_active)                                                    AS lifetime_active_days,
        sum(workouts_completed)                                                              AS lifetime_workouts
    FROM fct_user_daily
    GROUP BY user_id
)
SELECT
    u.*,
    m.onboarded_at IS NOT NULL                                AS onboarded,
    m.max_onboarding_step,
    m.first_workout_at,
    m.first_paywall_at,
    m.trial_started_at,
    m.subscribed_at,
    s.subscription_id,
    s.plan,
    coalesce(a.workouts_first_7d, 0)                          AS workouts_first_7d,
    coalesce(a.active_days_first_7d, 0)                       AS active_days_first_7d,
    coalesce(a.d1_retained,  FALSE)                           AS d1_retained,
    coalesce(a.d7_retained,  FALSE)                           AS d7_retained,
    coalesce(a.d30_retained, FALSE)                           AS d30_retained,
    a.last_active_date,
    coalesce(a.lifetime_active_days, 0)                       AS lifetime_active_days,
    coalesce(a.lifetime_workouts, 0)                          AS lifetime_workouts,
    -- maturity flags: only use a retention flag once its window has passed
    u.signup_date + 13 <= DATE '{{ obs_end }}'                AS d7_mature,
    u.signup_date + 36 <= DATE '{{ obs_end }}'                AS d30_mature
FROM stg_users            AS u
LEFT JOIN milestones      AS m USING (user_id)
LEFT JOIN activity        AS a USING (user_id)
LEFT JOIN stg_subscriptions AS s USING (user_id);
