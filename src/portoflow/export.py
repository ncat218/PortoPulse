"""Precomputed serving artifacts. The web app never calls preprocessing or matching."""

import json
from datetime import date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import mapping
from .contracts import load_contracts


COLORS = {"normal": "#2ca25f", "slow": "#fec44f", "high_slowdown": "#de2d26", "unknown": "#969696"}


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Not JSON serializable: {type(value)}")


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, default=json_default, allow_nan=False), encoding="utf-8")


def write_profiles(path: Path, profiles: list[dict]):
    fields = [pa.field("edge_id", pa.string(), False), pa.field("day_group", pa.string(), False), pa.field("time_bucket", pa.string(), False)]
    fields += [pa.field(name, pa.float64()) for name in ("median_speed_kmh", "reference_speed_kmh", "static_speed_kmh", "slowdown_ratio")]
    fields += [pa.field("reference_source", pa.string())]
    fields += [pa.field(name, pa.int64(), False) for name in ("distinct_taxis", "distinct_trips", "distinct_dates")]
    fields += [pa.field(name, pa.string(), False) for name in ("confidence", "status", "graph_version")]
    fields += [pa.field("train_cutoff", pa.timestamp("us", tz="UTC"), False)]
    schema = pa.schema(fields, metadata={b"schema_version": load_contracts()["schema_version"].encode()})
    pq.write_table(pa.Table.from_pylist(profiles, schema=schema), path, compression="zstd")


def serve_geojson(network, profiles: list[dict]) -> dict:
    features = []
    for row in profiles:
        if row["graph_version"] != network.graph_version:
            raise ValueError("Graph version mismatch during export")
        properties = {name: value for name, value in row.items() if name != "train_cutoff"}
        properties.update(color=COLORS[row["status"]], highway=network.edges[row["edge_id"]].highway)
        features.append({"type": "Feature", "geometry": mapping(network.edges[row["edge_id"]].geometry), "properties": properties})
    return {"type": "FeatureCollection", "features": features}
