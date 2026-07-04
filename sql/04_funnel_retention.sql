-- funnel, activation and retention
--   mart_funnel:           funnel counts by signup month, channel and platform
--   mart_activation:       first-week behaviour and D30 retention per user
--   mart_cohort_retention: monthly cohorts by weeks since signup (handles censoring)
--   mart_retention_curve:  Dn retention by acquisition channel

-- Only cohorts whose 30-day window is complete, so recent cohorts don't look worse.
CREATE OR REPLACE TABLE mart_funnel AS
SELECT
    date_trunc('month', signup_date)::DATE                                  AS signup_month,
    acquisition_channel,
    platform,
    count(*)                                                                AS signups,
    count(*) FILTER (WHERE onboarded)                                       AS onboarded,
    count(*) FILTER (WHERE date_diff('day', signup_date, CAST(first_workout_at AS DATE)) <= 6)
                                                                            AS first_workout_7d,
    count(*) FILTER (WHERE first_paywall_at IS NOT NULL)                    AS saw_paywall,
    count(*) FILTER (WHERE trial_started_at IS NOT NULL)                    AS started_trial,
    count(*) FILTER (WHERE subscribed_at    IS NOT NULL)                    AS subscribed,
    count(*) FILTER (WHERE d30_retained)                                    AS retained_d30
FROM dim_users
WHERE d30_mature
GROUP BY ALL;


CREATE OR REPLACE TABLE mart_activation AS
SELECT
    user_id,
    signup_date,
    acquisition_channel,
    platform,
    onboarded::INTEGER        AS onboarded,
    workouts_first_7d,
    active_days_first_7d,
    d7_retained::INTEGER      AS d7_retained,
    d30_retained::INTEGER     AS d30_retained
FROM dim_users
WHERE d30_mature;


CREATE OR REPLACE TABLE mart_cohort_retention AS
WITH weekly_activity AS (
    SELECT DISTINCT user_id, days_since_signup // 7 AS week_since_signup
    FROM fct_user_daily
    WHERE is_active AND days_since_signup < 7 * 13
),
grid AS (
    SELECT
        u.user_id,
        date_trunc('month', u.signup_date)::DATE AS cohort_month,
        w.week
    FROM stg_users AS u
    CROSS JOIN range(0, 13) AS w(week)
    -- censoring: a user only enters the week w denominator once that week is over
    WHERE u.signup_date + CAST(w.week * 7 + 6 AS INTEGER) <= DATE '{{ obs_end }}'
)
SELECT
    g.cohort_month,
    g.week                             AS week_since_signup,
    count(*)                           AS cohort_users,
    count(a.user_id)                   AS retained_users,
    count(a.user_id) / count(*)        AS retention_rate
FROM grid AS g
LEFT JOIN weekly_activity AS a
       ON a.user_id = g.user_id AND a.week_since_signup = g.week
GROUP BY ALL
ORDER BY ALL;


CREATE OR REPLACE TABLE mart_retention_curve AS
WITH horizons AS (
    SELECT unnest([1, 7, 14, 30, 60, 90]) AS day_n
),
eligible AS (
    SELECT u.user_id, u.acquisition_channel, h.day_n
    FROM stg_users AS u
    CROSS JOIN horizons AS h
    WHERE u.signup_date + h.day_n + 6 <= DATE '{{ obs_end }}'
),
retained AS (
    SELECT DISTINCT e.user_id, e.day_n
    FROM eligible AS e
    JOIN fct_user_daily AS f
      ON f.user_id = e.user_id
     AND f.is_active
     AND f.days_since_signup BETWEEN e.day_n AND e.day_n + 6
)
SELECT
    e.acquisition_channel,
    e.day_n,
    count(*)                       AS eligible_users,
    count(r.user_id)               AS retained_users,
    count(r.user_id) / count(*)    AS retention_rate
FROM eligible AS e
LEFT JOIN retained AS r USING (user_id, day_n)
GROUP BY ALL
ORDER BY ALL;
