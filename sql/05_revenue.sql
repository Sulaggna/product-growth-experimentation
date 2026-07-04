-- revenue and unit economics
--   mart_mrr_monthly:       MRR, subscriber counts and MRR movements per month
--   mart_channel_economics: CAC, LTV, LTV:CAC and payback by acquisition channel
--   mart_channel_daily:     daily spend and signups per paid channel

CREATE OR REPLACE TABLE mart_mrr_monthly AS
WITH months AS (
    SELECT
        CAST(m AS DATE)                                         AS month_start,
        CAST(m + INTERVAL 1 MONTH - INTERVAL 1 DAY AS DATE)     AS month_end
    FROM generate_series(TIMESTAMP '{{ signup_start }}', TIMESTAMP '{{ obs_end }}', INTERVAL 1 MONTH) AS t(m)
),
movements AS (
    SELECT
        mo.month_start,
        mo.month_end,
        -- stock at month end: started by month end and access not yet ended
        sum(s.mrr_usd) FILTER (WHERE s.start_date <= mo.month_end
                                 AND (s.end_date IS NULL OR s.end_date > mo.month_end))      AS mrr_usd,
        count(*)       FILTER (WHERE s.start_date <= mo.month_end
                                 AND (s.end_date IS NULL OR s.end_date > mo.month_end))      AS subscribers,
        count(*)       FILTER (WHERE s.start_date <  mo.month_start
                                 AND (s.end_date IS NULL OR s.end_date >= mo.month_start))   AS subscribers_at_start,
        -- flows during the month
        coalesce(sum(s.mrr_usd) FILTER (WHERE s.start_date BETWEEN mo.month_start AND mo.month_end), 0) AS new_mrr_usd,
        count(*)       FILTER (WHERE s.start_date BETWEEN mo.month_start AND mo.month_end)   AS new_subscribers,
        coalesce(sum(s.mrr_usd) FILTER (WHERE s.end_date BETWEEN mo.month_start AND mo.month_end), 0)   AS churned_mrr_usd,
        count(*)       FILTER (WHERE s.end_date BETWEEN mo.month_start AND mo.month_end
                                 AND s.start_date < mo.month_start)                          AS churned_from_start
    FROM months AS mo
    CROSS JOIN stg_subscriptions AS s
    GROUP BY ALL
),
revenue AS (
    SELECT date_trunc('month', charge_date)::DATE AS month_start,
           sum(gross_usd) AS gross_revenue_usd,
           sum(net_usd)   AS net_revenue_usd
    FROM stg_charges
    GROUP BY 1
)
SELECT
    m.*,
    m.mrr_usd - lag(m.mrr_usd, 1, 0) OVER (ORDER BY m.month_start)    AS net_new_mrr_usd,
    m.churned_from_start / nullif(m.subscribers_at_start, 0)         AS logo_churn_rate,
    r.gross_revenue_usd,
    r.net_revenue_usd,
    m.month_end <= DATE '{{ obs_end }}'                               AS month_complete
FROM movements AS m
LEFT JOIN revenue AS r USING (month_start)
ORDER BY m.month_start;


CREATE OR REPLACE TABLE mart_channel_economics AS
WITH spend AS (
    SELECT channel, sum(spend_usd) AS spend_usd
    FROM stg_marketing_spend
    GROUP BY 1
),
signups AS (
    SELECT acquisition_channel AS channel, count(*) AS signups
    FROM stg_users
    GROUP BY 1
),
fee AS (   -- effective net/gross ratio actually realised per subscription
    SELECT subscription_id, sum(net_usd) / sum(gross_usd) AS net_ratio
    FROM stg_charges
    GROUP BY 1
),
subs AS (
    SELECT
        u.acquisition_channel                                              AS channel,
        s.subscription_id,
        s.mrr_usd * f.net_ratio                                            AS net_mrr_usd,
        -- paid exposure observed so far, censored at the end of the data
        date_diff('day', s.start_date,
                  least(coalesce(s.end_date, DATE '{{ obs_end }}'), DATE '{{ obs_end }}')) / 30.4375
                                                                           AS exposure_months,
        (s.end_date IS NOT NULL AND s.end_date <= DATE '{{ obs_end }}')    AS churned
    FROM stg_subscriptions AS s
    JOIN stg_users AS u USING (user_id)
    JOIN fee       AS f USING (subscription_id)
),
sub_agg AS (
    SELECT
        channel,
        count(*)                                                AS paid_subscribers,
        sum(exposure_months)                                    AS exposure_months,
        count(*) FILTER (WHERE churned)                         AS churned_subscribers,
        sum(net_mrr_usd * exposure_months) / sum(exposure_months) AS net_arpu_month_usd
    FROM subs
    GROUP BY 1
),
base AS (
    SELECT
        g.channel,
        g.signups,
        coalesce(sp.spend_usd, 0)                                   AS spend_usd,
        a.paid_subscribers,
        a.paid_subscribers / g.signups                              AS signup_to_paid_rate,
        a.net_arpu_month_usd,
        -- constant-hazard monthly churn estimated from censored exposure
        a.churned_subscribers / a.exposure_months                   AS monthly_churn_rate
    FROM signups AS g
    JOIN sub_agg AS a USING (channel)
    LEFT JOIN spend AS sp USING (channel)
)
SELECT
    *,
    nullif(spend_usd, 0) / signups                                  AS cost_per_signup_usd,
    nullif(spend_usd, 0) / paid_subscribers                         AS cac_usd,
    -- 24-month LTV (net revenue, geometric survival), capped to stay conservative
    net_arpu_month_usd * (1 - pow(1 - monthly_churn_rate, 24)) / monthly_churn_rate AS ltv_24m_usd,
    (net_arpu_month_usd * (1 - pow(1 - monthly_churn_rate, 24)) / monthly_churn_rate)
        / (nullif(spend_usd, 0) / paid_subscribers)                 AS ltv_to_cac,
    -- months until cumulative net revenue (with survival) covers CAC
    CASE
        WHEN spend_usd = 0 THEN NULL
        WHEN (spend_usd / paid_subscribers) * monthly_churn_rate / net_arpu_month_usd < 1
        THEN ln(1 - (spend_usd / paid_subscribers) * monthly_churn_rate / net_arpu_month_usd)
             / ln(1 - monthly_churn_rate)
    END                                                             AS payback_months
FROM base
ORDER BY channel;


CREATE OR REPLACE TABLE mart_channel_daily AS
SELECT
    s.spend_date,
    s.channel,
    s.spend_usd,
    s.impressions,
    s.clicks,
    count(u.user_id) AS signups
FROM stg_marketing_spend AS s
LEFT JOIN stg_users AS u
       ON u.acquisition_channel = s.channel AND u.signup_date = s.spend_date
GROUP BY ALL
ORDER BY ALL;
