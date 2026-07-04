"""Acquisition funnel, engagement summary and the activation ("aha moment") search."""

from __future__ import annotations

import numpy as np
import pandas as pd

STAGES = [
    ("signups", "Signed up"),
    ("onboarded", "Completed onboarding"),
    ("saw_paywall", "Saw paywall"),
    ("started_trial", "Started free trial"),
    ("subscribed", "Became paying subscriber"),
]


def funnel_table(mart_funnel: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Stage counts plus step-wise and cumulative conversion, optionally per segment.

    Stages are milestone *reach* rates (a few users reach the paywall without finishing
    onboarding), so step conversion is computed against the previous stage and the
    cumulative rate against signups.  Early-workout behaviour is analysed separately
    in :func:`activation_threshold` because it is not a sequential step.
    """
    cols = [c for c, _ in STAGES]
    keys = [by] if by else []
    agg = mart_funnel.groupby(keys)[cols].sum() if by else mart_funnel[cols].sum().to_frame().T
    rows = []
    for key, r in agg.iterrows():
        prev = None
        for col, label in STAGES:
            rows.append({
                **({by: key} if by else {}),
                "stage": label,
                "users": int(r[col]),
                "step_conversion": np.nan if prev is None else r[col] / r[prev],
                "cumulative_conversion": r[col] / r["signups"],
            })
            prev = col
    return pd.DataFrame(rows)


def biggest_drop(funnel: pd.DataFrame) -> dict:
    f = funnel.dropna(subset=["step_conversion"])
    worst = f.loc[f["step_conversion"].idxmin()]
    return {"stage": worst["stage"], "step_conversion": float(worst["step_conversion"])}


def activation_threshold(act: pd.DataFrame, feature: str = "workouts_first_7d",
                         outcome: str = "d30_retained", k_max: int = 10) -> pd.DataFrame:
    """Scan ">= k <feature> in the first week" rules for the one that best separates
    D30-retained users (Youden's J = TPR - FPR).  Correlational, not causal."""
    y = act[outcome].to_numpy().astype(bool)
    x = act[feature].to_numpy()
    rows = []
    for k in range(1, k_max + 1):
        hit = x >= k
        tpr = (hit & y).sum() / y.sum()
        fpr = (hit & ~y).sum() / (~y).sum()
        rows.append({
            "k": k,
            "share_users_reaching": hit.mean(),
            "retention_if_reached": y[hit].mean() if hit.any() else np.nan,
            "retention_if_not": y[~hit].mean() if (~hit).any() else np.nan,
            "precision": y[hit].mean() if hit.any() else np.nan,
            "recall_tpr": tpr,
            "fpr": fpr,
            "youden_j": tpr - fpr,
        })
    out = pd.DataFrame(rows)
    out["retention_ratio"] = out["retention_if_reached"] / out["retention_if_not"]
    return out


def retention_by_bucket(act: pd.DataFrame, feature: str = "workouts_first_7d", cap: int = 8,
                        outcome: str = "d30_retained") -> pd.DataFrame:
    b = act[feature].clip(upper=cap)
    g = act.groupby(b)[outcome].agg(["mean", "size"]).reset_index()
    g.columns = ["bucket", "retention", "users"]
    g["label"] = g["bucket"].astype(int).astype(str)
    g.loc[g["bucket"] == cap, "label"] = f"{cap}+"
    return g


def best_activation_rule(act: pd.DataFrame, features=("workouts_first_7d", "active_days_first_7d")) -> dict:
    """Pick the (feature, k) rule with the highest Youden's J across candidate features."""
    best = None
    for f in features:
        t = activation_threshold(act, f, k_max=10 if f.startswith("workouts") else 7)
        r = t.loc[t["youden_j"].idxmax()]
        cand = {"feature": f, "k": int(r["k"]), "youden_j": float(r["youden_j"]),
                "share_users_reaching": float(r["share_users_reaching"]),
                "retention_if_reached": float(r["retention_if_reached"]),
                "retention_if_not": float(r["retention_if_not"]),
                "retention_ratio": float(r["retention_ratio"])}
        if best is None or cand["youden_j"] > best["youden_j"]:
            best = cand
    return best


def engagement_summary(daily: pd.DataFrame, monthly: pd.DataFrame) -> dict:
    d = daily[daily["window_complete"]]
    last = monthly.iloc[-1]
    first = monthly.iloc[0]
    return {
        "avg_dau": float(d["dau"].mean()),
        "avg_mau": float(d["mau"].mean()),
        "avg_stickiness": float((d["dau"] / d["mau"]).mean()),
        "peak_dau": int(d["dau"].max()),
        "peak_dau_date": str(d.loc[d["dau"].idxmax(), "day"])[:10],
        "stickiness_first_month": float(first["stickiness"]),
        "stickiness_last_month": float(last["stickiness"]),
        "mau_last_month": int(last["mau"]),
        "months": int(len(monthly)),
    }
