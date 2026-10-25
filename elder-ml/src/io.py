from __future__ import annotations

from pathlib import Path
import pandas as pd

SIGNALS = ["hr_bpm", "spo2_pct", "sbp_mmhg", "dbp_mmhg", "skin_temp_c", "motion_g"]
LABELS = ["gt_worn", "gt_activity", "gt_state"]
EXPECTED_ROWS = 2_419_200


def data_dir(path: str | Path | None = None) -> Path:
    return Path(path) if path else Path(__file__).resolve().parents[2] / "elder_vitals_14day"


def load_person(person: str, root: str | Path | None = None) -> pd.DataFrame:
    path = data_dir(root) / f"elder_{person}.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    columns = ["person_id", "timestamp", "day", "t_sec", *SIGNALS, *LABELS]
    return pd.read_parquet(path, columns=columns)


def load_events(root: str | Path | None = None) -> pd.DataFrame:
    ev = pd.read_csv(data_dir(root) / "events.csv", parse_dates=["start", "end"])
    ev["day"] = ev["day"].astype("int8")
    return ev


def qa(root: str | Path | None = None) -> pd.DataFrame:
    root = data_dir(root)
    rows = []
    for p in sorted(root.glob("elder_E*.parquet")):
        pf = pd.read_parquet(p, columns=["timestamp", "gt_worn", *SIGNALS])
        ts = pd.to_datetime(pf.timestamp)
        spacing_ok = ts.diff().dropna().dt.total_seconds().eq(0.5).all()
        rows.append({"person": p.stem[-2:], "rows": len(pf), "spacing_500ms": bool(spacing_ok),
                     "worn_pct": round(100 * pf.gt_worn.mean(), 2),
                     "missing_hr_pct": round(100 * pf.hr_bpm.isna().mean(), 2),
                     "missing_spo2_pct": round(100 * pf.spo2_pct.isna().mean(), 2),
                     "missing_sbp_pct": round(100 * pf.sbp_mmhg.isna().mean(), 2),
                     "row_count_ok": len(pf) == EXPECTED_ROWS})
    result = pd.DataFrame(rows)
    if len(result) != 5:
        raise ValueError(f"Expected five Parquet files; found {len(result)}")
    return result
