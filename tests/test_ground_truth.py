"""The analysis should recover the effects planted in the simulator."""

import pytest

from growth_analytics import experiments as E
from growth_analytics import marketing as MK
from growth_analytics import simulate as SIM
from growth_analytics.warehouse import read


@pytest.fixture(scope="module")
def results(world):
    db = world["db"]
    e1 = E.analyze_onboarding(read("mart_exp_onboarding", db))
    e2 = E.analyze_reminders(read("mart_exp_reminders", db), n_boot=500)
    return e1, e2, E.compare_to_truth(e1, e2, world["truth"])


def test_srm_is_caught_on_web_only(results):
    e1, _, _ = results
    assert e1["srm_by_platform"]["web"]["p_value"] < 1e-3
    assert e1["srm_by_platform"]["ios"]["p_value"] > 0.01
    assert e1["srm_by_platform"]["android"]["p_value"] > 0.01


def test_onboarding_estimate_recovers_truth(results):
    _, _, c = results
    assert c["exp1_d7"]["ci_covers_truth"]
    assert abs(c["exp1_d7"]["z_error"]) < 2.5


def test_web_only_estimate_is_biased_by_the_logging_bug(results):
    _, _, c = results
    assert c["exp1_web_only"]["estimate"] > c["exp1_web_only"]["truth"] + 0.03


def test_onboarding_ships_and_android_effect_is_larger(results):
    e1, _, _ = results
    assert e1["decision"]["ship"]
    seg = {s["segment"]: s["abs_diff"] for s in e1["segments"]}
    assert seg["android"] > seg["ios"]


def test_cuped_recovers_truth_with_less_variance(results):
    _, e2, c = results
    assert c["exp2_workouts"]["ci_covers_truth"]
    assert e2["cuped"]["variance_reduction"] > 0.4
    assert (e2["cuped"]["ci_high"] - e2["cuped"]["ci_low"]) < (e2["raw"]["ci_high"] - e2["raw"]["ci_low"])


def test_novelty_effect_decays(results):
    _, e2, _ = results
    w = [x["abs_diff"] for x in e2["weekly"]]
    assert w[0] > w[3]


def test_spend_elasticities_are_recovered(world):
    curves = MK.response_curves(read("mart_channel_daily", world["db"])).set_index("channel")
    for ch, planted in SIM.SPEND_ELASTICITY.items():
        assert curves.loc[ch, "elasticity"] == pytest.approx(planted, abs=0.12)
