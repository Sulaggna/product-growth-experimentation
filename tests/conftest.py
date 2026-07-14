import json
import warnings

import pytest

from growth_analytics import config as C
from growth_analytics import simulate as SIM
from growth_analytics import warehouse as W


@pytest.fixture(scope="session")
def world(tmp_path_factory):
    """Simulate the published seed into a temp dir and build its warehouse (~5 s)."""
    warnings.filterwarnings("ignore")
    out = tmp_path_factory.mktemp("world")
    tables = SIM.simulate(seed=C.SEED)
    SIM.write(tables, out)
    db = W.build(out / "raw", out / "warehouse.duckdb", verbose=False)
    truth = json.loads((out / "ground_truth.json").read_text())
    return {"dir": out, "db": db, "truth": truth}
