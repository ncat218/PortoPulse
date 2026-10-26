"""Training-only historical relative-slowdown profiles and coverage sensitivity."""

import math
import re
from collections import defaultdict
from statistics import median


def quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def parse_maxspeed(raw: str) -> float | None:
    """Conservatively parse numerical km/h or mph; special OSM values stay unknown."""
    values = []
    for token in re.split(r"[;\[\],\"]", raw or ""):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kph)?\s*", token)
        if match:
            speed = float(match[1]) * (1.609344 if match[2] == "mph" else 1)
            if 0 < speed <= 160:
                values.append(speed)
    return min(values) if values else None


def validate_rules(rules: dict):
    for name in ("min_distinct_trips", "min_distinct_taxis", "min_distinct_dates"):
        if type(rules.get(name)) is not int or rules[name] < 1:
            raise ValueError(f"Set {name} explicitly after QC; support rules cannot be null")
    high, slow = rules.get("high_slowdown_ratio_threshold"), rules.get("slow_ratio_threshold")
    if not isinstance(high, (int, float)) or not isinstance(slow, (int, float)) or not 0 < high < slow < 1:
        raise ValueError("Require 0 < high_slowdown_ratio_threshold < slow_ratio_threshold < 1")


def support(rows: list[dict]) -> dict:
    return {"distinct_trips": len({r["trip_id"] for r in rows}), "distinct_taxis": len({r["taxi_id"] for r in rows}),
            "distinct_dates": len({r["local_date"] for r in rows})}


def adequate(rows: list[dict], rules: dict) -> bool:
    counts = support(rows)
    return all(counts[name] >= rules["min_" + name] for name in counts)


def trip_speeds(rows: list[dict]) -> list[float]:
    """Give each independent trip one distance/time representative, not one vote per tiny edge piece."""
    grouped = defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        grouped[row["trip_id"]][0] += row["traveled_distance_m"]
        grouped[row["trip_id"]][1] += row["observed_or_inferred_duration_s"]
    return [distance / duration * 3.6 for distance, duration in grouped.values() if duration > 0]


def build_profiles(network, observations: list[dict], config: dict, cutoff, train_trip_ids: set[str]) -> list[dict]:
    rules = config["profile_rules"]
    validate_rules(rules)
    for row in observations:
        if row["trip_id"] not in train_trip_ids or row["estimated_exit_utc"] >= cutoff:
            raise ValueError("Data leakage: profile input includes non-training trip/time")
        if row["graph_version"] != network.graph_version:
            raise ValueError("Graph version mismatch in edge observations")
    valid = [row for row in observations if row["quality_flag"] == "accepted_inferred"]
    edge_rows, bucket_rows, night_rows = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in valid:
        edge_rows[row["edge_id"]].append(row)
        bucket_rows[(row["edge_id"], row["day_group"], row["time_bucket"])].append(row)
        if row["time_bucket"] == "00-06":
            night_rows[network.edges[row["edge_id"]].highway].append(row)
    boundaries = config["time"]["bucket_boundaries_hour"]
    result = []
    for edge in network.edges.values():
        all_rows = edge_rows[edge.edge_id]
        speeds = trip_speeds(all_rows)
        static = median(speeds) if speeds and adequate(all_rows, rules) else None
        nighttime = night_rows[edge.highway]
        if adequate(all_rows, rules):
            reference, source = quantile(speeds, 0.85), "edge_p85"
        elif adequate(nighttime, rules):
            reference, source = quantile(trip_speeds(nighttime), 0.85), "class_night_p85"
        else:
            reference = parse_maxspeed(edge.maxspeed_raw)
            source = "maxspeed_weak_proxy" if reference else None
        for group in ("weekday", "weekend"):
            for start, end in zip(boundaries, boundaries[1:]):
                bucket = f"{start:02d}-{end:02d}"
                rows = bucket_rows[(edge.edge_id, group, bucket)]
                bucket_speeds = trip_speeds(rows)
                speed = median(bucket_speeds) if bucket_speeds else None
                status, confidence, slowdown = "unknown", "insufficient", None
                if speed is not None and reference is not None and reference > 0 and adequate(rows, rules):
                    ratio = speed / reference
                    status = "high_slowdown" if ratio < rules["high_slowdown_ratio_threshold"] else "slow" if ratio < rules["slow_ratio_threshold"] else "normal"
                    confidence = "weak_reference" if source == "maxspeed_weak_proxy" else "supported_uncalibrated"
                    slowdown = max(0.0, 1 - ratio)
                result.append({"edge_id": edge.edge_id, "day_group": group, "time_bucket": bucket,
                    "median_speed_kmh": speed, "reference_speed_kmh": reference, "reference_source": source,
                    "static_speed_kmh": static, "slowdown_ratio": slowdown, **support(rows),
                    "confidence": confidence, "status": status, "graph_version": network.graph_version,
                    "train_cutoff": cutoff})
    return result


def threshold_sensitivity(network, observations, config: dict, cutoff, train_ids: set[str]) -> list[dict]:
    import copy
    result = []
    for minimum in sorted({2, 3, 5, 10, config["profile_rules"]["min_distinct_trips"]}):
        for slow_ratio in sorted({0.6, 0.7, 0.8, config["profile_rules"]["slow_ratio_threshold"]}):
            candidate = copy.deepcopy(config)
            candidate["profile_rules"].update(min_distinct_trips=minimum, slow_ratio_threshold=slow_ratio)
            if slow_ratio <= candidate["profile_rules"]["high_slowdown_ratio_threshold"]:
                continue
            profiles = build_profiles(network, observations, candidate, cutoff, train_ids)
            known = sum(row["status"] != "unknown" for row in profiles)
            result.append({"min_distinct_trips": minimum, "slow_ratio_threshold": slow_ratio,
                           "edge_buckets": len(profiles), "known_edge_buckets": known,
                           "known_fraction": known / len(profiles),
                           "slow_edge_buckets": sum(row["status"] in {"slow", "high_slowdown"} for row in profiles)})
    return result
