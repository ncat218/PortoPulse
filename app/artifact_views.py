"""Build app views from the compact tables already present in a serving export."""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pyarrow.parquet as pq
from shapely import from_wkb
from shapely.geometry import mapping

from portoflow.export import COLORS
from portoflow.storage import verify_checkpoint
from road_display import separate_direction_geometries
from ui_logic import MAP_PROPERTIES, STATUS_LABELS


def read_snapshot(directory):
    metadata = verify_checkpoint(directory)
    graph_version = metadata["graph_version"]
    table = pq.ParquetFile(directory / "congestion_profiles.parquet").read()
    # Convert the shared cutoff only once per unique timestamp.
    cutoffs = table.column("train_cutoff").cast("int64").to_pylist()
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    instants = {value: epoch + timedelta(microseconds=value) for value in set(cutoffs)}
    profiles = table.drop(["train_cutoff"]).to_pylist()

    edges = pq.ParquetFile(directory / "graph/road_edges.parquet").read(
        columns=["edge_id", "geometry", "graph_version"]
    )
    edge_ids = edges["edge_id"].to_pylist()
    if len(set(edge_ids)) != len(edge_ids) or set(edges["graph_version"].to_pylist()) != {graph_version}:
        raise ValueError("Danh tính cạnh hoặc phiên bản đồ thị không khớp.")
    geometries = dict(zip(edge_ids, map(mapping, from_wkb(edges["geometry"].to_pylist()))))
    display_geometries = separate_direction_geometries(
        {"geometry": geometry, "properties": {"edge_id": edge_id}}
        for edge_id, geometry in geometries.items()
    )

    buckets = defaultdict(list)
    for row, value in zip(profiles, cutoffs):
        if row["graph_version"] != graph_version or row["edge_id"] not in geometries:
            raise ValueError("Cạnh trong profile không khớp đồ thị.")
        row["train_cutoff"] = instants[value]
        buckets[row["day_group"], row["time_bucket"]].append(row)
    config = json.loads((directory / "pipeline_config.json").read_text(encoding="utf-8"))
    return metadata, profiles, dict(buckets), config, geometries, display_geometries


def build_bucket_view(rows, geometries, display_geometries):
    features, map_features = [], []
    for row in rows:
        edge_id, status = row["edge_id"], row["status"]
        properties = {**row, "color": COLORS[status], "status_label": STATUS_LABELS[status]}
        feature = {
            "type": "Feature", "geometry": geometries[edge_id],
            "properties": {name: properties[name] for name in MAP_PROPERTIES},
        }
        features.append(feature)
        map_features.append({**feature, "geometry": display_geometries[edge_id]})
    return features, map_features
