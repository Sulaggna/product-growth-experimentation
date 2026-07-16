"""Build and execute notebooks/01_growth_analysis_walkthrough.ipynb.

The notebook is generated from this script so it stays in sync with the package.
Run with `make notebook` after `make data warehouse analysis`.
"""

from pathlib import Path

import nbformat as nbf
from nbconvert.preprocessors import ExecutePreprocessor

HERE = Path(__file__).resolve().parent
OUT = HERE / "01_growth_analysis_walkthrough.ipynb"

cells: list = []


def md(text: str) -> None:
    cells.append(nbf.v4.new_markdown_cell(text.strip()))


def code(text: str) -> None:
    cells.append(nbf.v4.new_code_cell(text.strip()))


md("""
# Kinora growth analysis: walkthrough

This notebook walks through the main results of the project in order. The heavy lifting
lives in the `growth_analytics` package and the SQL files in `sql/`. Here I call those
functions and comment on what comes out.

The data is simulated (see `docs/methodology.md`). Kinora is a fictional freemium
fitness app. To run this notebook, first run `make data warehouse analysis`.
""")

code("""
import json
import warnings

import pandas as pd
from IPython.display import Image, display

from growth_analytics import config as C
from growth_analytics import churn_model, experiments as E, funnel as F, marketing as MK
from growth_analytics.warehouse import read

warnings.filterwarnings("ignore")
pd.set_option("display.float_format", "{:.4f}".format)
pd.set_option("display.max_columns", 20)
FIG = C.FIGURES_DIR

def show(name, width=900):
    display(Image(filename=str(FIG / f"{name}.png"), width=width))
""")

md("""
## 1. The data

Six raw tables are loaded into DuckDB as staging views, then modelled into a user-day
fact table, a user dimension and a set of marts.
""")

code("""
read(\"\"\"
SELECT table_name, estimated_size AS rows
FROM duckdb_tables()
ORDER BY table_name
\"\"\")
""")

code("""
read(\"\"\"
SELECT event_name, count(*) AS events, count(DISTINCT user_id) AS users
FROM stg_events
GROUP BY 1
ORDER BY 2 DESC
\"\"\")
""")

md("""
## 2. Engagement and retention

About a third of new users come back in their second week, and roughly one in seven is
still active a month later. Retention differs a lot by acquisition channel.
""")

code("""
read(\"\"\"
SELECT avg(d7_retained::INT)  FILTER (WHERE d7_mature)  AS d7_retention,
       avg(d30_retained::INT) FILTER (WHERE d30_mature) AS d30_retention
FROM dim_users
\"\"\")
""")

code("""
rc = read("mart_retention_curve")
rc.pivot(index="acquisition_channel", columns="day_n", values="retention_rate").round(3)
""")

code("show('04_cohort_retention')")

md("""
## 3. Funnel and the "aha moment"

The biggest drop in the funnel is from paywall to trial. On the activation side, I scanned
simple rules of the form "at least k active days (or workouts) in the first week" and kept
the one that best separates users who are still active at D30.
""")

code("""
F.funnel_table(read("mart_funnel")).round(3)
""")

code("""
act = read("mart_activation")
best = F.best_activation_rule(act)
best
""")

code("show('06_activation_threshold')")

md("""
This is a correlation. Users who come back three times in week one are also the more
motivated users to begin with, so the next step would be an experiment that nudges new
users towards a second and third session.

## 4. Experiment 1: onboarding v2

New users were split 50/50 between the old 5-step onboarding and a shorter 3-step flow.
The primary metric is D7 retention. Before looking at results I sized the test from
July and August cohorts.
""")

code("""
pre = read(\"\"\"
SELECT signup_date, platform, d7_retained::INT AS d7_retained FROM dim_users
WHERE signup_date BETWEEN DATE '2025-07-01' AND DATE '2025-08-31' AND platform IN ('ios', 'android')
\"\"\")
E.power_analysis(pre)
""")

md("""
The first check is the sample ratio. iOS and Android are fine, but web has far fewer
treatment users than control.
""")

code("""
e1 = E.analyze_onboarding(read("mart_exp_onboarding"))
pd.DataFrame(e1["srm_by_platform"]).T[["n_control", "n_treatment", "share_treatment", "p_value"]]
""")

md("""
The new web flow logged its exposure event late, so users who bounced quickly were often
missing from the treatment group. The users that remain are the more engaged ones, which
inflates the web result. I excluded web and analysed iOS and Android only.
""")

code("""
cols = ["metric", "control", "treatment", "abs_diff", "ci_low", "ci_high", "p_value"]
rows = [e1["web_only_primary"], e1["naive_primary"], e1["primary"], *e1["secondary"], *e1["guardrails"]]
pd.DataFrame(rows)[cols]
""")

code("show('08_exp1_effects')")

code("""
pd.DataFrame(e1["segments"])[["dimension", "segment", "abs_diff", "ci_low", "ci_high", "p_value", "p_bh"]]
""")

md("""
The lift is concentrated on Android. The interaction test (Android lift minus iOS lift)
is significant, while the channel splits are exploratory and BH-adjusted.

Decision: ship to iOS and Android, fix the web logging and re-test web separately. The
trial-to-paid guardrail did not move significantly, but its CI is wide, so I would keep
watching it after launch.

## 5. Experiment 2: smart reminders

Existing users were split 50/50, and treatment users got reminders timed to when they
usually work out. The metric is workouts per user over 28 days, which is heavy-tailed.
""")

code("""
e2 = E.analyze_reminders(read("mart_exp_reminders"), n_boot=2000)
e2["distribution"]
""")

code("""
pd.DataFrame([e2["pre_period_balance"], e2["raw"], e2["cuped"]])[cols]
""")

md("""
By chance, the treatment group was already more active before launch. The raw comparison
mixes that head start with the real effect. CUPED adjusts for pre-period workouts, which
removes most of the imbalance and also cuts the variance roughly in half.
""")

code("show('10_exp2_cuped')")
code("show('11_exp2_novelty')")

md("""
Most of the lift comes in the first week and fades after that. For a forecast I would use
the weeks 3-4 effect, not the 28-day average.

## 6. Churn model

The model scores monthly subscribers on day 14 and predicts whether they cancel before the
first renewal. It is trained on subscriptions that started before September and tested on
later ones.
""")

code("""
res = churn_model.run(read("mart_churn_features"))
pd.DataFrame(res.summary["models"]).T
""")

code("res.deciles")

code("""
res.summary["policy"]
""")

code("show('16_retention_offer_policy')")

md("""
Logistic regression did slightly better than gradient boosting here, and it is easier to
explain. The useful output is the targeting rule: offering the discount only to
subscribers above the threshold is worth much more than offering it to everyone.

## 7. Marketing efficiency
""")

code("""
econ = read("mart_channel_economics")
econ[["channel", "spend_usd", "paid_subscribers", "cac_usd", "ltv_24m_usd", "ltv_to_cac", "payback_months"]]
""")

code("""
curves = MK.response_curves(read("mart_channel_daily"))
opt = MK.optimise_budget(econ, curves)
display(curves[["channel", "elasticity", "elasticity_ci_low", "elasticity_ci_high", "marginal_cost_per_signup"]])
{k: v for k, v in opt.items() if k != "table"}
""")

code("show('19_budget_reallocation')")

md("""
## 8. Checking against the simulator

Because the data is simulated, I know the true effects. This is a check that the methods
work, not something available with real data.
""")

code("""
truth = json.loads(C.GROUND_TRUTH_PATH.read_text())
v = E.compare_to_truth(e1, e2, truth)
pd.DataFrame({k: v[k] for k in ["exp1_d7", "exp2_workouts"]}).T
""")

code("show('20_estimator_coverage')")

md("""
## Summary

- Ship onboarding v2 on iOS and Android. Fix web exposure logging before re-testing web.
- Ship smart reminders, but plan on the smaller steady-state effect.
- Push users to come back on at least 3 of their first 7 days, and test that directly.
- Use the churn score to target retention offers instead of a blanket discount.
- Move budget from influencer towards search, within the observed spend range.
""")


def main() -> None:
    nb = nbf.v4.new_notebook()
    nb.cells = cells
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    ExecutePreprocessor(timeout=600, kernel_name="python3").preprocess(nb, {"metadata": {"path": str(HERE)}})
    # keep the file diff-friendly: drop per-cell execution timestamps
    for cell in nb.cells:
        cell.metadata.pop("execution", None)
    nbf.write(nb, OUT)
    print(f"wrote {OUT.name}")


if __name__ == "__main__":
    main()
