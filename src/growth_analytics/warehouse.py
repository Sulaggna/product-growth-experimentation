"""Build the DuckDB warehouse by running ``sql/*.sql`` in order.

The SQL files are plain DuckDB SQL. A few ``{{ name }}`` placeholders (paths and
dates) are filled in here, so the files can also be read and run on their own.

Run:  ``python -m growth_analytics.warehouse``
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import duckdb
import pandas as pd

from . import config as C

PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def default_params(raw_dir: Path | None = None) -> dict[str, str]:
    return {
        "raw_dir": Path(raw_dir or C.RAW_DIR).as_posix(),
        "signup_start": C.SIGNUP_START.isoformat(),
        "obs_end": C.OBS_END.isoformat(),
        "trial_days": str(C.TRIAL_DAYS),
        "exp2_pre_start": C.EXP2["pre_start"].isoformat(),
        "exp2_pre_end": C.EXP2["pre_end"].isoformat(),
        "exp2_start": C.EXP2["start"].isoformat(),
        "exp2_end": C.EXP2["end"].isoformat(),
    }


def render(sql: str, params: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in params:
            raise KeyError(f"SQL placeholder '{{{{ {key} }}}}' has no value")
        return params[key]

    return PLACEHOLDER.sub(sub, sql)


def run_sql_file(con: duckdb.DuckDBPyConnection, path: Path, params: dict[str, str]) -> None:
    con.execute(render(Path(path).read_text(), params))


def sql_files() -> list[Path]:
    return sorted(C.SQL_DIR.glob("[0-9][0-9]_*.sql"))


def build(raw_dir: Path | None = None, db_path: Path | None = None, verbose: bool = True) -> Path:
    db_path = Path(db_path or C.WAREHOUSE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    params = default_params(raw_dir)
    with duckdb.connect(str(db_path)) as con:
        for f in sql_files():
            t0 = time.time()
            run_sql_file(con, f, params)
            if verbose:
                print(f"  ran {f.name:<28} {time.time() - t0:5.1f}s")
        if verbose:
            tables = con.execute(
                "SELECT table_name, estimated_size FROM duckdb_tables() ORDER BY table_name"
            ).fetchall()
            for name, rows in tables:
                print(f"  {name:<28} {rows:>12,} rows")
    return db_path


def connect(db_path: Path | None = None, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    path = Path(db_path or C.WAREHOUSE_PATH)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run `make data warehouse` first")
    return duckdb.connect(str(path), read_only=read_only)


def read(table_or_sql: str, db_path: Path | None = None) -> pd.DataFrame:
    """Return a table (by name) or the result of a SELECT as a DataFrame."""
    sql = table_or_sql if " " in table_or_sql.strip() else f"SELECT * FROM {table_or_sql}"
    with connect(db_path) as con:
        return con.execute(sql).df()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build the DuckDB warehouse")
    ap.add_argument("--raw", type=Path, default=C.RAW_DIR)
    ap.add_argument("--db", type=Path, default=C.WAREHOUSE_PATH)
    args = ap.parse_args(argv)
    t0 = time.time()
    path = build(args.raw, args.db)
    print(f"warehouse built in {time.time() - t0:.1f}s -> {path}")


if __name__ == "__main__":
    main()
