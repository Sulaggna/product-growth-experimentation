import numpy as np
import pandas as pd

from growth_analytics import config as C
from growth_analytics import simulate as SIM
from growth_analytics.warehouse import read


def test_hash_uniform_is_deterministic_and_uniform():
    u = SIM.hash_uniform(1, 2, np.arange(50_000), 3)
    assert np.array_equal(u, SIM.hash_uniform(1, 2, np.arange(50_000), 3))
    assert 0 < u.min() and u.max() < 1
    assert abs(u.mean() - 0.5) < 0.01
    # different stream -> uncorrelated draws
    v = SIM.hash_uniform(1, 3, np.arange(50_000), 3)
    assert abs(np.corrcoef(u, v)[0, 1]) < 0.02


def test_same_seed_same_data():
    a = SIM.simulate(scale=0.05, seed=5)
    b = SIM.simulate(scale=0.05, seed=5)
    pd.testing.assert_frame_equal(a["users"], b["users"])
    assert len(a["events"]) == len(b["events"])


def test_events_are_inside_the_observation_window(world):
    r = read("SELECT min(event_ts) AS lo, max(event_ts) AS hi FROM stg_events", world["db"]).iloc[0]
    assert r["lo"] >= pd.Timestamp(C.SIGNUP_START)
    assert r["hi"] < pd.Timestamp(C.OBS_END) + pd.Timedelta(days=1)


def test_every_subscription_has_a_first_charge(world):
    n = read("""SELECT count(*) AS n FROM stg_subscriptions s
                LEFT JOIN stg_charges c ON c.subscription_id = s.subscription_id AND c.charge_type = 'new'
                WHERE c.charge_id IS NULL""", world["db"])["n"].iloc[0]
    assert n == 0


def test_cancelled_subscriptions_end_after_they_start(world):
    bad = read("SELECT count(*) AS n FROM stg_subscriptions WHERE end_date <= start_date", world["db"])["n"].iloc[0]
    assert bad == 0
