"""Versioned logical table contracts and small record-level smoke checks.

Parquet/Arrow physical schemas and whole-table integrity checks belong to the
stage that first writes each table. S00 intentionally performs no Parquet I/O.
"""

import json
import math
from datetime import datetime
from importlib.resources import files
from zoneinfo import ZoneInfo


def load_contracts() -> dict:
    """Return the bundled schema catalog, including its semantic version."""
    return json.loads(files("portoflow").joinpath("schema_v1.json").read_text(encoding="utf-8"))


def validate_record(table: str, record: dict, contracts: dict | None = None) -> None:
    """Validate one JSON-friendly fixture against the S00 logical contract."""
    catalog = contracts if contracts is not None else load_contracts()
    try:
        fields = catalog["tables"][table]["fields"]
    except KeyError as exc:
        raise ValueError(f"Unknown table: {table}") from exc
    if set(record) != set(fields):
        missing = sorted(set(fields) - set(record))
        extra = sorted(set(record) - set(fields))
        raise ValueError(f"{table} columns differ: missing={missing}, extra={extra}")

    for name, spec in fields.items():
        value = record[name]
        if value is None:
            if not spec["nullable"]:
                raise ValueError(f"{table}.{name} may not be null")
            continue
        kind = spec["type"]
        if kind == "string" and not isinstance(value, str):
            raise ValueError(f"{table}.{name} must be string")
        if kind == "int64" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(f"{table}.{name} must be integer")
        if kind == "float64" and (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)):
            raise ValueError(f"{table}.{name} must be finite number")
        if kind == "list<string>" and (not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            raise ValueError(f"{table}.{name} must be list of strings")
        if kind.startswith("timestamp["):
            if not isinstance(value, str):
                raise ValueError(f"{table}.{name} must be ISO timestamp string in fixture")
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{table}.{name} is not ISO timestamp") from exc
            if parsed.tzinfo is None:
                raise ValueError(f"{table}.{name} must be timezone-aware")
            if kind == "timestamp[us,UTC]" and parsed.utcoffset().total_seconds() != 0:
                raise ValueError(f"{table}.{name} must have UTC offset")
        if kind == "date32":
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{table}.{name} must be YYYY-MM-DD") from exc
    if table == "gps_points":
        if not (-180 <= record["lon"] <= 180 and -90 <= record["lat"] <= 90):
            raise ValueError("gps_points coordinates must be [lon, lat] in WGS84")
        if record["point_idx"] < 0:
            raise ValueError("point_idx must be nonnegative")
        utc = datetime.fromisoformat(record["event_time_utc"])
        local = datetime.fromisoformat(record["event_time_local"])
        if utc != local or local.utcoffset() != ZoneInfo("Europe/Lisbon").utcoffset(utc.astimezone(ZoneInfo("Europe/Lisbon"))):
            raise ValueError("UTC and Lisbon event times must represent the same instant")
    if table == "congestion_profiles":
        if record["status"] not in {"normal", "slow", "high_slowdown", "unknown"}:
            raise ValueError("Invalid congestion profile status")
        if any(record[field] < 0 for field in ("distinct_taxis", "distinct_trips", "distinct_dates")):
            raise ValueError("Support counts must be nonnegative")
        if record["status"] == "unknown" and record["confidence"] != "insufficient":
            raise ValueError("Unknown profile must have insufficient confidence")
        if record["status"] != "unknown":
            if record["median_speed_kmh"] is None or record["reference_speed_kmh"] is None:
                raise ValueError("Known status requires both speed estimates")
            if record["median_speed_kmh"] <= 0 or record["reference_speed_kmh"] <= 0:
                raise ValueError("Known status requires positive speeds")
            if not all(record[field] > 0 for field in ("distinct_taxis", "distinct_trips", "distinct_dates")):
                raise ValueError("Known status requires independent support")
            if record["reference_source"] is None or record["slowdown_ratio"] is None:
                raise ValueError("Known status requires source and slowdown ratio")
            if not 0 <= record["slowdown_ratio"] <= 1:
                raise ValueError("Slowdown ratio must be between zero and one")
