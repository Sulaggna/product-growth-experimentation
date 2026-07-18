# Methodology

## Why the data is simulated

Real product event logs and experiment results are not published, so I wrote a
simulator that produces a realistic warehouse for a made-up app. The upside is that every
effect is known, so I can check whether my analysis finds the right answer. The downside
is that the findings describe the simulator, not a real business. The methods are the
point of the project.

## The simulator

`src/growth_analytics/simulate.py`, seed 11, about 149k users and 5.8M events, Jan 2025
to Jan 2026. It runs in a few seconds.

### Users and acquisition

- Organic and referral signups follow a daily baseline with weekday effects, a New Year
  spike that decays over about a month, a small early-summer bump and a holiday dip.
- Paid signups (paid social, search, influencer) follow `signups = k * spend^b` with
  b = 0.80, 0.70 and 0.85. Spend is raised in January and November, and influencer spend
  comes in 8-day campaign bursts.
- Platform, region, device tier and age band are drawn per channel (for example search
  skews to web and paid social to Android).

### Engagement

Each user gets a latent engagement score from a normal draw plus effects for channel
(referral highest, influencer lowest), platform, device, age and signup season (users
who sign up in early January are less engaged). From that score:

- onboarding completion is a logistic function of the score
- lifetime in days is Weibull with shape 0.65, so many users leave within days and a
  long tail stays for months; finishing onboarding makes lifetimes longer
- on each day of the lifetime the user is active with a probability that depends on the
  score, a short honeymoon period, weekday and season
- workouts on an active day are Poisson with a per-user rate, which gives a heavy tail

### Monetisation

- The paywall is shown at onboarding (or on an early return visit for users who skipped
  onboarding). Trial start depends on the score, platform and region.
- Trial-to-paid conversion depends on the score and on workouts during the 7-day trial.
- About a third of subscribers pick the annual plan.
- For monthly plans, cancelling before the first renewal depends on activity in the first
  14 days of the subscription, whether workouts dropped from week 1 to week 2, channel,
  region and age. Later months have a lower constant churn rate.

### Planted experiments

**onboarding_v2** (new users, 1 Sep to 12 Oct 2025, 50/50 by hashed user id). The shorter
flow raises the log-odds of finishing onboarding, more on Android and for paid social and
influencer users, less on web. It also slightly lengthens lifetimes. A small negative
effect on trial-to-paid conversion is planted (-0.06 log-odds). On web, the treatment
exposure event was often not logged for users who bounced quickly, which creates a
sample ratio mismatch and biases any web comparison upwards.

**smart_reminders** (users active in the 28 days before 3 Nov 2025, 50/50). Reminders
raise the daily activity probability and workout rate by 8% and 5% in week 1, falling to
3% and 1.5% by week 4.

### Ground truth

Random draws that both arms share (activity, workout counts, onboarding, lifetime) come
from a hash of (seed, user_id, day) instead of a sequential random generator. So I can
compute each user's outcome under both control and treatment and get the exact average
effect for the people in the test. These values go to `data/ground_truth.json` and are
used only for validation.

## Analysis methods

### Warehouse

DuckDB SQL in `sql/`, run in order by `warehouse.py`. Raw parquet is exposed as staging
views, events are rolled up to a user-day table, and marts are built on top. Metrics
that need a window to pass (D7, D30, weekly cohorts, the churn label) only include users
whose window is complete.

### Experiment 1

1. Power analysis from July and August mobile cohorts (baseline D7 36.6%, MDE 2.5 pp,
   alpha 0.05, power 0.8): 5,908 users per arm, 42 days at about 282 signups a day.
2. SRM chi-square test overall and per platform.
3. Primary metric with a two-proportion z-test (pooled SE for the p-value, unpooled for
   the CI).
4. Secondary metrics with Holm correction.
5. Guardrails: a guardrail is breached if it is significantly worse (one-sided test,
   Holm-adjusted across guardrails). I also report whether the CI stays inside a
   tolerance margin. Crashes per session uses the delta method.
6. Segments by platform and channel with Benjamini-Hochberg adjustment, plus one
   interaction test (Android lift minus iOS lift).

### Experiment 2

1. SRM check and a pre-period balance check (an A/A comparison on pre-launch data).
2. Welch t-test on the raw metric, and a percentile bootstrap CI because the metric is
   heavy-tailed.
3. CUPED with pre-period workouts as the covariate, theta estimated on both arms pooled.
4. Weekly CUPED effects to check for novelty, and a weeks 3-4 estimate as the longer-run
   effect.

### Churn model

Out-of-time split (train: subscriptions starting before 1 Sep 2025, test: later). I
compared a logistic regression (log-scaled counts, one-hot categoricals) with a
histogram gradient boosting model, picked the model by 5-fold cross-validation on the
training period and reported both on the test period. The retention offer threshold is
chosen on out-of-fold training predictions by expected value:

- a would-be churner who takes the offer is saved with probability 0.30 and pays for 3
  more months, minus the $6.50 discount
- a subscriber who was going to stay anyway redeems the discount with probability 0.60

### Marketing

Spend response per channel is a log-log regression of daily signups on daily spend with
month and weekday fixed effects and HC1 standard errors. The fixed effects matter because
budgets go up in January, when demand is also high. The budget optimiser keeps the total
budget fixed, maximises 24-month LTV and keeps each channel within 0.5x to 2x of its
current spend.

### Coverage study

`validation.py` re-runs everything with 40 new seeds and records how often the 95% CIs
contain the true effect. Results are in `reports/tables/estimator_coverage.csv`.

## Limitations

- The data is simulated. Real data would have messier tracking, more seasonality and
  interactions I did not model.
- The two experiments overlap in time for some users. Assignment is independent, so this
  adds noise but no bias.
- LTV assumes a constant churn rate after the first months and is capped at 24 months.
- Spend elasticities are only reliable near the observed spend range.
- The activation rule and the churn drivers are correlations, not causal effects.
