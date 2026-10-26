"""Inferred traversal speeds with explicit GPS-gap and time-bucket provenance."""

import math
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import bucket_for_local_time


def split_local_buckets(start: datetime, end: datetime, config: dict):
    """Split in UTC at actual Lisbon bucket/day boundaries, preserving elapsed seconds across DST."""
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        raise ValueError("Positive aware time interval required")
    zone = ZoneInfo("Europe/Lisbon")
    day = start.astimezone(zone).date()
    last = end.astimezone(zone).date() + timedelta(days=1)
    cuts = {start.astimezone(timezone.utc), end.astimezone(timezone.utc)}
    while day <= last:
        for hour in config["time"]["bucket_boundaries_hour"][:-1]:
            instant = datetime.combine(day, time(hour), tzinfo=zone).astimezone(timezone.utc)
            if start < instant < end:
                cuts.add(instant)
        day += timedelta(days=1)
    ordered = sorted(cuts)
    for entry, exit_time in zip(ordered, ordered[1:]):
        local = entry.astimezone(zone)
        group, bucket = bucket_for_local_time(local, config)
        yield entry, exit_time, local.date(), group, bucket


def build_observations(traversals: list[dict], config: dict) -> list[dict]:
    counts = Counter()
    gap_sizes = Counter((row["trip_id"], row["gap_index"]) for row in traversals)
    result = []
    for row in traversals:
        duration = (row["estimated_exit_utc"] - row["estimated_entry_utc"]).total_seconds()
        if duration <= 0:
            continue  # Zero-duration boundary pieces contribute no distance or support.
        speed = row["traveled_distance_m"] / duration * 3.6
        if not math.isfinite(speed) or speed > config["speed_rules"]["max_speed_kmh"]:
            quality = "implausible_speed"
        elif speed <= 0:
            quality = "zero_matched_displacement_excluded"
        elif duration < config["speed_rules"]["min_inferred_duration_s"]:
            quality = "short_inferred_duration_excluded"
        else:
            quality = "accepted_inferred"
        for entry, exit_time, date, group, bucket in split_local_buckets(row["estimated_entry_utc"], row["estimated_exit_utc"], config):
            seconds = (exit_time - entry).total_seconds()
            index = counts[row["trip_id"]]
            counts[row["trip_id"]] += 1
            result.append({"trip_id": row["trip_id"], "taxi_id": row["taxi_id"], "edge_id": row["edge_id"],
                "traversal_idx": index, "gap_index": row["gap_index"],
                "estimated_entry_utc": entry, "estimated_exit_utc": exit_time,
                "observed_or_inferred_duration_s": seconds, "traveled_distance_m": row["traveled_distance_m"] * seconds / duration,
                "estimated_speed_kmh": speed, "local_date": date,
                "day_group": group, "time_bucket": bucket,
                "time_inference_flag": "inferred_from_nominal_15s_complete_GPS_gap",
                "gap_edge_count": gap_sizes[(row["trip_id"], row["gap_index"])],
                "quality_flag": quality, "graph_version": row["graph_version"]})
    return result


def inference_diagnostics(observations: list[dict]) -> dict:
    gaps = {}
    for row in observations:
        gaps[(row["trip_id"], row["gap_index"])] = row["gap_edge_count"]
    return {"edge_observations": len(observations), "gps_intervals": len(gaps),
            "multi_edge_interval_fraction": sum(n > 1 for n in gaps.values()) / len(gaps) if gaps else None,
            "duration_under_1s_fraction": sum(r["observed_or_inferred_duration_s"] < 1 for r in observations) / len(observations) if observations else None,
            "quality_flags": dict(Counter(row["quality_flag"] for row in observations)),
            "limitation": "Edge timing is distance-proportional interpolation, not observed edge-level truth"}
