"""Load and validate pipeline configuration; no data processing occurs here."""

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import math

import yaml
from .contracts import load_contracts


def load_config(path: str | Path) -> dict:
    """Read a YAML mapping and enforce the current stage's core invariants."""
    with Path(path).open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    validate_config(config)
    return config


def validate_config(config: object) -> None:
    """Reject incompatible schema, time buckets, or coordinate conventions."""
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML mapping")
    if config.get("schema_version") != load_contracts()["schema_version"]:
        raise ValueError(f"Expected schema_version {load_contracts()['schema_version']}")
    if type(config.get("random_seed")) is not int:
        raise ValueError("random_seed must be an integer")

    time = config.get("time")
    if not isinstance(time, dict):
        raise ValueError("time must be a mapping")
    if time.get("source_timezone") != "UTC":
        raise ValueError("Source timestamps must be UTC")
    if time.get("analysis_timezone") != "Europe/Lisbon":
        raise ValueError("Porto analysis_timezone must be Europe/Lisbon")
    try:
        ZoneInfo(time.get("analysis_timezone", ""))
    except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
        raise ValueError("Invalid analysis_timezone") from exc
    groups = time.get("day_groups")
    if groups != {"weekday": [0, 1, 2, 3, 4], "weekend": [5, 6]}:
        raise ValueError("day_groups must partition local Monday-Sunday")
    boundaries = time.get("bucket_boundaries_hour")
    if (
        not isinstance(boundaries, list)
        or len(boundaries) != 7
        or boundaries[0] != 0
        or boundaries[-1] != 24
        or any(type(hour) is not int for hour in boundaries)
        or any(left >= right for left, right in zip(boundaries, boundaries[1:]))
    ):
        raise ValueError("Six increasing local-hour intervals from 0 to 24 required")

    geometry = config.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("source_crs") != "EPSG:4326" or geometry.get("display_crs") != "EPSG:4326":
        raise ValueError("Source and display CRS must be EPSG:4326")
    if config.get("dataset", {}).get("nominal_sample_interval_seconds") != 15:
        raise ValueError("Porto complete trajectories use a nominal 15-second interval")
    settings = config.get("s01", {})
    for key in ("max_rows", "batch_size", "max_points_per_trip", "sample_per_stratum", "points_per_partition"):
        if type(settings.get(key)) is not int or settings[key] <= 0:
            raise ValueError(f"s01.{key} must be a positive integer")
    if not 1 <= settings["batch_size"] <= settings["max_rows"] <= 5000:
        raise ValueError("S01 budget requires batch_size <= max_rows <= 5000")
    bbox = settings.get("qc_bbox_lonlat")
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(type(x) in (float, int) for x in bbox):
        raise ValueError("s01.qc_bbox_lonlat must contain four numbers")
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Invalid S01 QC bbox")
    for section, keys in {
        "matching": ["candidate_radius_m", "gps_sigma_m", "transition_beta_m", "max_median_residual_m", "max_gap_speed_kmh", "ubodt_distance_m"],
        "speed_rules": ["max_speed_kmh", "min_inferred_duration_s"],
        "route_rules": ["fallback_speed_kmh", "unknown_cost_multiplier"],
    }.items():
        for key in keys:
            value = config.get(section, {}).get(key)
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{section}.{key} must be positive and finite")
    if not 1 <= config["matching"].get("max_candidates", 0) <= 16:
        raise ValueError("Small matcher requires 1..16 candidates")
    if not 0 < config["matching"].get("minimum_success_fraction", 0) <= 1:
        raise ValueError("Invalid matching success stop rule")
    if config["route_rules"]["unknown_cost_multiplier"] < 1:
        raise ValueError("Unknown route cost multiplier must be at least one")
    if not 0 <= config.get("evaluation", {}).get("maximum_unknown_distance_fraction", -1) <= 1:
        raise ValueError("Invalid evaluation coverage rule")
    for key in ("window_minutes", "min_distinct_trips", "min_distinct_taxis"):
        if type(config.get("events", {}).get(key)) is not int or config["events"][key] <= 0:
            raise ValueError(f"events.{key} must be a positive integer")


def bucket_for_local_time(local_time, config: dict) -> tuple[str, str]:
    """Map an aware Lisbon passage time to a day group and half-open bucket."""
    if local_time.tzinfo is None:
        raise ValueError("Passage time must be timezone-aware")
    zone = config["time"]["analysis_timezone"]
    if getattr(local_time.tzinfo, "key", None) != zone:
        raise ValueError(f"Passage time must use {zone}")
    group = "weekday" if local_time.weekday() < 5 else "weekend"
    boundaries = config["time"]["bucket_boundaries_hour"]
    hour = local_time.hour
    for start, end in zip(boundaries, boundaries[1:]):
        if start <= hour < end:
            return group, f"{start:02d}-{end:02d}"
    raise AssertionError("Validated boundaries should cover every local hour")

