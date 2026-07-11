"""Every figure in reports/figures, one function each.  Titles state the finding."""

from __future__ import annotations

import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from scipy import stats as st

from . import plotting as P
from .plotting import BLUE, INK, INK_2, MUTED, SERIES, figure, headline, save


def _date_axis(ax):
    loc = mdates.MonthLocator(bymonth=[1, 3, 5, 7, 9, 11])
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc, show_offset=False))


# engagement & acquisition
def engagement_trend(daily: pd.DataFrame):
    d = daily[daily["window_complete"]].copy()
    d["day"] = pd.to_datetime(d["day"])
    d["stick"] = d["dau"] / d["mau"]
    fig, (a1, a2) = figure(2, 1, h=6.0, sharex=True)
    a1.plot(d["day"], d["dau_7d_avg"], color=SERIES[0])
    a1.set_title("Daily active users, 7-day average")
    a1.yaxis.set_major_formatter(P.thousands())
    a1.set_ylim(0, None)
    a2.plot(d["day"], d["stick"].rolling(7, min_periods=1).mean(), color=SERIES[0])
    a2.set_title("Stickiness: DAU / MAU, 7-day average")
    a2.yaxis.set_major_formatter(P.pct(0))
    a2.set_ylim(0, None)
    _date_axis(a2)
    first, last = d["stick"].iloc[:14].mean(), d["stick"].iloc[-14:].mean()
    headline(fig, "Stickiness improved while the user base churned and refilled",
             f"DAU/MAU rose from {first:.0%} to {last:.0%}; the New-Year waves lift DAU but bring less sticky users")
    return save(fig, "01_engagement_trend")


def acquisition_by_channel(weekly: pd.DataFrame):
    w = weekly.copy()
    w["week"] = pd.to_datetime(w["week"])
    w = w[w["week"] < w["week"].max()]  # drop partial final week
    fig, ax = figure(h=4.6)
    order = ["organic", "paid_social", "search", "influencer", "referral"]
    ends = []
    for ch in order:
        s = w[w["acquisition_channel"] == ch].sort_values("week")
        ax.plot(s["week"], s["signups"], color=P.CHANNEL_COLOR[ch], label=P.LABEL[ch], lw=1.8)
        ends.append((s["week"].iloc[-1] + pd.Timedelta(days=4), s["signups"].iloc[-1], P.LABEL[ch]))
    ax.yaxis.set_major_formatter(P.thousands())
    ax.set_ylim(0, None)
    P.end_labels(ax, ends, min_gap_frac=0.065)
    ax.set_ylabel("signups per week")
    _date_axis(ax)
    ax.legend(loc="upper center", ncol=5, bbox_to_anchor=(0.5, 1.02))
    headline(fig, "Acquisition is seasonal: two New-Year waves and burst-driven influencer spend",
             "Weekly signups by acquisition channel")
    return save(fig, "02_acquisition_by_channel")


def funnel(f_all: pd.DataFrame, by_channel: pd.DataFrame):
    fig, (a1, a2) = figure(1, 2, h=4.4, gridspec_kw={"width_ratios": [1.35, 1]})
    f = f_all.iloc[::-1]
    a1.barh(f["stage"], f["cumulative_conversion"], color=SERIES[0], height=0.55)
    for i, (_, r) in enumerate(f.iterrows()):
        step = "" if np.isnan(r["step_conversion"]) else f"   ({r['step_conversion']:.0%} of previous)"
        a1.text(r["cumulative_conversion"] + 0.01, i, f"{r['cumulative_conversion']:.1%}{step}", va="center",
                fontsize=8.5, color=INK_2)
    a1.set_xlim(0, 1.45)
    a1.xaxis.set_major_formatter(P.pct(0))
    a1.grid(axis="y", visible=False)
    a1.grid(axis="x", visible=True)
    a1.set_title("Share of signups reaching each stage")
    a1.set_xticks([0, 0.25, 0.5, 0.75, 1.0])

    paid = by_channel[by_channel["stage"] == "Became paying subscriber"].sort_values("cumulative_conversion")
    a2.barh([P.LABEL[c] for c in paid["acquisition_channel"]], paid["cumulative_conversion"], color=SERIES[0],
            height=0.55)
    for i, v in enumerate(paid["cumulative_conversion"]):
        a2.text(v + 0.002, i, f"{v:.1%}", va="center", fontsize=8.5, color=INK_2)
    a2.xaxis.set_major_formatter(P.pct(0))
    a2.grid(axis="y", visible=False)
    a2.grid(axis="x", visible=True)
    a2.set_xlim(0, paid["cumulative_conversion"].max() * 1.25)
    a2.set_title("Signup to paid, by channel")
    drop = f_all.dropna(subset=["step_conversion"]).sort_values("step_conversion").iloc[0]
    headline(fig, f"The paywall-to-trial step is the leak: only {drop['step_conversion']:.0%} start a trial",
             "Acquisition funnel for cohorts with a fully observed 30-day window")
    return save(fig, "03_funnel")


def cohort_heatmap(cr: pd.DataFrame):
    c = cr[(cr["week_since_signup"] >= 1)].copy()
    c["cohort"] = pd.to_datetime(c["cohort_month"]).dt.strftime("%b %Y")
    order = c.drop_duplicates("cohort_month").sort_values("cohort_month")["cohort"]
    piv = c.pivot(index="cohort", columns="week_since_signup", values="retention_rate").loc[order]
    fig, ax = figure(h=5.6, w=10)
    im = ax.imshow(piv.to_numpy(), cmap=P.SEQ_CMAP, vmin=0, vmax=0.4, aspect="auto")
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.iat[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v * 100:.0f}", ha="center", va="center", fontsize=7.5,
                        color="#ffffff" if v > 0.22 else INK)
    ax.set_xticks(range(piv.shape[1]), [f"W{w}" for w in piv.columns])
    ax.set_yticks(range(piv.shape[0]), piv.index)
    ax.grid(False)
    ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.01, format=P.pct(0))
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=MUTED, labelcolor=INK_2, labelsize=8)
    ax.set_xlabel("weeks since signup  (cells: % of cohort active that week; blank = not yet observed)")
    jan, later = piv.iloc[0, 3], piv.iloc[1:9, 3].mean()
    headline(fig, "January cohorts churn fastest; retention flattens after week 6",
             f"Week-4 retention: Jan 2025 cohort {jan:.0%} vs {later:.0%} for Feb-Sep cohorts")
    return save(fig, "04_cohort_retention")


def retention_curves(rc: pd.DataFrame):
    fig, ax = figure(h=4.6)
    order = ["referral", "organic", "search", "paid_social", "influencer"]
    ends = []
    for ch in order:
        s = rc[rc["acquisition_channel"] == ch].sort_values("day_n")
        ax.plot(s["day_n"], s["retention_rate"], color=P.CHANNEL_COLOR[ch], marker="o", ms=5, mec=P.SURFACE,
                label=P.LABEL[ch])
        ends.append((s["day_n"].iloc[-1] + 2, s["retention_rate"].iloc[-1], P.LABEL[ch]))
    ax.set_xticks([1, 7, 14, 30, 60, 90], ["D1", "D7", "D14", "D30", "D60", "D90"])
    ax.yaxis.set_major_formatter(P.pct(0))
    ax.set_ylim(0, None)
    ax.set_xlim(0, 96)  # 5 converging series: the legend carries identity
    ax.legend(loc="upper right", ncol=5, bbox_to_anchor=(1.0, 1.06))
    r = rc[rc["day_n"] == 30].set_index("acquisition_channel")["retention_rate"]
    headline(fig, f"Referral users retain {r['referral'] / r['influencer']:.1f}x better than influencer users at D30",
             "Dn retention = active at least once in days n to n+6 after signup")
    return save(fig, "05_retention_by_channel")


def activation(bucket: pd.DataFrame, scan_days: pd.DataFrame, scan_workouts: pd.DataFrame, best: dict):
    fig, (a1, a2) = figure(1, 2, h=4.4)
    k = best["k"] if best["feature"] == "active_days_first_7d" else 3
    colors = [SERIES[0] if b >= k else P.BASELINE for b in bucket["bucket"]]
    a1.bar(bucket["label"], bucket["retention"], color=colors, width=0.62)
    for x, v in zip(bucket["label"], bucket["retention"]):
        a1.text(x, v + 0.008, f"{v:.0%}", ha="center", fontsize=8.5, color=INK_2)
    a1.yaxis.set_major_formatter(P.pct(0))
    a1.set_xlabel("active days in the first 7 days (incl. signup day)")
    a1.set_title("D30 retention by first-week active days")
    a2.plot(scan_days["k"], scan_days["youden_j"], color=SERIES[0], marker="o", ms=5, mec=P.SURFACE,
            label=">= k active days")
    a2.plot(scan_workouts["k"], scan_workouts["youden_j"], color=SERIES[1], marker="o", ms=5, mec=P.SURFACE,
            label=">= k workouts")
    a2.set_xlabel("threshold k (first 7 days)")
    a2.set_title("How well each rule separates D30 retainers (Youden's J)")
    a2.legend(loc="upper right")
    a2.set_ylim(0, None)
    a2.annotate(f"best: {k}+ active days (J = {best['youden_j']:.2f})", (best["k"], best["youden_j"]),
                xytext=(10, -2), textcoords="offset points", va="center", fontsize=8.5, color=INK_2)
    headline(fig, f"'Aha moment': users active on {k}+ of their first 7 days retain "
                  f"{best['retention_ratio']:.1f}x better",
             f"{best['share_users_reaching']:.0%} of new users reach it; D30 retention {best['retention_if_reached']:.0%} "
             f"vs {best['retention_if_not']:.0%}. It is a correlation, so it needs an experiment to confirm")
    return save(fig, "06_activation_threshold")


# experiment 1
def exp1_srm(srm_by_platform: dict):
    fig, ax = figure(h=3.4)
    names = ["ios", "android", "web"]
    for i, p in enumerate(names):
        r = srm_by_platform[p]
        n = r["n_control"] + r["n_treatment"]
        s = r["share_treatment"]
        se = np.sqrt(s * (1 - s) / n)
        bad = r["p_value"] < 0.001
        c = P.STATUS["critical"] if bad else SERIES[0]
        y = 2 - i
        ax.plot([s - 1.96 * se, s + 1.96 * se], [y, y], color=c, lw=2)
        ax.plot([s], [y], "o", color=c, ms=8, mec=P.SURFACE, mew=2)
        tag = "SRM detected, p < 0.001" if bad else f"OK, p = {r['p_value']:.2f}"
        ax.text(s + 1.96 * se + 0.004, y, f"  {s:.1%} treatment, n={n:,}, {tag}", va="center", fontsize=8.5,
                color=INK_2)
    ax.axvline(0.5, color=P.BASELINE, lw=1)
    ax.set_yticks([2, 1, 0], [P.LABEL[p] for p in names])
    ax.xaxis.set_major_formatter(P.pct(0))
    ax.set_xlim(0.28, 0.62)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlabel("share of exposed users in treatment (expected 50%) with 95% CI")
    headline(fig, "Sample-ratio mismatch on web only: 1 in 2 treatment users never got logged",
             "The new web flow fired its exposure event after a heavy asset load, so fast bouncers were lost")
    return save(fig, "07_exp1_srm")


def exp1_effects(e1: dict, truth: dict):
    rows = [("D7 retention, naive, all platforms", e1["naive_primary"], SERIES[1], truth["ate_d7_all_assigned"]),
            ("D7 retention, PRIMARY (iOS + Android)", e1["primary"], SERIES[0], truth["ate_d7_ios_android"])]
    for s in e1["secondary"]:
        rows.append((f"{s['metric']} (secondary)", s, SERIES[0],
                     truth["ate_onboarding_ios_android"] if s["metric"].startswith("Onboarding") else
                     truth["ate_d30_ios_android"] if s["metric"].startswith("D30") else None))
    for g in e1["guardrails"]:
        rows.append((f"{g['metric']} (guardrail)", g, SERIES[2], None))
    fig, ax = figure(h=4.8)
    P.forest(ax, [r[0] for r in rows], [r[1]["abs_diff"] for r in rows], [r[1]["ci_low"] for r in rows],
             [r[1]["ci_high"] for r in rows], colors=[r[2] for r in rows], fmt=P.pp(0),
             value_fmt=lambda e, lo, hi: f"{e * 100:+.1f} pp [{lo * 100:+.1f}, {hi * 100:+.1f}]",
             truth=[r[3] for r in rows])
    ax.set_xlabel("treatment - control (percentage points), 95% CI")
    ax.set_xlim(-0.09, 0.2)
    p = e1["primary"]
    headline(fig, f"Onboarding v2 lifts D7 retention by {p['abs_diff'] * 100:+.1f} pp "
                  f"({p['rel_diff']:+.0%}) with no guardrail breach",
             "Ship. The trial-to-paid guardrail is under-powered (CI reaches -7 pp): keep monitoring after launch")
    return save(fig, "08_exp1_effects")


def exp1_segments(e1: dict, truth: dict):
    seg = pd.DataFrame(e1["segments"])
    tp, tc = truth["ate_d7_by_platform"], truth["ate_d7_by_channel_ios_android"]
    labels, colors, tr = [], [], []
    for _, r in seg.iterrows():
        dim = "Platform" if r["dimension"] == "platform" else "Channel"
        pbh = "<0.001" if r["p_bh"] < 0.001 else f"={r['p_bh']:.3f}"
        labels.append(f"{dim}: {P.LABEL[r['segment']]}   (BH p{pbh})")
        colors.append(SERIES[0] if dim == "Platform" else SERIES[1])
        tr.append(tp.get(r["segment"]) if dim == "Platform" else tc.get(r["segment"]))
    fig, ax = figure(h=4.6)
    P.forest(ax, labels, seg["abs_diff"], seg["ci_low"], seg["ci_high"], colors=colors, fmt=P.pp(0), truth=tr)
    ax.axvline(e1["primary"]["abs_diff"], color=MUTED, lw=1)
    ax.text(e1["primary"]["abs_diff"], len(seg) - 0.45, " overall", fontsize=8.5, color=INK_2)
    ax.set_xlabel("D7 retention lift (pp), 95% CI")
    inter = e1["interaction_android_vs_ios"]
    headline(fig, "Android drives the lift; iOS barely moves",
             f"Android lift minus iOS lift = {inter['diff_in_diff'] * 100:+.1f} pp (interaction p = {inter['p_value']:.3f}). "
             "Channel splits are exploratory (Benjamini-Hochberg adjusted)")
    return save(fig, "09_exp1_segments")


# experiment 2
def exp2_cuped(e2: dict, truth: dict):
    r, c = e2["raw"], e2["cuped"]
    rows = [("Raw difference, Welch t", r["abs_diff"], r["ci_low"], r["ci_high"], SERIES[1]),
            ("Raw difference, bootstrap", r["abs_diff"], r["boot_ci_low"], r["boot_ci_high"], SERIES[1]),
            ("CUPED-adjusted, Welch t", c["abs_diff"], c["ci_low"], c["ci_high"], SERIES[0]),
            ("CUPED-adjusted, bootstrap", c["abs_diff"], c["boot_ci_low"], c["boot_ci_high"], SERIES[0])]
    fig, ax = figure(h=3.8)
    P.forest(ax, [x[0] for x in rows], [x[1] for x in rows], [x[2] for x in rows], [x[3] for x in rows],
             colors=[x[4] for x in rows],
             value_fmt=lambda e, lo, hi: f"{e:+.2f} [{lo:+.2f}, {hi:+.2f}]")
    t = truth["ate_workouts_28d"]
    ax.axvline(t, color=INK, lw=1)
    ax.text(t, 3.55, " simulated truth", fontsize=8.5, color=INK_2)
    ax.set_xlabel("extra workouts per user over 28 days (treatment - control), 95% CI")
    ax.set_xlim(-0.3, 2.3)
    bal = e2["pre_period_balance"]
    headline(fig, f"CUPED removes a chance imbalance and cuts variance by {c['variance_reduction']:.0%}",
             f"Treatment users already did {bal['abs_diff']:+.2f} more workouts before launch (p = {bal['p_value']:.2f}); "
             f"the raw read overstated the lift by about {r['abs_diff'] / c['abs_diff']:.1f}x")
    return save(fig, "10_exp2_cuped")


def exp2_novelty(e2: dict, truth: dict):
    w = pd.DataFrame(e2["weekly"])
    fig, ax = figure(h=4.2)
    ax.axhline(0, color=P.BASELINE, lw=1)
    ax.fill_between(w["week"], w["ci_low"], w["ci_high"], color=BLUE[150], lw=0, label="95% CI (CUPED)")
    ax.plot(w["week"], w["abs_diff"], color=SERIES[0], marker="o", ms=7, mec=P.SURFACE, mew=2, label="estimate")
    ax.plot(w["week"], truth["ate_by_week"], ls="none", marker="D", ms=6, mfc=P.SURFACE, mec=INK, mew=1.2,
            label="simulated truth")
    ax.set_xticks([1, 2, 3, 4], ["Week 1", "Week 2", "Week 3", "Week 4"])
    ax.set_ylabel("extra workouts per user per week")
    ax.legend(loc="upper right")
    headline(fig, f"Novelty effect: the week-1 lift is about {e2['novelty_decay_share']:.0%} smaller by weeks 3-4",
             "Forecast impact from the steady-state weeks, not the launch spike")
    return save(fig, "11_exp2_novelty")


# revenue
def mrr(m: pd.DataFrame):
    d = m.copy()
    d["month_start"] = pd.to_datetime(d["month_start"])
    fig, (a1, a2) = figure(2, 1, h=6.0, sharex=True)
    a1.plot(d["month_start"], d["mrr_usd"], color=SERIES[0], marker="o", ms=5, mec=P.SURFACE)
    a1.yaxis.set_major_formatter(P.usd(0))
    a1.set_ylim(0, None)
    a1.set_title("Monthly recurring revenue (month end)")
    width = 18
    a2.bar(d["month_start"], d["new_mrr_usd"], width=width, color=P.POS, label="New MRR")
    a2.bar(d["month_start"], -d["churned_mrr_usd"], width=width, color=P.NEG, label="Churned MRR")
    a2.axhline(0, color=P.BASELINE, lw=1)
    a2.yaxis.set_major_formatter(P.usd(0))
    a2.set_title("MRR movements")
    a2.legend(loc="upper right", ncol=2, bbox_to_anchor=(1.0, 1.16))
    _date_axis(a2)
    last = d.iloc[-1]
    late = d["churned_mrr_usd"].iloc[-3:].sum() / d["new_mrr_usd"].iloc[-3:].sum()
    early = d["churned_mrr_usd"].iloc[1:4].sum() / d["new_mrr_usd"].iloc[1:4].sum()
    headline(fig, f"MRR grew to ${last['mrr_usd']:,.0f} as monthly churn settled near "
                  f"{d['logo_churn_rate'].iloc[-4:].mean():.0%}",
             f"Churn now erases {late:.0%} of new MRR each month (vs {early:.0%} in Feb-Apr): "
             "retention is the next growth lever")
    return save(fig, "12_mrr")


def churn_performance(res):
    fig, (a1, a2) = figure(1, 2, h=4.4)
    base = res.summary["base_rate_test"]
    for name, cv in res.curves.items():
        auc = res.summary["models"][name]["test_roc_auc"]
        ap = res.summary["models"][name]["test_pr_auc"]
        a1.plot(cv["fpr"], cv["tpr"], color=P.MODEL_COLOR[name], label=f"{name} (AUC {auc:.2f})")
        a2.plot(cv["recall"], cv["precision"], color=P.MODEL_COLOR[name], label=f"{name} (AP {ap:.2f})")
    a1.plot([0, 1], [0, 1], color=P.BASELINE, lw=1)
    a2.axhline(base, color=P.BASELINE, lw=1)
    a2.text(0.98, base + 0.015, f"base rate {base:.0%}", ha="right", fontsize=8.5, color=INK_2)
    a1.set_xlabel("false-positive rate")
    a1.set_ylabel("true-positive rate")
    a1.set_title("ROC")
    a2.set_xlabel("recall")
    a2.set_ylabel("precision")
    a2.set_title("Precision-recall")
    for a in (a1, a2):
        a.legend(loc="lower right" if a is a1 else "upper right")
        a.grid(axis="x", visible=True)
    s = res.summary
    headline(fig, "Simple beats complex: logistic regression edges gradient boosting out of time",
             f"Trained on subscriptions started before {s['split_date']}, tested on {s['n_test']:,} later ones")
    return save(fig, "13_churn_model_performance")


def churn_calibration_lift(res):
    fig, (a1, a2) = figure(1, 2, h=4.4)
    cal = res.calibration
    a1.plot([0, 0.8], [0, 0.8], color=P.BASELINE, lw=1)
    a1.plot(cal["mean_predicted"], cal["observed_rate"], color=SERIES[0], marker="o", ms=6, mec=P.SURFACE)
    a1.xaxis.set_major_formatter(P.pct(0))
    a1.yaxis.set_major_formatter(P.pct(0))
    a1.set_xlabel("predicted churn probability (decile mean)")
    a1.set_ylabel("observed churn rate")
    a1.set_title("Calibration (test period)")
    a1.grid(axis="x", visible=True)
    d = res.deciles
    a2.bar(d["decile"].astype(str), d["churn_rate"], color=SERIES[0], width=0.62)
    a2.axhline(res.summary["base_rate_test"], color=MUTED, lw=1)
    a2.text(9.4, res.summary["base_rate_test"] + 0.012, "base rate", ha="right", fontsize=8.5, color=INK_2)
    a2.yaxis.set_major_formatter(P.pct(0))
    a2.set_xlabel("risk decile (1 = highest predicted risk)")
    a2.set_title("Observed churn by risk decile")
    headline(fig, f"Top-decile subscribers churn {res.summary['top_decile_lift']:.1f}x the base rate",
             f"The riskiest 30% contain {res.summary['top_30pct_capture']:.0%} of churners; probabilities are well calibrated")
    return save(fig, "14_churn_calibration_lift")


def churn_importance(res, top: int = 10):
    imp = res.importance.head(top).iloc[::-1]
    nice = {"active_days_14d": "Active days (first 14d)", "workouts_wk2": "Workouts in week 2",
            "workouts_wk1": "Workouts in week 1", "acquisition_channel": "Acquisition channel",
            "region": "Region", "trial_workouts": "Workouts during trial", "age_band": "Age band",
            "sessions_14d": "Sessions (first 14d)", "workouts_14d": "Workouts (first 14d)",
            "workout_trend": "Workout trend (wk2 - wk1)", "days_since_last_active": "Days since last active",
            "platform": "Platform", "device_tier": "Device tier", "crashes_14d": "Crashes (first 14d)",
            "workouts_started_14d": "Workouts started (14d)", "days_signup_to_subscribe": "Days from signup to subscribing"}
    fig, ax = figure(h=4.6, w=9)
    ax.barh([nice.get(f, f) for f in imp["feature"]], imp["importance"], xerr=imp["std"], color=SERIES[0],
            height=0.55, error_kw={"ecolor": MUTED, "elinewidth": 1, "capsize": 0})
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlabel("drop in test ROC-AUC when the feature is shuffled (permutation importance)")
    headline(fig, "Early habit, not demographics, predicts churn",
             "Active days and week-2 workouts carry most of the signal, the same habit loop as activation")
    return save(fig, "15_churn_importance")


def offer_policy(res):
    sw = res.policy_sweep
    pol = res.summary["policy"]
    fig, ax = figure(h=4.2)
    ax.plot(sw["threshold"], sw["test_value_per_1k"], color=SERIES[0], label="test period (realised)")
    ax.plot(sw["threshold"], sw["train_value_per_1k"], color=SERIES[1], label="train, out-of-fold (used to choose)")
    ax.axhline(pol["value_per_1k_target_all"], color=MUTED, lw=1)
    ax.text(0.9, pol["value_per_1k_target_all"] + 25, "offer to everyone", ha="right", fontsize=8.5, color=INK_2)
    ax.axhline(0, color=P.BASELINE, lw=1)
    ax.axvline(pol["threshold"], color=INK, lw=1)
    ax.text(pol["threshold"], 0.04, f"  chosen threshold {pol['threshold']:.2f}", fontsize=8.5,
            color=INK_2, va="bottom", transform=ax.get_xaxis_transform())
    ax.yaxis.set_major_formatter(P.usd(0))
    ax.set_xlabel("target subscribers whose predicted churn probability >= threshold")
    ax.set_ylabel("net value per 1,000 subscribers")
    ax.legend(loc="upper right")
    headline(fig, f"Targeting the offer adds ${pol['value_per_1k_model']:,.0f} per 1,000 subscribers, "
                  f"{pol['value_per_1k_model'] / pol['value_per_1k_target_all']:.1f}x a blanket discount",
             f"Offer {pol['share_targeted']:.0%} of subscribers; break-even churn probability about {pol['breakeven_probability']:.2f}")
    return save(fig, "16_retention_offer_policy")


# marketing
def unit_economics(econ: pd.DataFrame):
    e = econ[econ["cac_usd"].notna()].sort_values("ltv_to_cac", ascending=True)
    fig, (a1, a2) = figure(1, 2, h=3.8)
    names = [P.LABEL[c] for c in e["channel"]]
    a1.barh(names, e["ltv_to_cac"], color=SERIES[0], height=0.55)
    a1.axvline(1, color=INK, lw=1)
    a1.text(1, -0.42, " break-even", fontsize=8.5, color=INK_2, va="center")
    for i, v in enumerate(e["ltv_to_cac"]):
        a1.text(v + 0.04, i, f"{v:.2f}x", va="center", fontsize=8.5, color=INK_2)
    a1.set_title("24-month LTV : CAC")
    a1.set_xlim(0, e["ltv_to_cac"].max() * 1.3)
    a2.barh(names, e["payback_months"].fillna(0), color=SERIES[0], height=0.55)
    for i, v in enumerate(e["payback_months"]):
        a2.text((0 if np.isnan(v) else v) + 0.3, i, "never pays back" if np.isnan(v) else f"{v:.1f} months",
                va="center", fontsize=8.5, color=INK_2)
    a2.set_title("CAC payback")
    a2.set_xlim(0, np.nanmax(e["payback_months"]) * 1.45)
    for a in (a1, a2):
        a.grid(axis="y", visible=False)
        a.grid(axis="x", visible=True)
    best, worst = e.iloc[-1], e.iloc[0]
    headline(fig, f"{P.LABEL[best['channel']]} returns {best['ltv_to_cac']:.1f}x its cost; "
                  f"{P.LABEL[worst['channel']].lower()} loses money",
             f"CAC: {', '.join(f'{P.LABEL[c]} ${v:,.0f}' for c, v in zip(e['channel'], e['cac_usd']))}")
    return save(fig, "17_channel_unit_economics")


def spend_response(daily: pd.DataFrame, curves: pd.DataFrame):
    fig, axes = figure(1, 3, h=3.8, sharey=False)
    for ax, (_, c) in zip(axes, curves.iterrows()):
        ch = c["channel"]
        d = daily[(daily["channel"] == ch) & (daily["signups"] > 0)]
        ax.scatter(d["spend_usd"], d["signups"], s=10, color=P.CHANNEL_COLOR[ch], alpha=0.55, lw=0)
        x = np.linspace(d["spend_usd"].quantile(0.02), d["spend_usd"].quantile(0.98), 50)
        # display curve: elasticity from the FE model, anchored at the channel's average day
        y = c["avg_daily_signups"] * (x / c["avg_daily_spend"]) ** c["elasticity"]
        ax.plot(x, y, color=INK, lw=1.5)
        ax.set_title(P.LABEL[ch])
        ax.text(0.04, 0.93, f"elasticity {c['elasticity']:.2f}\nmarginal cost / signup ${c['marginal_cost_per_signup']:.2f}",
                transform=ax.transAxes, va="top", fontsize=8.5, color=INK_2)
        ax.xaxis.set_major_formatter(P.usd(0))
        ax.set_xlabel("daily spend")
        ax.grid(axis="x", visible=True)
    axes[0].set_ylabel("signups that day")
    headline(fig, "Every paid channel shows diminishing returns",
             "Elasticity < 1: doubling spend buys fewer than double the signups (month and weekday fixed effects)")
    return save(fig, "18_spend_response")


def budget_reallocation(opt: dict):
    t = opt["table"]
    fig, ax = figure(h=3.8, w=9)
    x = np.arange(len(t))
    ax.bar(x - 0.18, t["spend_old"], width=0.34, color=SERIES[0], label="current spend")
    ax.bar(x + 0.18, t["spend_new"], width=0.34, color=SERIES[1], label="optimised spend (same total)")
    ax.set_xticks(x, [P.LABEL[c] for c in t["channel"]])
    ax.yaxis.set_major_formatter(P.usd(0))
    ax.legend(loc="upper right")
    for i, r in t.iterrows():
        ax.text(i + 0.18, r["spend_new"], f"\n{r['paid_new'] - r['paid_old']:+.0f} subs", ha="center", va="bottom",
                fontsize=8.5, color=INK_2)
    headline(fig, f"Same budget, {opt['paid_subscribers_change_pct']:+.0%} paying subscribers and "
                  f"{opt['ltv_change_pct']:+.0%} LTV by shifting influencer to search",
             f"Blended CAC ${opt['blended_cac_old']:.0f} to ${opt['blended_cac_new']:.0f}; spend bounded to 0.5-2x today "
             "to stay within observed range")
    return save(fig, "19_budget_reallocation")


def estimator_coverage(cov: pd.DataFrame):
    fig, (a1, a2) = figure(1, 2, h=3.8)
    grid = np.linspace(-4, 4, 200)
    for ax, col, title in [(a1, "exp1_z", "Onboarding v2: D7 lift"), (a2, "exp2_z", "Smart reminders: CUPED lift")]:
        z = cov[col].to_numpy()
        counts, _, _ = ax.hist(z, bins=np.arange(-4, 4.01, 0.5), density=True, color=BLUE[300],
                               edgecolor=P.SURFACE, lw=2)
        ax.set_ylim(0, max(counts.max(), 0.4) * 1.45)
        ax.plot(grid, st.norm.pdf(grid), color=INK, lw=1.2)
        covered = (np.abs(z) <= 1.96).mean()
        ax.set_title(title)
        ax.text(0.03, 0.93, f"95% CI covered the truth in {covered:.0%} of {len(z)} runs\nmean error {z.mean():+.2f} SE",
                transform=ax.transAxes, va="top", fontsize=8.5, color=INK_2)
        ax.set_xlabel("(estimate - truth) / standard error")
        ax.set_yticks([])
    c1, c2 = (np.abs(cov["exp1_z"]) <= 1.96).mean(), (np.abs(cov["exp2_z"]) <= 1.96).mean()
    headline(fig, f"Across {len(cov)} re-simulations the 95% CIs covered the truth {c1:.0%} and {c2:.0%} of the time",
             "Each run re-simulates the whole warehouse with a new seed. Curve = standard normal")
    return save(fig, "20_estimator_coverage")
