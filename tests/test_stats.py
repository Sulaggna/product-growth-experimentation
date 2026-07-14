import numpy as np
import pytest
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportions_ztest

from growth_analytics import stats as S


def test_holm_and_bh_match_statsmodels():
    p = np.array([0.001, 0.04, 0.03, 0.2, 0.012, 0.6])
    assert np.allclose(S.holm(p), multipletests(p, method="holm")[1])
    assert np.allclose(S.benjamini_hochberg(p), multipletests(p, method="fdr_bh")[1])


def test_two_proportion_test_matches_statsmodels():
    e = S.two_proportion_test(300, 1000, 345, 1000)
    _, p = proportions_ztest([345, 300], [1000, 1000])
    assert e.p_value == pytest.approx(p, rel=1e-9)
    assert e.abs_diff == pytest.approx(0.045)
    assert e.ci_low < 0.045 < e.ci_high


def test_sample_size_textbook_value_and_mde_round_trip():
    # p=0.5 -> 0.6: (1.96 + 0.84)^2 * (0.25 + 0.24) / 0.01 = 384.6
    assert S.sample_size_proportions(0.5, 0.1) == 385
    n = S.sample_size_proportions(0.36, 0.025)
    assert S.mde_proportions(0.36, n) == pytest.approx(0.025, rel=0.03)


def test_srm_flags_imbalance_only():
    assert S.srm_test(5000, 5030)["p_value"] > 0.5
    assert S.srm_test(5200, 4800)["p_value"] < 0.001


def test_welch_matches_scipy():
    rng = np.random.default_rng(1)
    a, b = rng.lognormal(1, 1, 800), rng.lognormal(1.1, 1.2, 900)
    e = S.welch_diff(a, b)
    assert e.p_value == pytest.approx(stats.ttest_ind(b, a, equal_var=False).pvalue, rel=1e-9)


def test_cuped_is_unbiased_and_reduces_variance():
    rng = np.random.default_rng(2)
    true_effect, est, raw_se, cup_se = 0.5, [], [], []
    for _ in range(300):
        x = rng.gamma(2.0, 3.0, 2000)
        y = 0.8 * x + rng.normal(0, 3, 2000)
        t = rng.random(2000) < 0.5
        y = y + true_effect * t
        e, info = S.cuped_effect(y[~t], y[t], x[~t], x[t])
        r = S.welch_diff(y[~t], y[t])
        est.append(e.abs_diff)
        raw_se.append(r.ci_high - r.ci_low)
        cup_se.append(e.ci_high - e.ci_low)
    assert np.mean(est) == pytest.approx(true_effect, abs=0.03)
    assert np.mean(cup_se) < 0.75 * np.mean(raw_se)
    # variance reduction should be close to corr(x, y)^2
    assert info["variance_reduction"] == pytest.approx(info["corr"] ** 2, abs=0.02)


def test_bootstrap_ci_agrees_with_welch_for_large_samples():
    rng = np.random.default_rng(3)
    a, b = rng.exponential(2.0, 4000), rng.exponential(2.2, 4000)
    lo, hi = S.bootstrap_diff_ci(a, b, n_boot=3000)
    w = S.welch_diff(a, b)
    assert lo == pytest.approx(w.ci_low, abs=0.03)
    assert hi == pytest.approx(w.ci_high, abs=0.03)


def test_delta_method_se_matches_bootstrap():
    rng = np.random.default_rng(4)
    n = 3000
    den_c, den_t = rng.poisson(5, n) + 1, rng.poisson(5, n) + 1
    num_c, num_t = rng.binomial(den_c, 0.05), rng.binomial(den_t, 0.06)
    e = S.ratio_metric_delta(num_c, den_c, num_t, den_t)
    se_delta = (e.ci_high - e.ci_low) / (2 * 1.959964)
    boots = []
    for _ in range(1000):
        i, j = rng.integers(0, n, n), rng.integers(0, n, n)
        boots.append(num_t[j].sum() / den_t[j].sum() - num_c[i].sum() / den_c[i].sum())
    assert se_delta == pytest.approx(np.std(boots), rel=0.12)
