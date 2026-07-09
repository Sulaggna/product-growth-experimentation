"""Marketing efficiency: unit economics, spend-response curves and budget reallocation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.optimize import minimize

PAID = ["paid_social", "search", "influencer"]


def response_curves(daily: pd.DataFrame) -> pd.DataFrame:
    """Log-log spend response per paid channel.

    log(signups) = a + b * log(spend) + month FE + weekday FE

    Budgets are raised in January when demand is also high, so month and weekday fixed
    effects are needed to separate the spend effect from seasonality. b is then the
    within-month elasticity, identified from day-to-day budget changes and influencer
    campaign bursts.
    """
    d = daily[daily["signups"] > 0].copy()
    d["month"] = pd.to_datetime(d["spend_date"]).dt.to_period("M").astype(str)
    d["dow"] = pd.to_datetime(d["spend_date"]).dt.day_name()
    rows = []
    for ch in PAID:
        sub = d[d["channel"] == ch]
        fit = smf.ols("np.log(signups) ~ np.log(spend_usd) + C(month) + C(dow)", data=sub).fit(cov_type="HC1")
        b = fit.params["np.log(spend_usd)"]
        se = fit.bse["np.log(spend_usd)"]
        avg_spend, avg_signups = sub["spend_usd"].mean(), sub["signups"].mean()
        rows.append({
            "channel": ch, "elasticity": b, "elasticity_ci_low": b - 1.96 * se, "elasticity_ci_high": b + 1.96 * se,
            "r2": fit.rsquared, "days": len(sub), "avg_daily_spend": avg_spend, "avg_daily_signups": avg_signups,
            "avg_cost_per_signup": sub["spend_usd"].sum() / sub["signups"].sum(),
            # d(spend)/d(signups) at the current operating point
            "marginal_cost_per_signup": avg_spend / (b * avg_signups),
        })
    return pd.DataFrame(rows)


def _scenario_table(econ: pd.DataFrame, curves: pd.DataFrame, new_spend: dict[str, float]) -> pd.DataFrame:
    e = econ.set_index("channel")
    rows = []
    for _, c in curves.iterrows():
        ch = c["channel"]
        old = e.loc[ch, "spend_usd"]
        new = new_spend[ch]
        signups_old = e.loc[ch, "signups"]
        signups_new = signups_old * (new / old) ** c["elasticity"]
        paid_rate = e.loc[ch, "signup_to_paid_rate"]
        ltv = e.loc[ch, "ltv_24m_usd"]
        rows.append({"channel": ch, "spend_old": old, "spend_new": new, "signups_old": signups_old,
                     "signups_new": signups_new, "paid_old": signups_old * paid_rate,
                     "paid_new": signups_new * paid_rate, "ltv_old": signups_old * paid_rate * ltv,
                     "ltv_new": signups_new * paid_rate * ltv})
    return pd.DataFrame(rows)


def optimise_budget(econ: pd.DataFrame, curves: pd.DataFrame, bounds_mult=(0.5, 2.0)) -> dict:
    """Maximise 24-month LTV at the same total budget.

    Spend per channel is bounded to 0.5x-2x of the current level, because the
    elasticities are only reliable near the spend range that was observed.
    """
    e = econ.set_index("channel")
    chans = list(curves["channel"])
    old = np.array([e.loc[c, "spend_usd"] for c in chans])
    budget = old.sum()
    b = curves.set_index("channel").loc[chans, "elasticity"].to_numpy()
    value_per_signup = np.array([e.loc[c, "signup_to_paid_rate"] * e.loc[c, "ltv_24m_usd"] for c in chans])
    signups_old = np.array([e.loc[c, "signups"] for c in chans])

    def neg_value(s):
        return -np.sum(value_per_signup * signups_old * (s / old) ** b)

    res = minimize(neg_value, old, method="SLSQP",
                   bounds=[(bounds_mult[0] * o, bounds_mult[1] * o) for o in old],
                   constraints=[{"type": "eq", "fun": lambda s: s.sum() - budget}])
    table = _scenario_table(econ, curves, dict(zip(chans, res.x)))
    tot = table[["spend_old", "spend_new", "paid_old", "paid_new", "ltv_old", "ltv_new"]].sum()
    return {
        "table": table,
        "budget": float(budget),
        "paid_subscribers_change": float(tot["paid_new"] - tot["paid_old"]),
        "paid_subscribers_change_pct": float(tot["paid_new"] / tot["paid_old"] - 1),
        "ltv_change_usd": float(tot["ltv_new"] - tot["ltv_old"]),
        "ltv_change_pct": float(tot["ltv_new"] / tot["ltv_old"] - 1),
        "blended_cac_old": float(tot["spend_old"] / tot["paid_old"]),
        "blended_cac_new": float(tot["spend_new"] / tot["paid_new"]),
        "converged": bool(res.success),
    }


def summarise(econ: pd.DataFrame) -> dict:
    paid = econ[econ["channel"].isin(PAID)]
    best = paid.loc[paid["ltv_to_cac"].idxmax()]
    worst = paid.loc[paid["ltv_to_cac"].idxmin()]
    return {
        "total_spend_usd": float(econ["spend_usd"].sum()),
        "blended_cac_usd": float(paid["spend_usd"].sum() / paid["paid_subscribers"].sum()),
        "best_channel": best["channel"], "best_ltv_to_cac": float(best["ltv_to_cac"]),
        "worst_channel": worst["channel"], "worst_ltv_to_cac": float(worst["ltv_to_cac"]),
        "by_channel": econ.to_dict(orient="records"),
    }
