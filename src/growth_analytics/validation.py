"""Coverage study for the experiment estimators.

One simulated dataset is a single draw. This re-runs the whole pipeline (simulate,
warehouse, analysis) with independent seeds and compares each estimate with that
run's ground truth, to check bias and CI coverage.

Run:  ``python -m growth_analytics.validation --seeds 40``   (about 4 minutes)
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
import warnings
from pathlib import Path

import pandas as pd

from . import config as C
from . import experiments as E
from . import simulate as SIM
from . import warehouse as W

COVERAGE_PATH = C.TABLES_DIR / "estimator_coverage.csv"


def one_run(seed: int, workdir: Path) -> dict:
    out = workdir / str(seed)
    SIM.write(SIM.simulate(seed=seed), out)
    db = W.build(out / "raw", out / "warehouse.duckdb", verbose=False)
    e1 = E.analyze_onboarding(W.read("mart_exp_onboarding", db))
    e2 = E.analyze_reminders(W.read("mart_exp_reminders", db), n_boot=200)
    truth = json.loads((out / "ground_truth.json").read_text())
    c = E.compare_to_truth(e1, e2, truth)
    return {
        "seed": seed,
        "exp1_estimate": c["exp1_d7"]["estimate"], "exp1_truth": c["exp1_d7"]["truth"],
        "exp1_z": c["exp1_d7"]["z_error"], "exp1_covered": c["exp1_d7"]["ci_covers_truth"],
        "exp1_naive_estimate": c["exp1_naive_d7"]["estimate"],
        "exp1_srm_web_flagged": e1["srm_by_platform"]["web"]["p_value"] < 0.001,
        "exp1_srm_mobile_false_alarm": min(e1["srm_by_platform"]["ios"]["p_value"],
                                           e1["srm_by_platform"]["android"]["p_value"]) < 0.001,
        "exp2_estimate": c["exp2_workouts"]["estimate_cuped"], "exp2_raw": c["exp2_workouts"]["estimate_raw"],
        "exp2_truth": c["exp2_workouts"]["truth"], "exp2_z": c["exp2_workouts"]["z_error"],
        "exp2_covered": c["exp2_workouts"]["ci_covers_truth"],
        "exp2_variance_reduction": e2["cuped"]["variance_reduction"],
    }


def run(seeds, out_csv: Path = COVERAGE_PATH) -> pd.DataFrame:
    warnings.filterwarnings("ignore")
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, s in enumerate(seeds, 1):
            t0 = time.time()
            rows.append(one_run(s, Path(tmp)))
            print(f"  [{i}/{len(seeds)}] seed {s}: exp1 z={rows[-1]['exp1_z']:+.2f}  "
                  f"exp2 z={rows[-1]['exp2_z']:+.2f}  ({time.time() - t0:.1f}s)")
    df = pd.DataFrame(rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    return df


def summarise(df: pd.DataFrame) -> dict:
    return {
        "runs": int(len(df)),
        "exp1_coverage": float(df["exp1_covered"].mean()),
        "exp1_mean_z": float(df["exp1_z"].mean()),
        "exp1_naive_bias_pp": float((df["exp1_naive_estimate"] - df["exp1_truth"]).mean()),
        "exp1_srm_detection_rate": float(df["exp1_srm_web_flagged"].mean()),
        "exp1_srm_false_alarm_rate": float(df["exp1_srm_mobile_false_alarm"].mean()),
        "exp2_coverage": float(df["exp2_covered"].mean()),
        "exp2_mean_z": float(df["exp2_z"].mean()),
        "exp2_rmse_cuped": float(((df["exp2_estimate"] - df["exp2_truth"]) ** 2).mean() ** 0.5),
        "exp2_rmse_raw": float(((df["exp2_raw"] - df["exp2_truth"]) ** 2).mean() ** 0.5),
        "exp2_mean_variance_reduction": float(df["exp2_variance_reduction"].mean()),
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Estimator coverage study")
    ap.add_argument("--seeds", type=int, default=40, help="number of independent seeds")
    ap.add_argument("--first-seed", type=int, default=101)
    args = ap.parse_args(argv)
    df = run(list(range(args.first_seed, args.first_seed + args.seeds)))
    print(json.dumps(summarise(df), indent=2))


if __name__ == "__main__":
    main()
