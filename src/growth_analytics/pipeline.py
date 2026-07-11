"""Run every analysis and write figures, tables and ``reports/metrics.json``.

Run:  ``python -m growth_analytics.pipeline``  (needs ``make data warehouse`` first)
"""

from __future__ import annotations

import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from . import churn_model, figures
from . import config as C
from . import experiments as E
from . import funnel as F
from . import marketing as MK
from . import validation as V
from .warehouse import read


class _Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if np.isnan(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (pd.Timestamp, np.datetime64)) or hasattr(o, "isoformat"):
            return str(o)[:10]
        return super().default(o)


def _clean_nan(obj):
    if isinstance(obj, float) and np.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    return obj


def _table(df: pd.DataFrame, name: str) -> None:
    C.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(C.TABLES_DIR / f"{name}.csv", index=False, float_format="%.6g")


def run() -> dict:
    warnings.filterwarnings("ignore", category=UserWarning)
    t0 = time.time()
    m: dict = {"generated_from": "simulated data (see docs/methodology.md)", "seed": C.SEED,
               "observation_end": C.OBS_END.isoformat()}
    figs: list[Path] = []

    # overview
    overview = read("""
        SELECT count(*) AS users,
               count(*) FILTER (WHERE subscription_id IS NOT NULL) AS paying_subscribers,
               min(signup_date) AS first_signup, max(signup_date) AS last_signup
        FROM dim_users""").iloc[0].to_dict()
    overview["events"] = int(read("SELECT count(*) AS n FROM stg_events")["n"].iloc[0])
    m["overview"] = overview

    # engagement
    daily, monthly = read("mart_engagement_daily"), read("mart_engagement_monthly")
    m["engagement"] = F.engagement_summary(daily, monthly)
    figs.append(figures.engagement_trend(daily))
    weekly = read("""SELECT date_trunc('week', signup_date)::DATE AS week, acquisition_channel, count(*) AS signups
                     FROM dim_users GROUP BY ALL""")
    figs.append(figures.acquisition_by_channel(weekly))

    # funnel & retention
    mf = read("mart_funnel")
    f_all, f_ch, f_pl = F.funnel_table(mf), F.funnel_table(mf, "acquisition_channel"), F.funnel_table(mf, "platform")
    _table(f_all, "funnel_overall")
    _table(f_ch, "funnel_by_channel")
    _table(f_pl, "funnel_by_platform")
    m["funnel"] = {"overall": f_all.to_dict(orient="records"), "biggest_drop": F.biggest_drop(f_all)}
    figs.append(figures.funnel(f_all, f_ch))

    cr = read("mart_cohort_retention")
    _table(cr, "cohort_retention")
    figs.append(figures.cohort_heatmap(cr))
    rc = read("mart_retention_curve")
    _table(rc, "retention_by_channel")
    figs.append(figures.retention_curves(rc))
    ret = read("""SELECT avg(d7_retained::INT) FILTER (WHERE d7_mature) AS d7,
                         avg(d30_retained::INT) FILTER (WHERE d30_mature) AS d30 FROM dim_users""").iloc[0]
    m["retention"] = {"d7": float(ret["d7"]), "d30": float(ret["d30"]),
                      "d30_by_channel": rc[rc["day_n"] == 30].set_index("acquisition_channel")["retention_rate"].to_dict()}

    act = read("mart_activation")
    scan_days = F.activation_threshold(act, "active_days_first_7d", k_max=7)
    scan_w = F.activation_threshold(act, "workouts_first_7d", k_max=10)
    best = F.best_activation_rule(act)
    _table(scan_days, "activation_scan_active_days")
    _table(scan_w, "activation_scan_workouts")
    m["activation"] = best
    figs.append(figures.activation(F.retention_by_bucket(act, "active_days_first_7d", cap=7), scan_days, scan_w, best))

    # experiments
    truth = json.loads(C.GROUND_TRUTH_PATH.read_text()) if C.GROUND_TRUTH_PATH.exists() else None
    pre = read("""SELECT signup_date, platform, d7_retained::INT AS d7_retained FROM dim_users
                  WHERE signup_date BETWEEN DATE '2025-07-01' AND DATE '2025-08-31'
                    AND platform IN ('ios', 'android')""")
    m["exp1_design"] = E.power_analysis(pre)
    e1 = E.analyze_onboarding(read("mart_exp_onboarding"))
    e2 = E.analyze_reminders(read("mart_exp_reminders"))

    # expected annual impact of shipping onboarding v2 to mobile
    econ = read("mart_channel_economics")
    n_mobile = int(read("""SELECT count(*) AS n FROM dim_users WHERE platform IN ('ios','android')
                           AND signup_date BETWEEN DATE '2025-01-01' AND DATE '2025-12-31'""")["n"].iloc[0])
    trial = next(s for s in e1["secondary"] if s["metric"].startswith("Trial"))
    conv = next(g for g in e1["guardrails"] if g["metric"].startswith("Trial"))["control"]
    ltv_paid = float((econ["ltv_24m_usd"] * econ["paid_subscribers"]).sum() / econ["paid_subscribers"].sum())
    p = e1["primary"]
    e1["impact"] = {
        "annual_mobile_signups": n_mobile,
        "extra_d7_retained_users": p["abs_diff"] * n_mobile,
        "extra_d7_retained_users_ci": [p["ci_low"] * n_mobile, p["ci_high"] * n_mobile],
        "extra_trials": trial["abs_diff"] * n_mobile,
        "extra_paid_subscribers": trial["abs_diff"] * n_mobile * conv,
        "extra_ltv_24m_usd": trial["abs_diff"] * n_mobile * conv * ltv_paid,
        "assumptions": "trial lift x control trial->paid rate x blended 24m LTV; trial lift CI is wide",
    }
    m["exp1"] = e1
    m["exp2"] = e2
    if truth:
        m["validation_vs_truth"] = E.compare_to_truth(e1, e2, truth)
    _table(pd.DataFrame(e1["segments"]), "exp1_segments")
    _table(pd.DataFrame(e2["weekly"]), "exp2_weekly_effects")
    figs.append(figures.exp1_srm(e1["srm_by_platform"]))
    if truth:
        figs.append(figures.exp1_effects(e1, truth["exp1"]))
        figs.append(figures.exp1_segments(e1, truth["exp1"]))
        figs.append(figures.exp2_cuped(e2, truth["exp2"]))
        figs.append(figures.exp2_novelty(e2, truth["exp2"]))

    # revenue
    mrr = read("mart_mrr_monthly")
    _table(mrr, "mrr_monthly")
    last = mrr.iloc[-1]
    m["revenue"] = {"mrr_end_usd": float(last["mrr_usd"]), "subscribers_end": int(last["subscribers"]),
                    "net_revenue_total_usd": float(mrr["net_revenue_usd"].sum()),
                    "avg_logo_churn_last_4m": float(mrr["logo_churn_rate"].iloc[-4:].mean())}
    figs.append(figures.mrr(mrr))

    # churn
    res = churn_model.run(read("mart_churn_features"))
    m["churn_model"] = res.summary
    _table(res.deciles, "churn_deciles")
    _table(res.importance, "churn_permutation_importance")
    _table(res.coefficients, "churn_logit_coefficients")
    _table(res.policy_sweep, "churn_offer_policy_sweep")
    figs += [figures.churn_performance(res), figures.churn_calibration_lift(res), figures.churn_importance(res),
             figures.offer_policy(res)]

    # marketing
    _table(econ, "channel_economics")
    cdaily = read("mart_channel_daily")
    curves = MK.response_curves(cdaily)
    opt = MK.optimise_budget(econ, curves)
    _table(curves, "spend_response_curves")
    _table(opt["table"], "budget_reallocation")
    m["marketing"] = {**MK.summarise(econ), "response_curves": curves.to_dict(orient="records"),
                      "reallocation": {k: v for k, v in opt.items() if k != "table"}}
    figs += [figures.unit_economics(econ), figures.spend_response(cdaily, curves), figures.budget_reallocation(opt)]

    # estimator validation
    if V.COVERAGE_PATH.exists():
        cov = pd.read_csv(V.COVERAGE_PATH)
        m["estimator_coverage"] = V.summarise(cov)
        figs.append(figures.estimator_coverage(cov))

    m["figures"] = [f.name for f in figs]
    m["runtime_s"] = round(time.time() - t0, 1)
    C.METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.METRICS_PATH.write_text(json.dumps(_clean_nan(json.loads(json.dumps(m, cls=_Encoder))), indent=2))
    return m


def main() -> None:
    m = run()
    print(f"wrote {len(m['figures'])} figures, tables and {C.METRICS_PATH.relative_to(C.ROOT)} "
          f"in {m['runtime_s']}s")


if __name__ == "__main__":
    main()
