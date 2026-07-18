# Kinora growth review: summary

Period: January 2025 to January 2026. Simulated data for a fictional app (see
`docs/methodology.md`). All numbers come from `reports/metrics.json`.

## Where we are

- 149,317 signups, 9,587 paying subscribers, MRR of $58,685 at the end of January 2026.
- 35% of new users are active in their second week (D7) and 15% a month later (D30).
- Stickiness (DAU/MAU) went from 9.9% in January 2025 to 15.6% in January 2026.
- Monthly subscriber churn has settled around 6%. In recent months churned MRR cancels
  out more than half of new MRR, so retention is now the main growth lever.

## Recommendations

1. **Ship onboarding v2 on iOS and Android.** D7 retention went from 37.2% to 40.5%
   (+3.3 pp, 95% CI +1.6 to +5.0). Most of the gain is on Android (+5.2 pp vs +0.9 pp on
   iOS). At this year's mobile volume that is about 3,900 more users still active in
   their second week (CI 1,900 to 5,900).
2. **Fix web exposure logging, then re-test web.** The web arm lost about half of its
   treatment users from the logs, so the web result (+11.8 pp) is not usable.
3. **Keep an eye on trial-to-paid after launch.** It did not drop significantly, but the
   CI goes down to -7.5 pp, which is wider than we would accept.
4. **Ship smart reminders, but plan on a small long-run effect.** The adjusted lift is
   +0.59 workouts per user per month (CI +0.21 to +0.98). Most of it comes in week 1 and
   it is close to zero by week 4.
5. **Make "3 active days in week one" an onboarding goal and test it.** Users who reach it
   are 7.8 times as likely to be active at D30 (33% vs 4%). This is a correlation, so it
   needs an experiment.
6. **Target the retention discount.** Scoring monthly subscribers on day 14 and offering
   the discount to the 62% above the threshold is worth about $1,265 per 1,000
   subscribers, against $512 for offering it to everyone.
7. **Move budget from influencer to search.** Search returns 2.2x its cost and pays back
   in 6.6 months. Influencer returns 0.64x and never pays back. Re-allocating the same
   budget within 0.5x to 2x of current levels gives about 11% more paying subscribers
   and lowers blended CAC from $69 to $63.

## How sure are we

The experiment estimates were checked against the simulator's true effects, and in a
40-seed re-run the 95% CIs covered the truth 95% (onboarding) and 90% (reminders) of the
time. The marketing and churn findings are based on observational data and should be
treated as directional.
