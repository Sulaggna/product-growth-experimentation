-- engagement
--   mart_engagement_daily:   DAU, rolling WAU and MAU, stickiness per day
--   mart_engagement_monthly: calendar month roll-up

CREATE OR REPLACE TABLE mart_engagement_daily AS
WITH days AS (
    SELECT CAST(d AS DATE) AS day
    FROM generate_series(TIMESTAMP '{{ signup_start }}', TIMESTAMP '{{ obs_end }}', INTERVAL 1 DAY) AS t(d)
),
active AS (
    SELECT user_id, activity_date, workouts_completed
    FROM fct_user_daily
    WHERE is_active
),
dau AS (
    SELECT activity_date AS day,
           count(*)                AS dau,
           sum(workouts_completed) AS workouts_completed
    FROM active
    GROUP BY 1
),
rolling AS (
    -- range join: each active user-day counts towards the 30 trailing windows it falls in
    SELECT
        d.day,
        count(DISTINCT a.user_id) FILTER (WHERE a.activity_date > d.day - 7) AS wau,
        count(DISTINCT a.user_id)                                            AS mau
    FROM days AS d
    JOIN active AS a
      ON a.activity_date BETWEEN d.day - 29 AND d.day
    GROUP BY d.day
)
SELECT
    r.day,
    coalesce(dau.dau, 0)                                AS dau,
    r.wau,
    r.mau,
    coalesce(dau.dau, 0) / r.mau                        AS stickiness_dau_mau,
    avg(coalesce(dau.dau, 0)) OVER w7                   AS dau_7d_avg,
    coalesce(dau.workouts_completed, 0)                 AS workouts_completed,
    r.day >= DATE '{{ signup_start }}' + 29             AS window_complete   -- MAU needs 30 days of history
FROM rolling AS r
LEFT JOIN dau USING (day)
WINDOW w7 AS (ORDER BY r.day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
ORDER BY r.day;


CREATE OR REPLACE TABLE mart_engagement_monthly AS
SELECT
    date_trunc('month', f.activity_date)::DATE           AS month,
    count(DISTINCT f.user_id)                            AS mau,
    count(*) / count(DISTINCT f.activity_date)           AS avg_dau,
    count(*) / count(DISTINCT f.activity_date) / count(DISTINCT f.user_id) AS stickiness,
    sum(f.workouts_completed) / count(DISTINCT f.user_id) AS workouts_per_mau,
    count(DISTINCT f.user_id) FILTER (
        WHERE date_trunc('month', u.signup_date) = date_trunc('month', f.activity_date)
    )                                                    AS new_mau        -- signed up this month
FROM fct_user_daily AS f
JOIN stg_users      AS u USING (user_id)
WHERE f.is_active
GROUP BY 1
ORDER BY 1;
