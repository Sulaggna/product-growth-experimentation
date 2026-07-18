# Experiment plans

Written before looking at the results. The numbers come from pre-launch data only.

## onboarding_v2

**Hypothesis.** A shorter onboarding flow (3 steps instead of 5) gets more new users
through onboarding, and more of them come back in their second week.

**Population.** All new signups from 1 Sep to 12 Oct 2025, on every platform.

**Randomisation.** 50/50 by a hash of user_id at signup. Unit of analysis: user.

**Metrics.**

| role | metric | decision use |
|---|---|---|
| primary | D7 retention (active at least once in days 7-13) | ship if the 95% CI is above zero |
| secondary | onboarding completion, trial start within 7 days, D30 retention | Holm-adjusted, supporting evidence |
| guardrail | trial-to-paid conversion | must not be significantly worse (tolerance -3 pp) |
| guardrail | crashes per session, first 7 days | must not be significantly worse (tolerance +0.1 pp) |

**Power.** Baseline D7 retention for mobile signups in July and August 2025 was 36.6%.
To detect +2.5 pp (about 7% relative) with alpha 0.05 (two-sided) and 80% power, I need
5,908 users per arm. At about 282 mobile signups a day that is 42 days, so the test runs
for 6 weeks (1 Sep to 12 Oct). D7 needs 13 more days before the last cohort can be read.

**Checks before reading results.**

- Sample ratio per platform. If a platform fails (p < 0.001), I find the cause and
  exclude it from the main analysis.
- No peeking: one read-out after the last D7 window is complete.

**Segments.** Platform and acquisition channel, adjusted with Benjamini-Hochberg. These
are exploratory and do not change the ship decision on their own.

## smart_reminders

**Hypothesis.** Reminders timed to when a user usually works out increase the number of
workouts.

**Population.** Users who signed up before 6 Oct 2025 and were active at least once
between 6 Oct and 2 Nov 2025 (5,952 users).

**Randomisation.** 50/50 by a hash of user_id. Runs 3 Nov to 30 Nov 2025 (28 days).

**Metrics.**

| role | metric |
|---|---|
| primary | completed workouts per user over the 28 days |
| secondary | active days per user over the 28 days |
| read-out | weekly effects, to check whether the effect fades |

**Analysis.** The metric is heavy-tailed (many zeros, a few very active users), so I use
CUPED with workouts in the 28 days before launch as the covariate and confirm the CI with
a bootstrap.

**Power.** In the pre-period these users averaged 10.9 workouts per 28 days with an SD of
11.4. Workouts in consecutive 4-week periods correlate at 0.68, so CUPED should remove
roughly 45% of the variance. With about 2,976 users per arm:

| analysis | minimum detectable effect |
|---|---|
| raw difference | 0.83 workouts |
| with CUPED | 0.61 workouts |

**Decision.** Ship if the CUPED-adjusted effect is positive with a 95% CI above zero.
Size the expected impact on the later weeks, not on the first week.
