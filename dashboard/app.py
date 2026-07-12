"""Kinora growth dashboard.

    streamlit run dashboard/app.py        (after `make data warehouse analysis`)

Filters sit in one row above the charts and apply to every live (warehouse) chart.
Experiment and model read-outs come from reports/metrics.json, so the dashboard and
the written report always show the same numbers.
"""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from growth_analytics import config as C
from growth_analytics.plotting import BASELINE, CHANNEL_COLOR, GRID, INK, INK_2, LABEL, MUTED, NEG, POS, SERIES, SURFACE
from growth_analytics.warehouse import connect

st.set_page_config(page_title="Kinora growth analytics", layout="wide")

CHANNELS = ["organic", "paid_social", "search", "referral", "influencer"]
PLATFORMS = ["ios", "android", "web"]
CH_MAP = {LABEL[c]: CHANNEL_COLOR[c] for c in CHANNELS}


# data
@st.cache_data(show_spinner=False)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    with connect() as con:
        return con.execute(sql, list(params)).df()


@st.cache_data(show_spinner=False)
def metrics() -> dict:
    return json.loads(C.METRICS_PATH.read_text()) if C.METRICS_PATH.exists() else {}


def style(fig: go.Figure, height: int = 360, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=36, b=8), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK_2, size=12),
        title_font=dict(color=INK, size=14), colorway=SERIES, hovermode="x unified",
        legend=dict(orientation="h", y=1.12, x=0, title_text="") if legend else dict(visible=False),
        showlegend=legend,
    )
    fig.update_xaxes(showgrid=False, linecolor=BASELINE, tickfont_color=INK_2)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, tickfont_color=INK_2)
    return fig


try:
    connect().close()
except FileNotFoundError:
    st.error("Warehouse not found. Run `make data warehouse analysis` first.")
    st.stop()

M = metrics()

# header
st.title("Kinora product growth analytics")
st.caption("Fictional freemium fitness app. Simulated data, Jan 2025 to Jan 2026.")

# filters (one row)
f1, f2, f3 = st.columns([1.2, 1.4, 1])
with f1:
    dr = st.date_input("Signup date", value=(C.SIGNUP_START, C.OBS_END), min_value=C.SIGNUP_START,
                       max_value=C.OBS_END)
with f2:
    chans = st.multiselect("Acquisition channel", CHANNELS, default=CHANNELS, format_func=LABEL.get)
with f3:
    plats = st.multiselect("Platform", PLATFORMS, default=PLATFORMS, format_func=LABEL.get)
d0, d1 = (dr if isinstance(dr, tuple) and len(dr) == 2 else (C.SIGNUP_START, C.OBS_END))
chans, plats = chans or CHANNELS, plats or PLATFORMS
FILTER = "u.signup_date BETWEEN ? AND ? AND list_contains(?, u.acquisition_channel) AND list_contains(?, u.platform)"
P = (d0, d1, chans, plats)

tabs = st.tabs(["Overview", "Acquisition & funnel", "Retention", "Experiments", "Revenue & churn", "Marketing"])

# overview
with tabs[0]:
    k = q(f"""SELECT count(*) AS users,
                     avg(d7_retained::INT) FILTER (WHERE d7_mature) AS d7,
                     avg(d30_retained::INT) FILTER (WHERE d30_mature) AS d30,
                     count(subscription_id) AS paid
              FROM dim_users u WHERE {FILTER}""", P).iloc[0]
    c = st.columns(5)
    c[0].metric("Signups", f"{k['users']:,.0f}")
    c[1].metric("D7 retention", f"{(k['d7'] or 0):.1%}")
    c[2].metric("D30 retention", f"{(k['d30'] or 0):.1%}")
    c[3].metric("Paying subscribers", f"{k['paid']:,.0f}", f"{k['paid'] / max(k['users'], 1):.1%} of signups",
                delta_color="off")
    if M:
        c[4].metric("MRR (Jan 2026)", f"${M['revenue']['mrr_end_usd']:,.0f}")
    act = q(f"""SELECT f.activity_date AS day, count(*) AS dau
                FROM fct_user_daily f JOIN stg_users u USING (user_id)
                WHERE f.is_active AND {FILTER} GROUP BY 1 ORDER BY 1""", P)
    act["DAU (7-day avg)"] = act["dau"].rolling(7, min_periods=1).mean()
    st.plotly_chart(style(px.line(act, x="day", y="DAU (7-day avg)", title="Daily active users"), legend=False),
                    width="stretch")

# acquisition/funnel
with tabs[1]:
    w = q(f"""SELECT date_trunc('week', signup_date)::DATE AS week, acquisition_channel AS channel, count(*) AS signups
              FROM dim_users u WHERE {FILTER} GROUP BY ALL ORDER BY ALL""", P)
    w["channel"] = w["channel"].map(LABEL)
    st.plotly_chart(style(px.line(w, x="week", y="signups", color="channel", color_discrete_map=CH_MAP,
                                  title="Weekly signups by channel")), width="stretch")
    fdf = q(f"""SELECT count(*) AS "Signed up", count(*) FILTER (WHERE onboarded) AS "Completed onboarding",
                       count(*) FILTER (WHERE first_paywall_at IS NOT NULL) AS "Saw paywall",
                       count(*) FILTER (WHERE trial_started_at IS NOT NULL) AS "Started trial",
                       count(*) FILTER (WHERE subscribed_at IS NOT NULL) AS "Paying subscriber"
                FROM dim_users u WHERE d30_mature AND {FILTER}""", P).T.reset_index()
    fdf.columns = ["stage", "users"]
    fig = go.Figure(go.Funnel(y=fdf["stage"], x=fdf["users"], marker_color=SERIES[0],
                              textinfo="value+percent initial+percent previous"))
    st.plotly_chart(style(fig, legend=False).update_layout(title="Funnel (cohorts with a full 30-day window)",
                                                           hovermode="closest"), width="stretch")

# retention
with tabs[2]:
    cr = q(f"""WITH wa AS (SELECT DISTINCT user_id, days_since_signup // 7 AS wk FROM fct_user_daily
                           WHERE is_active AND days_since_signup BETWEEN 7 AND 90)
               SELECT strftime(date_trunc('month', u.signup_date), '%Y-%m') AS cohort, g.wk AS week,
                      count(wa.user_id) / count(*) AS retention
               FROM stg_users u CROSS JOIN range(1, 13) g(wk)
               LEFT JOIN wa ON wa.user_id = u.user_id AND wa.wk = g.wk
               WHERE {FILTER} AND u.signup_date + CAST(g.wk * 7 + 6 AS INTEGER) <= DATE '{C.OBS_END}'
               GROUP BY ALL ORDER BY ALL""", P)
    piv = cr.pivot(index="cohort", columns="week", values="retention")
    fig = px.imshow(piv, color_continuous_scale=["#cde2fb", "#6da7ec", "#256abf", "#0d366b"], aspect="auto",
                    labels=dict(x="weeks since signup", y="signup cohort", color="retained"), text_auto=".0%")
    st.plotly_chart(style(fig, 460, legend=False).update_layout(title="Cohort retention", hovermode="closest"),
                    width="stretch")
    rc = q(f"""SELECT u.acquisition_channel AS channel, h.n AS day_n,
                      avg(CASE WHEN EXISTS (SELECT 1 FROM fct_user_daily f WHERE f.user_id = u.user_id AND f.is_active
                                 AND f.days_since_signup BETWEEN h.n AND h.n + 6) THEN 1 ELSE 0 END) AS retention
               FROM stg_users u CROSS JOIN (SELECT unnest([1, 7, 14, 30, 60, 90]) AS n) h
               WHERE {FILTER} AND u.signup_date + h.n + 6 <= DATE '{C.OBS_END}'
               GROUP BY ALL ORDER BY ALL""", P)
    rc["channel"] = rc["channel"].map(LABEL)
    st.plotly_chart(style(px.line(rc, x="day_n", y="retention", color="channel", markers=True,
                                  color_discrete_map=CH_MAP, title="Dn retention by channel")),
                    width="stretch")

# experiments
with tabs[3]:
    if not M:
        st.info("Run `make analysis` to populate experiment read-outs.")
    else:
        e1, e2 = M["exp1"], M["exp2"]
        st.subheader("Experiment 1: onboarding v2 (new users)")
        a, b, c3 = st.columns(3)
        a.metric("D7 retention lift (iOS + Android)", f"{e1['primary']['abs_diff'] * 100:+.1f} pp",
                 f"95% CI {e1['primary']['ci_low'] * 100:+.1f} to {e1['primary']['ci_high'] * 100:+.1f} pp",
                 delta_color="off")
        b.metric("SRM on web", f"p = {e1['srm_by_platform']['web']['p_value']:.1e}",
                 f"{e1['srm_by_platform']['web']['share_treatment']:.0%} treatment (expected 50%)", delta_color="off")
        c3.metric("Decision", "Ship" if e1["decision"]["ship"] else "Don't ship")
        rows = [e1["naive_primary"], e1["primary"], *e1["secondary"], *e1["guardrails"]]
        df = pd.DataFrame(rows)[["metric", "control", "treatment", "abs_diff", "ci_low", "ci_high", "p_value"]]
        fig = go.Figure()
        fig.add_vline(x=0, line_color=BASELINE)
        fig.add_trace(go.Scatter(
            x=df["abs_diff"] * 100, y=df["metric"], mode="markers", marker=dict(size=10, color=SERIES[0]),
            error_x=dict(type="data", symmetric=False, array=(df["ci_high"] - df["abs_diff"]) * 100,
                         arrayminus=(df["abs_diff"] - df["ci_low"]) * 100, color=SERIES[0]),
            hovertemplate="%{y}<br>%{x:+.2f} pp<extra></extra>"))
        st.plotly_chart(style(fig, 360, legend=False).update_layout(
            title="Treatment - control (pp, 95% CI)", hovermode="closest", yaxis_autorange="reversed"),
            width="stretch")
        st.dataframe(pd.DataFrame(e1["segments"])[["dimension", "segment", "abs_diff", "ci_low", "ci_high", "p_bh"]]
                     .style.format({"abs_diff": "{:+.2%}", "ci_low": "{:+.2%}", "ci_high": "{:+.2%}", "p_bh": "{:.3f}"}),
                     width="stretch", hide_index=True)

        st.subheader("Experiment 2: smart reminders (existing users)")
        a, b, c3 = st.columns(3)
        a.metric("Raw lift (workouts / 28d)", f"{e2['raw']['abs_diff']:+.2f}",
                 f"CI {e2['raw']['ci_low']:+.2f} to {e2['raw']['ci_high']:+.2f}", delta_color="off")
        b.metric("CUPED lift", f"{e2['cuped']['abs_diff']:+.2f}",
                 f"CI {e2['cuped']['ci_low']:+.2f} to {e2['cuped']['ci_high']:+.2f}", delta_color="off")
        c3.metric("Variance reduction", f"{e2['cuped']['variance_reduction']:.0%}")
        wk = pd.DataFrame(e2["weekly"])
        fig = go.Figure(go.Scatter(x=wk["week"], y=wk["abs_diff"], mode="lines+markers", line_color=SERIES[0],
                                   error_y=dict(type="data", symmetric=False, array=wk["ci_high"] - wk["abs_diff"],
                                                arrayminus=wk["abs_diff"] - wk["ci_low"]),
                                   hovertemplate="week %{x}: %{y:+.3f}<extra></extra>"))
        fig.add_hline(y=0, line_color=BASELINE)
        st.plotly_chart(style(fig, 320, legend=False).update_layout(title="Novelty decay: weekly effect (CUPED)"),
                        width="stretch")

# revenue & churn
with tabs[4]:
    mrr = q("SELECT * FROM mart_mrr_monthly ORDER BY month_start")
    a, b = st.columns(2)
    a.plotly_chart(style(px.line(mrr, x="month_start", y="mrr_usd", markers=True, title="MRR"), legend=False),
                   width="stretch")
    mv = go.Figure([go.Bar(x=mrr["month_start"], y=mrr["new_mrr_usd"], name="New MRR", marker_color=POS),
                    go.Bar(x=mrr["month_start"], y=-mrr["churned_mrr_usd"], name="Churned MRR", marker_color=NEG)])
    b.plotly_chart(style(mv).update_layout(barmode="relative", title="MRR movements"), width="stretch")
    if M:
        cm = M["churn_model"]
        st.subheader("Day-14 churn model")
        a, b, c3, d = st.columns(4)
        sel = cm["selected_model"]
        a.metric("Selected model", sel)
        b.metric("Test ROC-AUC", f"{cm['models'][sel]['test_roc_auc']:.3f}")
        c3.metric("Top-decile lift", f"{cm['top_decile_lift']:.2f}x")
        d.metric("Offer value / 1k subs", f"${cm['policy']['value_per_1k_model']:,.0f}",
                 f"vs ${cm['policy']['value_per_1k_target_all']:,.0f} if offered to all", delta_color="off")
        dec = pd.read_csv(C.TABLES_DIR / "churn_deciles.csv")
        fig = px.bar(dec, x="decile", y="churn_rate", title="Observed churn by predicted-risk decile (1 = riskiest)")
        fig.update_traces(marker_color=SERIES[0], hovertemplate="decile %{x}: %{y:.1%}<extra></extra>")
        fig.add_hline(y=cm["base_rate_test"], line_color=MUTED)
        st.plotly_chart(style(fig, 320, legend=False).update_layout(hovermode="closest"), width="stretch")

# marketing
with tabs[5]:
    econ = q("SELECT * FROM mart_channel_economics WHERE spend_usd > 0 ORDER BY ltv_to_cac DESC")
    econ["channel"] = econ["channel"].map(LABEL)
    show = econ[["channel", "spend_usd", "signups", "paid_subscribers", "cac_usd", "ltv_24m_usd", "ltv_to_cac",
                 "payback_months"]]
    st.dataframe(show.style.format({"spend_usd": "${:,.0f}", "signups": "{:,.0f}", "paid_subscribers": "{:,.0f}",
                                    "cac_usd": "${:,.0f}", "ltv_24m_usd": "${:,.0f}", "ltv_to_cac": "{:.2f}x",
                                    "payback_months": "{:.1f}"}, na_rep="never"),
                 width="stretch", hide_index=True)
    daily = q("SELECT * FROM mart_channel_daily WHERE signups > 0")
    daily["channel"] = daily["channel"].map(LABEL)
    fig = px.scatter(daily, x="spend_usd", y="signups", color="channel", color_discrete_map=CH_MAP, opacity=0.6,
                     log_x=True, log_y=True, title="Daily spend vs signups (log-log): diminishing returns")
    st.plotly_chart(style(fig, 380).update_layout(hovermode="closest"), width="stretch")
    if M:
        r = M["marketing"]["reallocation"]
        st.success(f"Re-allocating the same budget (bounded to 0.5-2x per channel) gives "
                   f"{r['paid_subscribers_change_pct']:+.0%} paying subscribers, {r['ltv_change_pct']:+.0%} 24-month LTV, "
                   f"blended CAC ${r['blended_cac_old']:.0f} to ${r['blended_cac_new']:.0f}.")
