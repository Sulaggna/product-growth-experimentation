"""Read-outs for the two experiments.

onboarding_v2: new users, binary metrics, SRM check, segments.
smart_reminders: existing users, heavy-tailed count metric, CUPED, bootstrap, novelty.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config as C
from . import stats as S

MOBILE = ["ios", "android"]


def _split(df: pd.DataFrame):
    return df[df["variant"] == "control"], df[df["variant"] == "treatment"]


def _prop(df: pd.DataFrame, col: str, label: str | None = None) -> S.Effect:
    d = df.dropna(subset=[col])
    c, t = _split(d)
    return S.two_proportion_test(int(c[col].sum()), len(c), int(t[col].sum()), len(t), label or col)


def _srm(df: pd.DataFrame) -> dict:
    c, t = _split(df)
    return S.srm_test(len(c), len(t))


# design: power analysis from pre-experiment data
def power_analysis(pre_users: pd.DataFrame, mde_abs: float = 0.025) -> dict:
    """Size experiment 1 from mobile cohorts that signed up before it (Jul-Aug 2025).

    ``pre_users`` needs columns signup_date, platform, d7_retained.
    """
    p = float(pre_users["d7_retained"].mean())
    n = S.sample_size_proportions(p, mde_abs, C.ALPHA, C.POWER)
    daily = float(pre_users.groupby("signup_date").size().mean())
    runtime = math.ceil(2 * n / daily)
    return {
        "baseline_cohorts": "mobile signups 2025-07-01 to 2025-08-31",
        "baseline_d7": p,
        "mde_abs": mde_abs,
        "mde_rel": mde_abs / p,
        "alpha": C.ALPHA,
        "power": C.POWER,
        "n_per_arm": n,
        "daily_eligible_signups": daily,
        "runtime_days_needed": runtime,
        "runtime_days_planned": (C.EXP1["end"] - C.EXP1["start"]).days + 1,
    }


# experiment 1: onboarding_v2
def analyze_onboarding(df: pd.DataFrame) -> dict:
    out: dict = {"n_exposed": len(df)}

    # sample ratio check, overall and per platform
    out["srm_overall"] = _srm(df)
    out["srm_by_platform"] = {p: _srm(df[df["platform"] == p]) for p in ["ios", "android", "web"]}

    # what a naive read would have said (web included, SRM ignored)
    out["naive_primary"] = _prop(df, "d7_retained", "D7 retention (all platforms, naive)").as_dict()
    out["web_only_primary"] = _prop(df[df["platform"] == "web"], "d7_retained", "D7 retention (web only, biased)").as_dict()

    # analysis population: iOS and Android (no SRM there)
    clean = df[df["platform"].isin(MOBILE)]
    out["analysis_population"] = "iOS + Android (web excluded: exposure-logging bug)"
    out["n_analysis"] = len(clean)
    out["achieved_mde"] = S.mde_proportions(clean.loc[clean["variant"] == "control", "d7_retained"].mean(),
                                            int(len(clean) / 2))
    primary = _prop(clean, "d7_retained", "D7 retention")
    out["primary"] = primary.as_dict()

    secondaries = [_prop(clean, "onboarded", "Onboarding completion"),
                   _prop(clean, "trial_7d", "Trial start <= 7 days"),
                   _prop(clean, "d30_retained", "D30 retention")]
    adj = S.holm([e.p_value for e in secondaries])
    out["secondary"] = [{**e.as_dict(), "p_holm": float(a)} for e, a in zip(secondaries, adj)]

    # guardrails. Pre-registered rule: a guardrail is breached if it gets significantly
    # worse (one-sided test, Holm-adjusted across guardrails). I also report whether the
    # CI stays inside the tolerated margin, because a non-significant result on an
    # underpowered guardrail does not mean it is safe.
    g_conv = _prop(clean, "trial_converted", "Trial-to-paid conversion")
    c, t = _split(clean)
    g_crash = S.ratio_metric_delta(c["crashes_7d"], c["sessions_7d"], t["crashes_7d"], t["sessions_7d"],
                                   "Crashes per session (7d)")
    guards = [(g_conv, -1, -0.03), (g_crash, +1, 0.001)]  # (effect, harmful direction, margin)
    one_sided = [g.p_value / 2 if np.sign(g.abs_diff) == d else 1 - g.p_value / 2 for g, d, _ in guards]
    adj = S.holm(one_sided)
    out["guardrails"] = []
    for (g, direction, margin), p1, pa in zip(guards, one_sided, adj):
        within = g.ci_low > margin if direction < 0 else g.ci_high < margin
        out["guardrails"].append({**g.as_dict(), "harm_p_one_sided": float(p1), "harm_p_holm": float(pa),
                                  "breached": bool(pa < C.ALPHA), "margin": margin,
                                  "ci_within_margin": bool(within)})

    # segment effects (exploratory, so BH-adjusted)
    seg_rows = []
    for dim in ["platform", "acquisition_channel"]:
        for level, sub in clean.groupby(dim):
            e = _prop(sub, "d7_retained", f"{dim}={level}")
            seg_rows.append({"dimension": dim, "segment": level, **e.as_dict()})
    seg = pd.DataFrame(seg_rows)
    seg["p_bh"] = S.benjamini_hochberg(seg["p_value"])
    out["segments"] = seg.to_dict(orient="records")

    # interaction test: Android lift minus iOS lift
    e_and = next(r for r in seg_rows if r["segment"] == "android")
    e_ios = next(r for r in seg_rows if r["segment"] == "ios")
    se_and = (e_and["ci_high"] - e_and["ci_low"]) / (2 * 1.959964)
    se_ios = (e_ios["ci_high"] - e_ios["ci_low"]) / (2 * 1.959964)
    dd = e_and["abs_diff"] - e_ios["abs_diff"]
    z = dd / math.hypot(se_and, se_ios)
    from scipy import stats as st
    out["interaction_android_vs_ios"] = {"diff_in_diff": dd, "z": z, "p_value": float(2 * st.norm.sf(abs(z)))}

    # decision
    guard_ok = not any(g["breached"] for g in out["guardrails"])
    out["decision"] = {
        "ship": bool(primary.significant and primary.abs_diff > 0 and guard_ok),
        "reason": ("Primary metric improved with the 95% CI excluding zero and no guardrail "
                   "showed significant harm." if primary.significant and guard_ok
                   else "Primary metric or guardrails did not meet the pre-registered bar."),
    }
    return out


# experiment 2: smart_reminders
def analyze_reminders(df: pd.DataFrame, n_boot: int = 4000) -> dict:
    c, t = _split(df)
    y, x = "workouts_28d", "pre_workouts"
    out: dict = {"n_exposed": len(df), "srm": _srm(df)}

    # pre-period balance: an "A/A" read on data collected before launch
    out["pre_period_balance"] = S.welch_diff(c[x], t[x], "Pre-period workouts (A/A)").as_dict()

    # heavy tail diagnostics
    allw = np.sort(df[y].to_numpy())[::-1]
    top10 = allw[: max(1, len(allw) // 10)].sum() / max(1, allw.sum())
    out["distribution"] = {
        "mean": float(allw.mean()), "median": float(np.median(allw)), "p99": float(np.quantile(allw, 0.99)),
        "share_zero": float((allw == 0).mean()), "top10pct_share_of_workouts": float(top10),
        "skewness": float(pd.Series(allw).skew()),
    }

    raw = S.welch_diff(c[y], t[y], "Workouts / user (28d), raw")
    raw_boot = S.bootstrap_diff_ci(c[y].to_numpy(), t[y].to_numpy(), n_boot=n_boot)
    cup, info = S.cuped_effect(c[y].to_numpy(), t[y].to_numpy(), c[x].to_numpy(), t[x].to_numpy(),
                               "Workouts / user (28d), CUPED")
    y_adj, _, _ = S.cuped(df[y].to_numpy(), df[x].to_numpy())
    is_c = (df["variant"] == "control").to_numpy()
    cup_boot = S.bootstrap_diff_ci(y_adj[is_c], y_adj[~is_c], n_boot=n_boot)

    out["raw"] = {**raw.as_dict(), "boot_ci_low": raw_boot[0], "boot_ci_high": raw_boot[1]}
    out["cuped"] = {**cup.as_dict(), "boot_ci_low": cup_boot[0], "boot_ci_high": cup_boot[1], **info}
    out["ci_width_reduction"] = 1 - (cup.ci_high - cup.ci_low) / (raw.ci_high - raw.ci_low)

    # secondary: active days, also CUPED-adjusted
    act, _ = S.cuped_effect(c["active_days_28d"].to_numpy(), t["active_days_28d"].to_numpy(),
                            c["pre_active_days"].to_numpy(), t["pre_active_days"].to_numpy(),
                            "Active days / user (28d), CUPED")
    out["secondary_active_days"] = act.as_dict()

    # novelty: weekly CUPED effects
    weekly = []
    for w in range(1, 5):
        col = f"workouts_wk{w}"
        e, _ = S.cuped_effect(c[col].to_numpy(), t[col].to_numpy(), c[x].to_numpy(), t[x].to_numpy(), f"week {w}")
        weekly.append({"week": w, **e.as_dict()})
    out["weekly"] = weekly

    # steady state: per-user average of weeks 3-4, a better guide to the long-run effect
    ss_c = (c["workouts_wk3"] + c["workouts_wk4"]) / 2
    ss_t = (t["workouts_wk3"] + t["workouts_wk4"]) / 2
    ss, _ = S.cuped_effect(ss_c.to_numpy(), ss_t.to_numpy(), c[x].to_numpy(), t[x].to_numpy(),
                           "Workouts / user / week (weeks 3-4), CUPED")
    out["steady_state_weekly"] = ss.as_dict()
    first = weekly[0]["abs_diff"]
    out["novelty_decay_share"] = float(1 - ss.abs_diff / first) if first > 0 else None

    out["decision"] = {
        "ship": bool(cup.significant and cup.abs_diff > 0),
        "reason": ("CUPED-adjusted lift is significant; plan on the smaller steady-state effect "
                   "(weeks 3-4), not the launch-week spike." if cup.significant else
                   "Effect not distinguishable from zero after variance reduction."),
    }
    return out


def compare_to_truth(exp1: dict, exp2: dict, truth: dict) -> dict:
    """Compare the estimates with the simulator's ground truth."""
    t1, t2 = truth["exp1"], truth["exp2"]
    p = exp1["primary"]
    se1 = (p["ci_high"] - p["ci_low"]) / (2 * 1.959964)
    cu = exp2["cuped"]
    se2 = (cu["ci_high"] - cu["ci_low"]) / (2 * 1.959964)
    raw = exp2["raw"]
    return {
        "exp1_d7": {"estimate": p["abs_diff"], "truth": t1["ate_d7_ios_android"],
                    "z_error": (p["abs_diff"] - t1["ate_d7_ios_android"]) / se1,
                    "ci_covers_truth": p["ci_low"] <= t1["ate_d7_ios_android"] <= p["ci_high"]},
        "exp1_naive_d7": {"estimate": exp1["naive_primary"]["abs_diff"], "truth_all_platforms": t1["ate_d7_all_assigned"]},
        "exp1_web_only": {"estimate": exp1["web_only_primary"]["abs_diff"], "truth": t1["ate_d7_by_platform"]["web"]},
        "exp2_workouts": {"estimate_cuped": cu["abs_diff"], "estimate_raw": raw["abs_diff"],
                          "truth": t2["ate_workouts_28d"], "z_error": (cu["abs_diff"] - t2["ate_workouts_28d"]) / se2,
                          "ci_covers_truth": cu["ci_low"] <= t2["ate_workouts_28d"] <= cu["ci_high"]},
        "exp2_weekly": {"estimate": [w["abs_diff"] for w in exp2["weekly"]], "truth": t2["ate_by_week"]},
    }
