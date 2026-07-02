"""Seeded simulator for the Kinora data warehouse.

Product event logs and A/B test results are not public, so this module generates a
synthetic warehouse. It is a simple structural model:

- each user has a latent engagement score driven by acquisition channel, platform,
  device, age and signup season (New Year signups churn faster)
- paid signups respond to marketing spend with diminishing returns
- daily activity, workouts, paywall views, trials, renewals and cancellations follow
  from that score and from observed behaviour
- two experiments are planted with known effects, written to data/ground_truth.json,
  including an exposure-logging bug on web that causes a sample ratio mismatch

Random draws that both experiment arms must share (activity, workout counts,
onboarding, lifetime) come from a hash keyed on (user_id, day). Every user therefore
has both potential outcomes, and the true treatment effect can be computed exactly.

Run:  ``python -m growth_analytics.simulate [--scale 1.0] [--out data/]``
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from . import config as C

CHANNELS = ["organic", "paid_social", "search", "referral", "influencer"]
PAID_CHANNELS = ["paid_social", "search", "influencer"]
PLATFORMS = ["ios", "android", "web"]
REGIONS = ["North America", "Europe", "LATAM", "APAC"]
AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55+"]

EPOCH = np.datetime64(C.SIGNUP_START.isoformat(), "s")
N_DAYS = (C.OBS_END - C.SIGNUP_START).days + 1  # calendar days in the warehouse
DOW0 = C.SIGNUP_START.weekday()  # 2025-01-01 is a Wednesday (2)

# structural parameters (documented in docs/methodology.md)
CHANNEL_QUALITY = {"organic": 0.15, "paid_social": -0.30, "search": 0.10, "referral": 0.45, "influencer": -0.40}
PLATFORM_QUALITY = {"ios": 0.10, "android": 0.0, "web": -0.35}
DEVICE_QUALITY = {"high": 0.10, "mid": 0.0, "low": -0.20, "desktop": 0.0}
AGE_QUALITY = {"18-24": -0.10, "25-34": 0.0, "35-44": 0.10, "45-54": 0.05, "55+": 0.05}

# Experiment 1 (onboarding v2): effect on onboarding-completion log-odds by segment
EXP1_TAU_ONB_BASE = 0.45
EXP1_TAU_ONB_ANDROID = 0.30
EXP1_TAU_ONB_PAID = 0.15     # paid_social / influencer users benefit more
EXP1_TAU_ONB_WEB = 0.20      # web flow barely changed
EXP1_TAU_LIFETIME = 0.06     # small direct effect on lifetime scale (log)
EXP1_TAU_TRIAL_TO_PAID = -0.06  # tiny planted guardrail regression (log-odds)
EXP1_WEB_DROP_BOUNCER = 0.85    # P(exposure not logged | web, treatment, bounced)
EXP1_WEB_DROP_OTHER = 0.35

# Experiment 2 (smart reminders): weekly multiplicative lift, decays over time (novelty)
EXP2_TAU_ACTIVE = np.array([0.080, 0.050, 0.035, 0.030])
EXP2_TAU_WORKOUTS = np.array([0.050, 0.030, 0.020, 0.015])

WEIBULL_K = 0.65

# signups = k * spend ** elasticity (diminishing returns)
SPEND_ELASTICITY = {"paid_social": 0.80, "search": 0.70, "influencer": 0.85}


# counter-based RNG: identical draws in both potential-outcome worlds
_M1 = np.uint64(0xBF58476D1CE4E5B9)
_M2 = np.uint64(0x94D049BB133111EB)
_GOLD = np.uint64(0x9E3779B97F4A7C15)


def _mix64(z: np.ndarray) -> np.ndarray:
    z = z ^ (z >> np.uint64(30))
    z = z * _M1
    z = z ^ (z >> np.uint64(27))
    z = z * _M2
    return z ^ (z >> np.uint64(31))


def hash_uniform(seed: int, stream: int, user_id, day=0) -> np.ndarray:
    """Deterministic U(0,1) keyed on (seed, stream, user_id, day), splitmix64."""
    u = np.atleast_1d(np.asarray(user_id)).astype(np.uint64)
    d = np.atleast_1d(np.asarray(day)).astype(np.uint64)
    with np.errstate(over="ignore"):
        key = (
            (np.uint64(seed & 0xFFFF) << np.uint64(48))
            ^ (np.uint64(stream & 0xFF) << np.uint64(40))
            ^ (u << np.uint64(12))
            ^ d
        )
        z = _mix64(key + _GOLD)
        z = _mix64(z + _GOLD)
    return ((z >> np.uint64(11)).astype(np.float64) + 0.5) / 2.0**53


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


# calendar effects
def _calendar() -> pd.DataFrame:
    dates = pd.date_range(C.SIGNUP_START, C.OBS_END, freq="D")
    doy = dates.day_of_year.to_numpy()
    year = dates.year.to_numpy()
    # New-Year resolution wave (both years), summer bump, holiday dip
    ny = 1 + 0.85 * np.exp(-(doy - 1) / 26.0)
    summer = 1 + 0.12 * np.exp(-(((doy - 150) / 28.0) ** 2))
    xmas = 1 - 0.20 * np.exp(-(((doy - 358) / 9.0) ** 2))
    demand = ny * summer * xmas
    act = (1 + 0.12 * np.exp(-(doy - 1) / 30.0)) * (1 - 0.12 * np.exp(-(((doy - 359) / 7.0) ** 2)))
    act *= 1 - 0.05 * np.exp(-(((doy - 205) / 25.0) ** 2))  # mid-summer slump
    return pd.DataFrame({"date": dates, "year": year, "doy": doy, "dow": dates.day_of_week.to_numpy(),
                         "demand": demand, "activity": act})


SIGNUP_WEEKDAY = np.array([1.12, 1.05, 1.00, 0.97, 0.90, 0.88, 1.04])
ACTIVITY_WEEKDAY = np.array([1.08, 1.04, 1.02, 1.00, 0.93, 0.90, 1.00])
SPEND_MONTH = np.array([1.70, 1.20, 1.00, 1.00, 1.15, 1.10, 0.90, 0.90, 1.10, 1.00, 1.25, 0.80])


# marketing spend and signups
def simulate_marketing_and_signups(rng: np.random.Generator, scale: float):
    cal = _calendar()
    cal = cal[cal["date"] <= pd.Timestamp(C.SIGNUP_END)].reset_index(drop=True)
    n = len(cal)
    wk = SIGNUP_WEEKDAY[cal["dow"]]
    demand = cal["demand"].to_numpy()
    month = cal["date"].dt.month.to_numpy()

    counts = {
        "organic": rng.poisson(110 * scale * demand * wk * np.exp(rng.normal(0, 0.07, n))),
        "referral": rng.poisson(32 * scale * demand * wk * np.exp(rng.normal(0, 0.10, n))),
    }

    base_budget = {"paid_social": 310.0, "search": 155.0, "influencer": 235.0}
    base_signups = {"paid_social": 95.0, "search": 52.0, "influencer": 42.0}
    cpm = {"paid_social": 6.5, "search": 38.0, "influencer": 9.0}
    ctr = {"paid_social": 0.009, "search": 0.045, "influencer": 0.013}

    # influencer spend comes in campaign bursts
    burst = np.full(n, 0.45)
    for start in range(4, n, 21):
        burst[start:start + 8] = 2.3
    burst /= burst.mean()

    spend_rows = []
    for ch in PAID_CHANNELS:
        spend = base_budget[ch] * scale * SPEND_MONTH[month - 1] * np.exp(rng.normal(0, 0.12, n))
        if ch == "influencer":
            spend *= burst
        k = base_signups[ch] / base_budget[ch] ** SPEND_ELASTICITY[ch]
        expected = scale * k * (spend / scale) ** SPEND_ELASTICITY[ch] * wk * np.sqrt(demand)
        counts[ch] = rng.poisson(expected)
        impressions = rng.poisson(spend / cpm[ch] * 1000)
        clicks = rng.binomial(impressions, ctr[ch])
        spend_rows.append(pd.DataFrame({
            "date": cal["date"].dt.date, "channel": ch, "spend_usd": spend.round(2),
            "impressions": impressions, "clicks": clicks,
        }))
    spend_df = pd.concat(spend_rows, ignore_index=True)

    day_idx, chan = [], []
    for ch in CHANNELS:
        day_idx.append(np.repeat(np.arange(n), counts[ch]))
        chan.append(np.full(counts[ch].sum(), ch, dtype=object))
    day_idx = np.concatenate(day_idx)
    chan = np.concatenate(chan)
    return spend_df, day_idx, chan


def _time_of_day(rng: np.random.Generator, size: int) -> np.ndarray:
    """Seconds after midnight: morning, lunch and evening workout peaks."""
    comp = rng.choice(3, size=size, p=[0.35, 0.20, 0.45])
    mu = np.array([7.0, 12.5, 19.0])[comp]
    sd = np.array([1.2, 1.0, 1.6])[comp]
    hours = np.clip(rng.normal(mu, sd), 0.0, 23.99)
    return (hours * 3600).astype(np.int64)


def build_users(rng, day_idx, chan) -> pd.DataFrame:
    n = len(day_idx)
    order = np.lexsort((rng.random(n), day_idx))
    day_idx, chan = day_idx[order], chan[order]
    secs = _time_of_day(rng, n)
    o2 = np.lexsort((secs, day_idx))
    day_idx, chan, secs = day_idx[o2], chan[o2], secs[o2]

    # platform depends on channel (search skews web, paid social skews Android)
    plat_p = {
        "organic": [0.44, 0.45, 0.11], "paid_social": [0.36, 0.57, 0.07], "search": [0.36, 0.42, 0.22],
        "referral": [0.47, 0.44, 0.09], "influencer": [0.42, 0.52, 0.06],
    }
    platform = np.empty(n, dtype=object)
    for ch, p in plat_p.items():
        m = chan == ch
        platform[m] = rng.choice(PLATFORMS, size=m.sum(), p=p)

    region = rng.choice(REGIONS, size=n, p=[0.38, 0.30, 0.14, 0.18])
    device = np.empty(n, dtype=object)
    m = platform == "ios"
    device[m] = rng.choice(["high", "mid"], size=m.sum(), p=[0.7, 0.3])
    m = platform == "android"
    device[m] = rng.choice(["high", "mid", "low"], size=m.sum(), p=[0.25, 0.45, 0.30])
    device[platform == "web"] = "desktop"

    age = np.empty(n, dtype=object)
    young = np.isin(chan, ["influencer", "paid_social"])
    age[young] = rng.choice(AGE_BANDS, size=young.sum(), p=[0.34, 0.36, 0.18, 0.08, 0.04])
    age[~young] = rng.choice(AGE_BANDS, size=(~young).sum(), p=[0.18, 0.33, 0.26, 0.15, 0.08])

    signup_date = (EPOCH.astype("datetime64[D]") + day_idx.astype("timedelta64[D]"))
    signup_ts = EPOCH + (day_idx.astype(np.int64) * 86400 + secs).astype("timedelta64[s]")

    users = pd.DataFrame({
        "user_id": np.arange(1, n + 1, dtype=np.int64),
        "signup_ts": signup_ts,
        "signup_date": signup_date,
        "acquisition_channel": chan,
        "platform": platform,
        "region": region,
        "device_tier": device,
        "age_band": age,
    })
    users["_day"] = day_idx
    users["_secs"] = secs
    return users


# behavioural model
def latent_quality(rng, users: pd.DataFrame) -> np.ndarray:
    doy = users["signup_date"].dt.day_of_year.to_numpy()
    z = rng.normal(0, 0.9, len(users))
    z += users["acquisition_channel"].map(CHANNEL_QUALITY).to_numpy()
    z += users["platform"].map(PLATFORM_QUALITY).to_numpy()
    z += users["device_tier"].map(DEVICE_QUALITY).to_numpy()
    z += users["age_band"].map(AGE_QUALITY).to_numpy()
    z += -0.25 * np.exp(-(doy - 1) / 30.0)  # New-Year resolution users are less sticky
    return z


def onboarding_prob(z, platform, channel, treat) -> np.ndarray:
    base = 0.35 + 0.8 * z + np.select([platform == "ios", platform == "web"], [0.10, -0.20], 0.0)
    tau = np.where(platform == "web", EXP1_TAU_ONB_WEB,
                   EXP1_TAU_ONB_BASE + np.where(platform == "android", EXP1_TAU_ONB_ANDROID, 0.0))
    tau = tau + np.where(np.isin(channel, ["paid_social", "influencer"]), EXP1_TAU_ONB_PAID, 0.0)
    return sigmoid(base + treat * tau)


def lifetime_days(z, onboarded, treat, u) -> np.ndarray:
    """Weibull(k<1) lifetime: many users leave in days, a long tail stays for months."""
    lam = np.exp(1.70 + 0.80 * z + 0.90 * onboarded + EXP1_TAU_LIFETIME * treat)
    return lam * (-np.log1p(-u)) ** (1.0 / WEIBULL_K)


def base_activity(z, onboarded) -> np.ndarray:
    return sigmoid(-0.90 + 0.80 * z + 0.40 * onboarded)


def active_prob(a_base, d, cal_activity, dow) -> np.ndarray:
    honeymoon = 0.72 + 0.28 * np.exp(-d / 8.0)
    return np.clip(a_base * honeymoon * cal_activity * ACTIVITY_WEEKDAY[dow], 0.0, 0.97)


# main simulation
def simulate(scale: float = 1.0, seed: int = C.SEED) -> dict[str, pd.DataFrame | dict]:
    t0 = time.time()
    rng = np.random.default_rng(seed)
    cal = _calendar()
    cal_act = cal["activity"].to_numpy()

    spend_df, day_idx, chan = simulate_marketing_and_signups(rng, scale)
    users = build_users(rng, day_idx, chan)
    n = len(users)
    uid = users["user_id"].to_numpy()
    sday = users["_day"].to_numpy()
    plat = users["platform"].to_numpy().astype(str)
    chan = users["acquisition_channel"].to_numpy().astype(str)
    horizon = N_DAYS - sday  # days observable incl. signup day

    z = latent_quality(rng, users)
    lam_user = 0.80 * np.exp(0.30 * z + 0.45 * rng.normal(0, 1, n))  # workouts per active day

    # experiment 1 assignment (server-side hash, 50/50)
    e1_start = (C.EXP1["start"] - C.SIGNUP_START).days
    e1_end = (C.EXP1["end"] - C.SIGNUP_START).days
    in_e1 = (sday >= e1_start) & (sday <= e1_end)
    e1_treat = in_e1 & (hash_uniform(seed, 20, uid) < 0.5)
    treat = e1_treat.astype(float)

    u_onb = hash_uniform(seed, 10, uid)
    u_life = hash_uniform(seed, 11, uid)
    onboarded = u_onb < onboarding_prob(z, plat, chan, treat)
    L = lifetime_days(z, onboarded, treat, u_life)
    a_base = base_activity(z, onboarded)

    # candidate user-days (ragged expansion)
    n_days = np.clip(np.ceil(L).astype(np.int64), 1, horizon)
    starts = np.concatenate([[0], np.cumsum(n_days)[:-1]])
    ui = np.repeat(np.arange(n), n_days)
    d = np.arange(n_days.sum()) - np.repeat(starts, n_days)
    date_idx = sday[ui] + d
    dow = cal["dow"].to_numpy()[date_idx]
    p_act = active_prob(a_base[ui], d, cal_act[date_idx], dow)
    u_act = hash_uniform(seed, 1, uid[ui], d)
    u_wk = hash_uniform(seed, 2, uid[ui], d)

    # experiment 2: smart reminders for existing active users
    e2_pre0 = (C.EXP2["pre_start"] - C.SIGNUP_START).days
    e2_pre1 = (C.EXP2["pre_end"] - C.SIGNUP_START).days
    e2_s = (C.EXP2["start"] - C.SIGNUP_START).days
    e2_e = (C.EXP2["end"] - C.SIGNUP_START).days

    active0 = (d == 0) | (u_act < p_act)
    workouts0 = np.zeros(len(ui), dtype=np.int64)
    workouts0[active0] = stats.poisson.ppf(u_wk[active0], lam_user[ui][active0]).astype(np.int64)
    # eligible = existing users (signed up before the pre-period) with >= 1 session in it
    pre_mask = (date_idx >= e2_pre0) & (date_idx <= e2_pre1) & active0
    pre_active_days = np.bincount(ui[pre_mask], minlength=n)
    e2_eligible = (pre_active_days >= 1) & (sday < e2_pre0)
    e2_treat = e2_eligible & (hash_uniform(seed, 21, uid) < 0.5)

    win = (date_idx >= e2_s) & (date_idx <= e2_e) & e2_eligible[ui]
    week = np.clip((date_idx - e2_s) // 7, 0, 3)
    p_act1 = np.where(win, np.clip(p_act * (1 + EXP2_TAU_ACTIVE[week]), 0, 0.97), p_act)
    active1 = (d == 0) | (u_act < p_act1)
    workouts1 = workouts0.copy()
    m1 = active1 & win
    lam1 = lam_user[ui][m1] * (1 + EXP2_TAU_WORKOUTS[week[m1]])
    workouts1[m1] = stats.poisson.ppf(u_wk[m1], lam1).astype(np.int64)
    workouts1[~active1] = 0

    t2 = e2_treat[ui]
    active = np.where(t2, active1, active0)
    completed = np.where(t2, workouts1, workouts0)

    # ground truth for experiment 2 (exact, common random numbers)
    elig_idx = np.flatnonzero(e2_eligible)
    wsum0 = np.bincount(ui[win], weights=workouts0[win], minlength=n)[elig_idx]
    wsum1 = np.bincount(ui[win], weights=workouts1[win], minlength=n)[elig_idx]
    week_truth = []
    for w in range(4):
        m = win & (week == w)
        w0 = np.bincount(ui[m], weights=workouts0[m], minlength=n)[elig_idx]
        w1 = np.bincount(ui[m], weights=workouts1[m], minlength=n)[elig_idx]
        week_truth.append(float((w1 - w0).mean()))

    # keep only active days
    keep = active
    ui, d, date_idx, completed = ui[keep], d[keep], date_idx[keep], completed[keep]
    m_rows = len(ui)
    started = completed + rng.poisson(0.30, m_rows)
    sessions = np.maximum(1, completed + rng.poisson(0.60, m_rows))

    # paywall, trial, subscription
    first_active_1_6 = np.full(n, 999)
    mk = (d >= 1) & (d <= 6)
    np.minimum.at(first_active_1_6, ui[mk], d[mk])
    u_pw = rng.random(n)
    paywall_day = np.where(onboarded & (u_pw < 0.90), 0,
                           np.where(~onboarded & (first_active_1_6 < 999) & (u_pw < 0.35), first_active_1_6, -1))
    region = users["region"].to_numpy().astype(str)
    region_eff = pd.Series(region).map({"North America": 0.15, "Europe": 0.05, "LATAM": -0.30, "APAC": -0.10}).to_numpy()
    p_trial = sigmoid(-1.75 + 0.55 * z + np.select([plat == "ios", plat == "web"], [0.25, -0.20], 0.0) + region_eff)
    trial = (paywall_day >= 0) & (rng.random(n) < p_trial) & (paywall_day < horizon)
    trial_day = np.where(trial, paywall_day, -1)

    def window_sum(values, lo, hi, cond=None):
        """Per-user sum of `values` over user-day offsets lo <= d < hi."""
        mm = (d >= lo[ui]) & (d < hi[ui])
        if cond is not None:
            mm &= cond[ui]
        return np.bincount(ui[mm], weights=values[mm], minlength=n)

    trial_workouts = window_sum(completed, trial_day, trial_day + C.TRIAL_DAYS, trial)
    p_conv = sigmoid(-0.35 + 0.45 * z + 0.35 * np.log1p(trial_workouts)
                     + np.where(plat == "ios", 0.20, 0.0) + EXP1_TAU_TRIAL_TO_PAID * treat)
    sub_day = trial_day + C.TRIAL_DAYS
    paid = trial & (rng.random(n) < p_conv) & (sub_day < horizon)

    age = users["age_band"].to_numpy().astype(str)
    p_annual = sigmoid(-0.75 + 0.30 * z + np.where(plat == "ios", 0.10, 0.0) + np.isin(age, ["35-44", "45-54", "55+"]) * 0.20)
    plan = np.where(rng.random(n) < p_annual, "annual", "monthly")

    ones = np.ones(m_rows)
    w14 = window_sum(completed, sub_day, sub_day + 14, paid)
    a14 = window_sum(ones, sub_day, sub_day + 14, paid)
    wk1 = window_sum(completed, sub_day, sub_day + 7, paid)
    wk2 = window_sum(completed, sub_day + 7, sub_day + 14, paid)
    declining = (wk2 < wk1).astype(float)
    chan_churn = pd.Series(chan).map({"influencer": 0.20, "paid_social": 0.15, "search": -0.05,
                                      "referral": -0.15, "organic": 0.0}).to_numpy()
    p_cancel1 = sigmoid(0.25 - 0.45 * np.log1p(w14) - 0.10 * a14 - 0.30 * z + 0.35 * declining + chan_churn
                        + np.where(region == "LATAM", 0.20, 0.0) + np.where(age == "18-24", 0.15, 0.0))
    cancel1 = rng.random(n) < p_cancel1
    cancel1_day = 29 - np.floor(rng.beta(1.0, 2.5, n) * 27).astype(int)  # most cancel close to renewal

    h_month = sigmoid(-2.40 - 0.45 * z + np.where(a14 < 3, 0.40, 0.0))
    extra_months = rng.geometric(h_month) - 1  # full months survived after the first renewal
    cancel_later_day = 30 * (1 + extra_months) + rng.integers(1, 29, n)
    p_cancel_annual = sigmoid(-0.40 - 0.45 * z)
    cancel_annual = rng.random(n) < p_cancel_annual
    cancel_annual_day = rng.integers(10, 360, n)

    monthly = plan == "monthly"
    cancel_day = np.where(monthly, np.where(cancel1, cancel1_day, cancel_later_day),
                          np.where(cancel_annual, cancel_annual_day, 10_000))
    # tables
    tables = _assemble_tables(
        rng, users, uid, sday, horizon, onboarded, e1_treat, in_e1, ui, d, date_idx,
        sessions, started, completed, paywall_day, trial_day, paid, sub_day, plan, cancel_day,
    )
    tables["marketing_spend"] = spend_df

    # experiments
    tables["experiment_exposures"] = _exposures(rng, users, uid, in_e1, e1_treat, onboarded, L,
                                                e2_eligible, e2_treat)

    truth = _ground_truth_exp1(seed, users, uid, sday, horizon, z, plat, chan, in_e1, e1_treat, u_onb, u_life,
                               cal_act, cal["dow"].to_numpy())
    truth["exp2"] = {
        "n_eligible": int(e2_eligible.sum()),
        "ate_workouts_28d": float((wsum1 - wsum0).mean()),
        "control_mean_workouts_28d": float(wsum0.mean()),
        "relative_lift": float((wsum1 - wsum0).mean() / wsum0.mean()),
        "ate_by_week": week_truth,
        "planted_active_lift_by_week": EXP2_TAU_ACTIVE.tolist(),
        "planted_workout_lift_by_week": EXP2_TAU_WORKOUTS.tolist(),
    }
    truth["exp1"]["planted_trial_to_paid_logodds"] = EXP1_TAU_TRIAL_TO_PAID
    truth["meta"] = {"seed": seed, "scale": scale, "n_users": int(n), "n_events": int(len(tables["events"])),
                     "runtime_s": round(time.time() - t0, 1)}
    tables["ground_truth"] = truth
    return tables


# table assembly
def _to_date(days) -> np.ndarray:
    """Day offsets since SIGNUP_START (NaN allowed) -> datetime64 dates."""
    arr = np.asarray(days, dtype=float)
    out = np.full(len(arr), np.datetime64("NaT", "s"), dtype="datetime64[s]")
    ok = ~np.isnan(arr)
    out[ok] = EPOCH + (arr[ok].astype(np.int64) * 86400).astype("timedelta64[s]")
    return out

EVENT_NAMES = ["signup", "onboarding_step", "onboarding_complete", "app_open", "workout_started",
               "workout_completed", "app_crash", "paywall_view", "trial_start", "subscription_start",
               "subscription_renewal", "subscription_cancel"]


def _assemble_tables(rng, users, uid, sday, horizon, onboarded, e1_treat, in_e1, ui, d, date_idx,
                     sessions, started, completed, paywall_day, trial_day, paid, sub_day, plan, cancel_day):
    n = len(users)
    secs0 = users["_secs"].to_numpy()
    ev_user, ev_t, ev_name, ev_prop = [], [], [], []

    def add(u_idx, tsec, name, prop=None):
        ev_user.append(uid[u_idx])
        ev_t.append(tsec)
        ev_name.append(np.full(len(u_idx), EVENT_NAMES.index(name), dtype=np.int8))
        ev_prop.append(prop if isinstance(prop, np.ndarray) else np.full(len(u_idx), prop, dtype=object))

    day_secs = lambda idx, off: (sday[idx] + off).astype(np.int64) * 86400  # noqa: E731

    # signup and onboarding (control flow has 5 steps, onboarding_v2 has 3)
    allu = np.arange(n)
    add(allu, day_secs(allu, 0) + secs0, "signup")
    n_steps = np.where(e1_treat, 3, 5)
    reached = np.where(onboarded, n_steps, 1 + np.floor(rng.random(n) * (n_steps - 1)).astype(int))
    for s in range(1, 6):
        idx = np.flatnonzero(reached >= s)
        add(idx, day_secs(idx, 0) + secs0[idx] + 25 * s, "onboarding_step", np.full(len(idx), f'{{"step":{s}}}', dtype=object))
    idx = np.flatnonzero(onboarded)
    add(idx, day_secs(idx, 0) + secs0[idx] + 25 * n_steps[idx] + 10, "onboarding_complete")

    # sessions, workouts and crashes on active days
    first_secs = np.where(d == 0, secs0[ui], -1)
    s_rep = np.repeat(np.arange(len(ui)), sessions)
    tod = _time_of_day(rng, len(s_rep))
    k_in_day = np.arange(len(s_rep)) - np.repeat(np.concatenate([[0], np.cumsum(sessions)[:-1]]), sessions)
    is_day0 = d[s_rep] == 0
    day0_t = first_secs[s_rep] + k_in_day * rng.integers(1800, 4 * 3600, len(s_rep))
    tod = np.where(is_day0, np.minimum(day0_t, 86399), tod)
    base = date_idx[s_rep].astype(np.int64) * 86400
    sess_t = base + tod
    add(ui[s_rep], sess_t, "app_open")
    crash = rng.random(len(s_rep)) < 0.004
    add(ui[s_rep][crash], sess_t[crash] + rng.integers(30, 900, crash.sum()), "app_crash")

    w_rep = np.repeat(np.arange(len(ui)), started)
    k_w = np.arange(len(w_rep)) - np.repeat(np.concatenate([[0], np.cumsum(started)[:-1]]), started)
    # attach the k-th workout to the k-th session of that day (wrapping), a few minutes in
    sess_offset = np.concatenate([[0], np.cumsum(sessions)[:-1]])
    sess_pick = sess_offset[w_rep] + (k_w % sessions[w_rep])
    w_start = np.minimum(sess_t[sess_pick] + 120 + (k_w // sessions[w_rep]) * 2700, base[sess_pick] + 86399)
    add(ui[w_rep], w_start, "workout_started")
    done = k_w < completed[w_rep]
    add(ui[w_rep][done], np.minimum(w_start[done] + rng.integers(15 * 60, 50 * 60, done.sum()),
                                     base[sess_pick][done] + 86399), "workout_completed")

    # paywall and trial
    idx = np.flatnonzero(paywall_day >= 0)
    add(idx, day_secs(idx, paywall_day[idx]) + np.where(paywall_day[idx] == 0, secs0[idx] + 400, 20 * 3600), "paywall_view")
    idx = np.flatnonzero(trial_day >= 0)
    add(idx, day_secs(idx, trial_day[idx]) + np.where(trial_day[idx] == 0, secs0[idx] + 460, 20 * 3600 + 60), "trial_start")

    # subscriptions and charges
    sub_rows, charge_rows = [], []
    obs_end_day = N_DAYS - 1
    pidx = np.flatnonzero(paid)
    plat = users["platform"].to_numpy().astype(str)
    for j, i in enumerate(pidx):
        start = sday[i] + sub_day[i]
        cday = cancel_day[i]
        if plan[i] == "monthly":
            period = 30
        else:
            period = 365
        cancel_abs = start + cday if cday < 10_000 else None
        # charges every period while not cancelled before the renewal date and inside observation window
        k = 0
        while True:
            charge_day = start + k * period
            if charge_day > obs_end_day:
                break
            if cancel_abs is not None and charge_day > cancel_abs:
                break
            charge_rows.append((i, charge_day, k))
            k += 1
        n_charges = k
        end_abs = start + n_charges * period if cancel_abs is not None else None
        observed_cancel = cancel_abs is not None and cancel_abs <= obs_end_day
        sub_rows.append((i, start, cancel_abs if observed_cancel else np.nan,
                         end_abs if observed_cancel else np.nan, n_charges))

    sub = pd.DataFrame(sub_rows, columns=["i", "start_day", "cancel_day", "end_day", "n_charges"])
    sub["subscription_id"] = np.arange(1, len(sub) + 1)
    sub["user_id"] = uid[sub["i"]]
    sub["plan"] = plan[sub["i"]]
    sub["list_price_usd"] = sub["plan"].map(C.PRICES)
    sub["store"] = pd.Series(plat[sub["i"]]).map({"ios": "app_store", "android": "play_store", "web": "web_stripe"}).to_numpy()
    sub["trial_start_date"] = _to_date(sday[sub["i"]] + trial_day[sub["i"]])
    sub["start_date"] = _to_date(sub["start_day"])
    sub["cancel_date"] = _to_date(sub["cancel_day"])
    sub["end_date"] = _to_date(sub["end_day"])
    sub["status"] = np.where(sub["cancel_date"].isna(), "active",
                             np.where(sub["end_date"] <= pd.Timestamp(C.OBS_END), "expired", "cancelled"))

    ch = pd.DataFrame(charge_rows, columns=["i", "charge_day", "seq"])
    sub_id_of_user = dict(zip(sub["i"], sub["subscription_id"]))
    ch["subscription_id"] = ch["i"].map(sub_id_of_user)
    ch["user_id"] = uid[ch["i"]]
    ch["charge_date"] = _to_date(ch["charge_day"])
    ch["charge_type"] = np.where(ch["seq"] == 0, "new", "renewal")
    ch["gross_usd"] = pd.Series(plan[ch["i"]]).map(C.PRICES).to_numpy()
    fee = pd.Series(plat[ch["i"]]).map(C.STORE_FEE).to_numpy()
    ch["net_usd"] = (ch["gross_usd"] * (1 - fee)).round(2)
    ch = ch.sort_values(["charge_date", "subscription_id"]).reset_index(drop=True)
    ch.insert(0, "charge_id", np.arange(1, len(ch) + 1))

    # subscription events
    si = sub["i"].to_numpy()
    plan_prop = np.array([f'{{"plan":"{p}"}}' for p in sub["plan"]], dtype=object)
    add(si, sub["start_day"].to_numpy().astype(np.int64) * 86400 + 6 * 3600, "subscription_start", plan_prop)
    ren = ch[ch["seq"] > 0]
    add(ren["i"].to_numpy(), ren["charge_day"].to_numpy().astype(np.int64) * 86400 + 6 * 3600 + 60, "subscription_renewal")
    canc = sub[sub["cancel_day"].notna()]
    add(canc["i"].to_numpy(), canc["cancel_day"].to_numpy().astype(np.int64) * 86400 + 21 * 3600, "subscription_cancel")

    events = pd.DataFrame({
        "user_id": np.concatenate(ev_user),
        "event_ts": EPOCH + np.concatenate(ev_t).astype("timedelta64[s]"),
        "event_name": pd.Categorical.from_codes(np.concatenate(ev_name), EVENT_NAMES),
        "event_props": np.concatenate(ev_prop),
    })
    events = events.sort_values(["user_id", "event_ts"], kind="stable").reset_index(drop=True)

    subscriptions = sub[["subscription_id", "user_id", "plan", "list_price_usd", "store", "trial_start_date",
                         "start_date", "cancel_date", "end_date", "status"]]
    charges = ch[["charge_id", "subscription_id", "user_id", "charge_date", "charge_type", "gross_usd", "net_usd"]]
    users_out = users.drop(columns=["_day", "_secs"])
    return {"users": users_out, "events": events, "subscriptions": subscriptions, "charges": charges}


def _exposures(rng, users, uid, in_e1, e1_treat, onboarded, L, e2_eligible, e2_treat) -> pd.DataFrame:
    plat = users["platform"].to_numpy().astype(str)
    # Exposure is logged client side when the first onboarding screen renders. The new
    # web flow fired the event after a large asset bundle loaded, so users who bounced
    # quickly were often never logged. This causes an SRM on web only.
    bounced = (~onboarded) & (L < 2.0)
    p_drop = np.where(bounced, EXP1_WEB_DROP_BOUNCER, EXP1_WEB_DROP_OTHER)
    dropped = in_e1 & e1_treat & (plat == "web") & (rng.random(len(uid)) < p_drop)
    logged = in_e1 & ~dropped
    i1 = np.flatnonzero(logged)
    ts1 = users["signup_ts"].to_numpy()[i1] + rng.integers(2, 20, len(i1)).astype("timedelta64[s]")
    e1 = pd.DataFrame({"user_id": uid[i1], "experiment": C.EXP1["name"],
                       "variant": np.where(e1_treat[i1], "treatment", "control"), "exposed_at": ts1})

    i2 = np.flatnonzero(e2_eligible)
    t0 = np.datetime64(C.EXP2["start"].isoformat(), "s")
    ts2 = t0 + rng.integers(6 * 3600, 30 * 3600, len(i2)).astype("timedelta64[s]")
    e2 = pd.DataFrame({"user_id": uid[i2], "experiment": C.EXP2["name"],
                       "variant": np.where(e2_treat[i2], "treatment", "control"), "exposed_at": ts2})
    out = pd.concat([e1, e2], ignore_index=True)
    out.attrs["web_drop_rate"] = float(dropped.sum() / max(1, (in_e1 & e1_treat & (plat == "web")).sum()))
    return out


def _ground_truth_exp1(seed, users, uid, sday, horizon, z, plat, chan, in_e1, e1_treat, u_onb, u_life,
                       cal_act, dow_arr) -> dict:
    """Exact potential outcomes for every user assigned to experiment 1."""
    idx = np.flatnonzero(in_e1)
    zi, pi, ci = z[idx], plat[idx], chan[idx]

    def outcomes(arm: float):
        onb = u_onb[idx] < onboarding_prob(zi, pi, ci, arm)
        L = lifetime_days(zi, onb, arm, u_life[idx])
        a = base_activity(zi, onb)

        def retained(lo, hi):
            dd = np.arange(lo, hi + 1)
            date = sday[idx][:, None] + dd[None, :]
            ok = (dd[None, :] < L[:, None]) & (dd[None, :] < horizon[idx][:, None])
            p = active_prob(a[:, None], dd[None, :], cal_act[np.minimum(date, len(cal_act) - 1)],
                            dow_arr[np.minimum(date, len(dow_arr) - 1)])
            u = hash_uniform(seed, 1, np.repeat(uid[idx], len(dd)), np.tile(dd, len(idx))).reshape(len(idx), len(dd))
            return ((u < p) & ok).any(axis=1)

        return onb, retained(7, 13), retained(30, 36)

    onb0, d7_0, d30_0 = outcomes(0.0)
    onb1, d7_1, d30_1 = outcomes(1.0)
    eff_d7 = d7_1.astype(float) - d7_0
    mob = pi != "web"

    def by(mask_fn_values, values):
        return {str(k): float(values[mask_fn_values == k].mean()) for k in np.unique(mask_fn_values)}

    return {"exp1": {
        "n_assigned": int(len(idx)),
        "control_d7_ios_android": float(d7_0[mob].mean()),
        "ate_d7_all_assigned": float(eff_d7.mean()),
        "ate_d7_ios_android": float(eff_d7[mob].mean()),
        "ate_d7_by_platform": by(pi, eff_d7),
        "ate_d7_by_channel_ios_android": by(ci[mob], eff_d7[mob]),
        "ate_onboarding_ios_android": float((onb1.astype(float) - onb0)[mob].mean()),
        "ate_d30_ios_android": float((d30_1.astype(float) - d30_0)[mob].mean()),
        "web_exposure_drop_rate": None,  # filled by caller
    }}


# write to disk
def write(tables: dict, out_dir: Path) -> None:
    raw = out_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    truth = tables.pop("ground_truth")
    truth["exp1"]["web_exposure_drop_rate"] = tables["experiment_exposures"].attrs.get("web_drop_rate")
    for name, df in tables.items():
        df.attrs = {}
        df.to_parquet(raw / f"{name}.parquet", index=False)
    (out_dir / "ground_truth.json").write_text(json.dumps(truth, indent=2))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scale", type=float, default=1.0, help="population multiplier (1.0 = ~120k signups)")
    ap.add_argument("--seed", type=int, default=C.SEED)
    ap.add_argument("--out", type=Path, default=C.DATA_DIR)
    args = ap.parse_args(argv)
    tables = simulate(scale=args.scale, seed=args.seed)
    meta = tables["ground_truth"]["meta"]
    write(tables, args.out)
    print(f"simulated {meta['n_users']:,} users and {meta['n_events']:,} events "
          f"in {meta['runtime_s']}s -> {args.out}")


if __name__ == "__main__":
    main()
