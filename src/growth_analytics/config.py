"""Project-wide paths and business constants.

Prices, experiment dates and the retention offer assumptions live here so the
analysis code does not hard-code them.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("GROWTH_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"
GROUND_TRUTH_PATH = DATA_DIR / "ground_truth.json"

SQL_DIR = ROOT / "sql"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
TABLES_DIR = REPORTS_DIR / "tables"
METRICS_PATH = REPORTS_DIR / "metrics.json"

SEED = 11  # published run; see `make validate` for the 40-seed coverage study

# observation window
SIGNUP_START = dt.date(2025, 1, 1)
SIGNUP_END = dt.date(2026, 1, 31)  # acquisition continues to the end of the data
OBS_END = dt.date(2026, 1, 31)  # last day of event data ("today" for the analysis)

# monetisation
TRIAL_DAYS = 7
PRICES = {"monthly": 12.99, "annual": 79.99}  # USD, list price
STORE_FEE = {"ios": 0.15, "android": 0.15, "web": 0.03}  # app-store / payment fee

# experiments
EXP1 = {
    "name": "onboarding_v2",
    "start": dt.date(2025, 9, 1),
    "end": dt.date(2025, 10, 12),
}
EXP2 = {
    "name": "smart_reminders",
    "pre_start": dt.date(2025, 10, 6),
    "pre_end": dt.date(2025, 11, 2),
    "start": dt.date(2025, 11, 3),
    "end": dt.date(2025, 11, 30),
}
ALPHA = 0.05
POWER = 0.80

# retention-offer economics (churn model)
OFFER = {
    "discount_usd": 6.50,        # 50% off the next monthly charge
    "save_rate": 0.30,           # share of would-be churners the offer retains
    "redeem_rate_non_churners": 0.60,  # loyal users who also take the discount
    "extra_months_if_saved": 3.0,
}
