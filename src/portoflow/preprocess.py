"""S01 trajectory validation, deterministic sampling, and temporal trip split."""

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import bucket_for_local_time
from .data import RAW_COLUMNS, read_batches


class TripRejected(ValueError):
    """A recoverable row-level QC rejection with a stable reason code."""


@dataclass(frozen=True)
class Trip:
    trip_id: str
    taxi_id: int
    start_utc: datetime
    coordinates: tuple[tuple[float, float], ...]
    source_row: int

    @property
    def end_utc(self) -> datetime:
        return self.start_utc + timedelta(seconds=15 * (len(self.coordinates) - 1))


def _integer(value: str, *, nullable: bool = False) -> int | None:
    if nullable and value == "":
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise TripRejected("invalid_integer") from None
    if result < 0:
        raise TripRejected("negative_integer")
    return result


def parse_trip(row: dict, source_row: int, config: dict) -> Trip:
    """Validate a whole trajectory; preserve original point indices and stationary repeats."""
    if set(row) != set(RAW_COLUMNS) or any(value is None for value in row.values()):
        raise TripRejected("invalid_row_width")
    trip_id = row["TRIP_ID"].strip()
    if not trip_id:
        raise TripRejected("empty_trip_id")
    if row["CALL_TYPE"] not in {"A", "B", "C"} or row["DAYTYPE"] not in {"A", "B", "C"}:
        raise TripRejected("invalid_category")
    _integer(row["ORIGIN_CALL"], nullable=True)
    _integer(row["ORIGIN_STAND"], nullable=True)
    taxi_id = _integer(row["TAXI_ID"])
    if taxi_id == 0 or taxi_id > 2**63 - 1:
        raise TripRejected("invalid_taxi_id")
    timestamp = _integer(row["TIMESTAMP"])
    try:
        start = datetime.fromtimestamp(timestamp, timezone.utc)
        if start.year > 2100:
            raise ValueError("future timestamp")
    except (ValueError, OverflowError, OSError):
        raise TripRejected("invalid_timestamp") from None
    missing = row["MISSING_DATA"].lower()
    if missing not in {"true", "false"}:
        raise TripRejected("invalid_missing_data_flag")
    if missing == "true":
        # Missing positions have unknown indices/times; never manufacture 15-second spacing.
        raise TripRejected("missing_gps_data")
    try:
        coordinates = json.loads(row["POLYLINE"])
    except (ValueError, TypeError):
        raise TripRejected("malformed_polyline") from None
    if not isinstance(coordinates, list):
        raise TripRejected("invalid_polyline_shape")
    if len(coordinates) < 2:
        raise TripRejected("short_trajectory")
    if len(coordinates) > config["s01"]["max_points_per_trip"]:
        raise TripRejected("point_budget_exceeded")
    west, south, east, north = config["s01"]["qc_bbox_lonlat"]
    points = []
    for pair in coordinates:
        if not isinstance(pair, list) or len(pair) != 2:
            raise TripRejected("invalid_coordinate_shape")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in pair):
            raise TripRejected("nonfinite_or_nonnumeric_coordinate")
        lon, lat = pair
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise TripRejected("invalid_wgs84_coordinate")
        if not (west <= lon <= east and south <= lat <= north):
            if west <= lat <= east and south <= lon <= north:
                raise TripRejected("suspected_lon_lat_swap")
            raise TripRejected("outside_qc_bbox")
        points.append((float(lon), float(lat)))
    return Trip(trip_id, taxi_id, start, tuple(points), source_row)


def scan_source(source: Path, config: dict, max_rows: int, batch_size: int) -> dict:
    """QC a bounded prefix and quarantine every accepted occurrence of duplicate trip IDs."""
    accepted, rejected = [], []
    identifiers = Counter()
    checksum = hashlib.sha256()
    scanned = 0
    input_schema = {}
    for batch in read_batches(source, max_rows=max_rows, batch_size=batch_size,
                              member=config["dataset"]["expected_csv_member"], schema_info=input_schema):
        for number, row in batch:
            scanned += 1
            checksum.update(json.dumps([number, row], ensure_ascii=False).encode("utf-8"))
            checksum.update(b"\n")
            identifier = row.get("TRIP_ID", "") or ""
            identifiers[identifier.strip()] += 1
            try:
                accepted.append(parse_trip(row, number, config))
            except TripRejected as exc:
                rejected.append({"source_row": number, "trip_id": identifier, "reason": str(exc)})
    unique = []
    for trip in accepted:
        if identifiers[trip.trip_id] > 1:
            rejected.append({"source_row": trip.source_row, "trip_id": trip.trip_id, "reason": "duplicate_trip_id"})
        else:
            unique.append(trip)
    return {"trips": unique, "rejected": sorted(rejected, key=lambda r: r["source_row"]),
            "scanned_rows": scanned, "prefix_records_sha256": checksum.hexdigest(),
            "input_schema": input_schema,
            "scan_limit_reached": scanned == max_rows}


def resolve_cutoff(trips: list[Trip], cutoff: str | None) -> tuple[datetime, str]:
    """Use explicit UTC cutoff, or a recorded median-start cutoff for prefix smoke testing."""
    if cutoff is not None:
        try:
            parsed = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Cutoff must be an aware UTC ISO timestamp") from None
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("Cutoff must be an aware UTC ISO timestamp")
        return parsed.astimezone(timezone.utc), "explicit_utc"
    times = sorted({trip.start_utc for trip in trips})
    if len(times) < 2:
        raise ValueError("Need at least two unique trip start times or an explicit UTC cutoff")
    middle = len(times) // 2
    return times[middle - 1] + (times[middle] - times[middle - 1]) / 2, "prefix_median_start_smoke_only"


def assign_split(trip: Trip, cutoff: datetime) -> str:
    """Purge trips touching/crossing the boundary so all training points precede holdout."""
    if trip.end_utc < cutoff:
        return "train"
    if trip.start_utc >= cutoff:
        return "holdout"
    return "boundary_purged"


def stratified_sample(trips: list[Trip], cutoff: datetime, config: dict) -> tuple[list[tuple[str, Trip]], list[dict]]:
    """Select up to k trips per split x local-start bucket by seeded hash rank."""
    strata = defaultdict(list)
    purged = []
    for trip in trips:
        split = assign_split(trip, cutoff)
        if split == "boundary_purged":
            purged.append({"source_row": trip.source_row, "trip_id": trip.trip_id, "reason": "split_boundary"})
            continue
        group, bucket = bucket_for_local_time(trip.start_utc.astimezone(ZoneInfo("Europe/Lisbon")), config)
        priority = hashlib.sha256(f"{config['random_seed']}:{trip.trip_id}".encode()).hexdigest()
        strata[(split, group, bucket)].append((priority, trip.trip_id, trip))
    selected = []
    for key in sorted(strata):
        for _, _, trip in sorted(strata[key])[:config["s01"]["sample_per_stratum"]]:
            selected.append((key[0], trip))
    selected.sort(key=lambda item: (item[0], item[1].start_utc, item[1].trip_id))
    return selected, purged


def iter_points(trip: Trip, config: dict):
    """Yield points with nominal UTC spacing and aware Lisbon passage times."""
    zone = ZoneInfo(config["time"]["analysis_timezone"])
    for index, (lon, lat) in enumerate(trip.coordinates):
        utc = trip.start_utc + timedelta(seconds=15 * index)
        yield {"trip_id": trip.trip_id, "taxi_id": trip.taxi_id, "point_idx": index,
               "lon": lon, "lat": lat, "event_time_utc": utc,
               "event_time_local": utc.astimezone(zone), "quality_flag": "nominal_15s_complete_trip"}
