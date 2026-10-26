"""Small Parquet checkpoints with explicit Arrow types for S01."""

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .contracts import load_contracts
from .preprocess import Trip, iter_points


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def gps_schema() -> pa.Schema:
    """Translate the versioned GPS logical contract into an explicit Arrow schema."""
    catalog = load_contracts()
    types = {"string": pa.string(), "int64": pa.int64(), "float64": pa.float64(),
             "timestamp[us,UTC]": pa.timestamp("us", tz="UTC"),
             "timestamp[us,Europe/Lisbon]": pa.timestamp("us", tz="Europe/Lisbon")}
    fields = [pa.field(name, types[spec["type"]], nullable=spec["nullable"])
              for name, spec in catalog["tables"]["gps_points"]["fields"].items()]
    return pa.schema(fields, metadata={b"schema_version": catalog["schema_version"].encode(),
                                      b"crs": b"EPSG:4326", b"coordinate_order": b"lon,lat"})


def write_point_partitions(root: Path, trips: list[Trip], config: dict) -> dict:
    """Flush at most points_per_partition records at once, preserving point index and tz."""
    root.mkdir(parents=True, exist_ok=True)
    rows = []
    total = 0
    partition = 0
    for trip in trips:
        for point in iter_points(trip, config):
            rows.append(point)
            if len(rows) == config["s01"]["points_per_partition"]:
                pq.write_table(pa.Table.from_pylist(rows, schema=gps_schema()), root / f"part-{partition:05d}.parquet", compression="zstd")
                total += len(rows)
                rows = []
                partition += 1
    if rows:
        pq.write_table(pa.Table.from_pylist(rows, schema=gps_schema()), root / f"part-{partition:05d}.parquet", compression="zstd")
        total += len(rows)
        partition += 1
    return {"rows": total, "partitions": partition}


def write_trips(path: Path, records: list[dict]) -> None:
    """Persist the split manifest's trip-level table with raw elapsed-time semantics."""
    schema = pa.schema([
        pa.field("trip_id", pa.string(), False), pa.field("taxi_id", pa.int64(), False),
        pa.field("source_row", pa.int64(), False), pa.field("split", pa.string(), False),
        pa.field("start_utc", pa.timestamp("us", tz="UTC"), False),
        pa.field("end_utc", pa.timestamp("us", tz="UTC"), False),
        pa.field("point_count", pa.int64(), False),
        pa.field("raw_elapsed_s", pa.float64(), False),
        pa.field("start_day_group", pa.string(), False), pa.field("start_time_bucket", pa.string(), False),
    ], metadata={b"schema_version": load_contracts()["schema_version"].encode(), b"duration_semantics": b"15*(N-1), complete trips only"})
    pq.write_table(pa.Table.from_pylist(records, schema=schema), path, compression="zstd")


def verify_checkpoint(root: Path) -> dict:
    """Reuse a completed run only if every recorded artifact's SHA-256 still matches."""
    manifest = json.loads((root / "run_metadata.json").read_text(encoding="utf-8"))
    for relative, checksum in manifest["outputs_sha256"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or sha256_file(path) != checksum:
            raise ValueError(f"Checkpoint is incomplete or corrupt: {relative}; use a new output root")
    return manifest
