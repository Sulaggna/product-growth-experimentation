"""Statistics used in the experiment read-outs.

Written out by hand so each step is visible. tests/test_stats.py checks them against
statsmodels and scipy, and against simulations with a known answer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats


@dataclass
class Effect:
    metric: str
    control: float
    treatment: float
    abs_diff: float
    rel_diff: float
    ci_low: float
    ci_high: float
    p_value: float
    n_control: int
    n_treatment: int
    method: str

    def as_dict(self) -> dict:
        return {k: (float(v) if isinstance(v, (float, np.floating)) else v) for k, v in asdict(self).items()}

    @property
    def significant(self) -> bool:
        return self.ci_low > 0 or self.ci_high < 0


# design
def sample_size_proportions(p_base: float, mde_abs: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Users per arm for a two-sided two-proportion z-test (unpooled variance)."""
    p_t = p_base + mde_abs
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    var = p_base * (1 - p_base) + p_t * (1 - p_t)
    return int(np.ceil((z_a + z_b) ** 2 * var / mde_abs**2))


def mde_proportions(p_base: float, n_per_arm: int, alpha: float = 0.05, power: float = 0.80) -> float:
    """Smallest absolute lift detectable with n users per arm (normal approximation)."""
    z = stats.norm.ppf(1 - alpha / 2) + stats.norm.ppf(power)
    return float(z * np.sqrt(2 * p_base * (1 - p_base) / n_per_arm))


# sanity checks
def srm_test(n_control: int, n_treatment: int, expected_share_treatment: float = 0.5) -> dict:
    """Sample ratio mismatch chi-square test. p < 0.001 is the usual alarm level."""
    n = n_control + n_treatment
    expected = np.array([n * (1 - expected_share_treatment), n * expected_share_treatment])
    chi2, p = stats.chisquare([n_control, n_treatment], expected)
    return {"n_control": int(n_control), "n_treatment": int(n_treatment),
            "share_treatment": n_treatment / n, "chi2": float(chi2), "p_value": float(p)}


# estimators
def two_proportion_test(x_c: int, n_c: int, x_t: int, n_t: int, metric: str = "", alpha: float = 0.05) -> Effect:
    """Difference in proportions: pooled-variance z-test p-value, unpooled Wald CI."""
    p_c, p_t = x_c / n_c, x_t / n_t
    diff = p_t - p_c
    p_pool = (x_c + x_t) / (n_c + n_t)
    se_pool = np.sqrt(p_pool * (1 - p_pool) * (1 / n_c + 1 / n_t))
    z = diff / se_pool if se_pool > 0 else 0.0
    p = 2 * stats.norm.sf(abs(z))
    se = np.sqrt(p_c * (1 - p_c) / n_c + p_t * (1 - p_t) / n_t)
    q = stats.norm.ppf(1 - alpha / 2)
    return Effect(metric, p_c, p_t, diff, diff / p_c if p_c else np.nan, diff - q * se, diff + q * se,
                  float(p), int(n_c), int(n_t), "two-proportion z-test")


def welch_diff(y_c: np.ndarray, y_t: np.ndarray, metric: str = "", alpha: float = 0.05,
               method: str = "Welch t-test") -> Effect:
    """Difference in means with Welch-Satterthwaite degrees of freedom."""
    y_c, y_t = np.asarray(y_c, float), np.asarray(y_t, float)
    m_c, m_t = y_c.mean(), y_t.mean()
    v_c, v_t = y_c.var(ddof=1) / len(y_c), y_t.var(ddof=1) / len(y_t)
    se = np.sqrt(v_c + v_t)
    df = (v_c + v_t) ** 2 / (v_c**2 / (len(y_c) - 1) + v_t**2 / (len(y_t) - 1))
    t = (m_t - m_c) / se
    p = 2 * stats.t.sf(abs(t), df)
    q = stats.t.ppf(1 - alpha / 2, df)
    diff = m_t - m_c
    return Effect(metric, m_c, m_t, diff, diff / m_c if m_c else np.nan, diff - q * se, diff + q * se,
                  float(p), len(y_c), len(y_t), method)


def cuped(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, float, float]:
    """CUPED (Deng et al., 2013): y_adj = y - theta * (x - mean(x)), theta = cov(y, x) / var(x).

    theta is estimated on both arms pooled. x is measured before treatment, so the
    estimate stays unbiased. Returns (y_adj, theta, variance_reduction).
    """
    y, x = np.asarray(y, float), np.asarray(x, float)
    theta = np.cov(y, x, ddof=1)[0, 1] / x.var(ddof=1)
    y_adj = y - theta * (x - x.mean())
    reduction = 1 - y_adj.var(ddof=1) / y.var(ddof=1)
    return y_adj, float(theta), float(reduction)


def cuped_effect(y_c, y_t, x_c, x_t, metric: str = "", alpha: float = 0.05) -> tuple[Effect, dict]:
    y = np.concatenate([y_c, y_t])
    x = np.concatenate([x_c, x_t])
    y_adj, theta, red = cuped(y, x)
    n_c = len(y_c)
    eff = welch_diff(y_adj[:n_c], y_adj[n_c:], metric, alpha, method="CUPED + Welch t-test")
    # keep the unadjusted arm means for display, the diff and CI are adjusted
    eff.control, eff.treatment = float(np.mean(y_c)), float(np.mean(y_c)) + eff.abs_diff
    eff.rel_diff = eff.abs_diff / eff.control
    return eff, {"theta": theta, "variance_reduction": red, "corr": float(np.corrcoef(y, x)[0, 1])}


def bootstrap_diff_ci(y_c, y_t, n_boot: int = 4000, alpha: float = 0.05, seed: int = 7,
                      chunk: int = 500) -> tuple[float, float]:
    """Percentile bootstrap CI for a difference in means. Useful for heavy-tailed metrics."""
    rng = np.random.default_rng(seed)
    y_c, y_t = np.asarray(y_c, float), np.asarray(y_t, float)
    diffs = []
    for start in range(0, n_boot, chunk):
        b = min(chunk, n_boot - start)
        mc = y_c[rng.integers(0, len(y_c), (b, len(y_c)))].mean(axis=1)
        mt = y_t[rng.integers(0, len(y_t), (b, len(y_t)))].mean(axis=1)
        diffs.append(mt - mc)
    d = np.concatenate(diffs)
    return float(np.quantile(d, alpha / 2)), float(np.quantile(d, 1 - alpha / 2))


def ratio_metric_delta(num_c, den_c, num_t, den_t, metric: str = "", alpha: float = 0.05) -> Effect:
    """Difference of ratio metrics (e.g. crashes per session) with delta-method variance.

    Users are randomised but the metric is per session, so a per-session variance
    would be too small. The delta method accounts for that.
    """
    def ratio_and_var(num, den):
        num, den = np.asarray(num, float), np.asarray(den, float)
        n = len(num)
        mx, my = num.mean(), den.mean()
        r = mx / my
        vx, vy = num.var(ddof=1), den.var(ddof=1)
        cxy = np.cov(num, den, ddof=1)[0, 1]
        var = (vx / my**2 - 2 * mx * cxy / my**3 + mx**2 * vy / my**4) / n
        return r, var, n

    r_c, v_c, n_c = ratio_and_var(num_c, den_c)
    r_t, v_t, n_t = ratio_and_var(num_t, den_t)
    diff = r_t - r_c
    se = np.sqrt(v_c + v_t)
    p = 2 * stats.norm.sf(abs(diff / se))
    q = stats.norm.ppf(1 - alpha / 2)
    return Effect(metric, r_c, r_t, diff, diff / r_c if r_c else np.nan, diff - q * se, diff + q * se,
                  float(p), n_c, n_t, "delta-method z-test")


# multiple testing
def holm(p_values) -> np.ndarray:
    """Holm-Bonferroni step-down adjusted p-values (controls family-wise error)."""
    p = np.asarray(p_values, float)
    m = len(p)
    order = np.argsort(p)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p[i])
        adj[i] = min(1.0, running)
    return adj


def benjamini_hochberg(p_values) -> np.ndarray:
    """BH adjusted p-values (controls the false-discovery rate), used for segment scans."""
    p = np.asarray(p_values, float)
    m = len(p)
    order = np.argsort(p)[::-1]
    adj = np.empty(m)
    running = 1.0
    for rank, i in enumerate(order):
        running = min(running, p[i] * m / (m - rank))
        adj[i] = running
    return adj
