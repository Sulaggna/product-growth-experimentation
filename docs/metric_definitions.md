# Metric definitions

These are the definitions used in the SQL and in the reports. When a metric needs a
window to pass before it can be measured, users whose window is not complete are left
out of the denominator.

## Engagement

| metric | definition |
|---|---|
| Active user (day) | at least one `app_open` that day. Billing events never count. |
| DAU | active users on the day |
| WAU / MAU | distinct active users in the trailing 7 / 30 days, including the day itself |
| Stickiness | DAU / MAU. Reported as a 7-day average in charts. |

## Retention and activation

| metric | definition |
|---|---|
| Dn retention | share of users active at least once in days n to n+6 after signup (signup day = day 0). Only users with signup_date + n + 6 <= last data day are counted. |
| D7 / D30 retention | Dn retention with n = 7 and n = 30 |
| Weekly cohort retention | share of a monthly signup cohort active in week w (days 7w to 7w+6). A user enters week w only once that week is over. |
| Activation rule | "active on at least k of the first 7 days", k chosen by the largest Youden's J (TPR - FPR) for predicting D30 retention |

I used a week window for Dn retention instead of the single day n. Single-day retention
jumps around with the day of the week, which makes small experiment effects harder to see.

## Funnel

Share of signups that reach each stage, for cohorts with a complete 30-day window:
signed up, completed onboarding, saw paywall, started free trial, became a paying
subscriber. Stages are reach rates, so a few users see the paywall without finishing
onboarding.

## Revenue

| metric | definition |
|---|---|
| MRR | sum of monthly-normalised list price (annual / 12) over subscriptions with paid access at month end |
| New MRR | MRR of subscriptions that started in the month |
| Churned MRR | MRR of subscriptions whose paid access ended in the month |
| Logo churn rate | subscriptions active at the start of the month whose access ended during it, divided by subscriptions active at the start |
| Net revenue | charges after store fees |

## Unit economics (by acquisition channel)

| metric | definition |
|---|---|
| Cost per signup | spend / signups |
| CAC | spend / paying subscribers acquired |
| Monthly churn (c) | churned subscriptions / observed paid subscription-months. This treats churn as a constant hazard and handles subscriptions that are still active. |
| Net ARPU (R) | net monthly revenue per paying subscriber, weighted by observed months |
| LTV (24 months) | R x (1 - (1 - c)^24) / c. Capped at 24 months to stay conservative. |
| LTV:CAC | LTV / CAC |
| Payback | months until cumulative expected net revenue covers CAC: ln(1 - CAC x c / R) / ln(1 - c). Never pays back if CAC x c / R >= 1. |

## Experiment metrics

### onboarding_v2 (new users)

| role | metric |
|---|---|
| primary | D7 retention |
| secondary | onboarding completion, trial start within 7 days, D30 retention |
| guardrail | trial-to-paid conversion (among trial starters), crashes per session in the first 7 days |

Crashes per session is a ratio metric. Users are randomised, not sessions, so its
variance uses the delta method.

### smart_reminders (existing users)

| role | metric |
|---|---|
| primary | completed workouts per user over the 28-day test window |
| covariate (CUPED) | completed workouts in the 28 days before launch |
| secondary | active days per user over the window |
| read-out | weekly effect for weeks 1 to 4 (novelty check) |

## Churn model

| item | definition |
|---|---|
| Population | monthly subscriptions with a complete 30-day label window that had not cancelled by day 14 |
| Scoring point | day 14 of the subscription |
| Label | auto-renew switched off before day 30 |
| Features | activity in subscription days 0-13 and the 7 trial days, plus channel, platform, region, age band and device tier |
