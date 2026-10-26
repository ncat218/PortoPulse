"""Versioned directed road graphs in WGS84 with metric geometry for calculations."""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import CRS, Transformer
from shapely import wkt, transform as project_geometry, to_wkt
from shapely.geometry import LineString, box

from .storage import sha256_file
from .contracts import load_contracts


@dataclass(frozen=True)
class RoadEdge:
    edge_id: str
    u: int
    v: int
    key: int
    geometry: LineString
    metric_geometry: LineString
    length_m: float
    highway: str
    maxspeed_raw: str


class RoadNetwork:
    def __init__(self, graph: nx.MultiDiGraph, metric_crs: str = "EPSG:32629", provenance: dict | None = None):
        if not isinstance(graph, nx.MultiDiGraph) or not graph.is_directed():
            raise ValueError("Road network must be a directed MultiDiGraph")
        if graph.number_of_edges() == 0:
            raise ValueError("Road network has no edges")
        crs = CRS.from_user_input(metric_crs)
        if not crs.is_projected or any(axis.unit_name.lower() != "metre" for axis in crs.axis_info):
            raise ValueError("Metric CRS must be projected with metre units")
        if CRS.from_user_input(graph.graph.get("crs", "EPSG:4326")) != CRS.from_epsg(4326):
            raise ValueError("Input graph must be EPSG:4326")
        self.metric_crs = crs.to_string()
        self.to_metric = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        self.to_wgs84 = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        self.provenance = provenance or {"kind": "UNVERIFIED"}
        self.graph = nx.MultiDiGraph(crs="EPSG:4326")
        for node, attributes in sorted(graph.nodes(data=True)):
            if type(node) is not int:
                raise ValueError("OSM node IDs must be integers")
            x, y = float(attributes["x"]), float(attributes["y"])
            if not (math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90):
                raise ValueError("Invalid WGS84 node coordinate")
            self.graph.add_node(node, x=x, y=y)
        self.edges: dict[str, RoadEdge] = {}
        for u, v, key, attributes in sorted(graph.edges(keys=True, data=True), key=lambda row: row[:3]):
            if type(key) is not int:
                raise ValueError("Parallel-edge key must be integer")
            geometry = attributes.get("geometry")
            if isinstance(geometry, str):
                geometry = wkt.loads(geometry)
            if geometry is None:
                geometry = LineString([(self.graph.nodes[n]["x"], self.graph.nodes[n]["y"]) for n in (u, v)])
            if not isinstance(geometry, LineString) or geometry.is_empty:
                raise ValueError("Road geometry must be a nonempty LineString")
            metric = project_geometry(geometry, self.to_metric.transform, interleaved=False)
            ux, uy = self.to_metric.transform(self.graph.nodes[u]["x"], self.graph.nodes[u]["y"])
            if math.dist(metric.coords[-1], (ux, uy)) < math.dist(metric.coords[0], (ux, uy)):
                geometry = LineString(list(geometry.coords)[::-1])
                metric = LineString(list(metric.coords)[::-1])
            if not math.isfinite(metric.length) or metric.length <= 0:
                raise ValueError("Road edge must have positive finite metric length")
            vx, vy = self.to_metric.transform(self.graph.nodes[v]["x"], self.graph.nodes[v]["y"])
            if math.dist(metric.coords[0], (ux, uy)) > 0.5 or math.dist(metric.coords[-1], (vx, vy)) > 0.5:
                raise ValueError("Directed geometry endpoints do not align with graph nodes")
            highway = attributes.get("highway", "unknown")
            highway = sorted(str(value) for value in highway)[0] if isinstance(highway, list) else str(highway)
            maximum = attributes.get("maxspeed_raw", attributes.get("maxspeed", ""))
            maximum = json.dumps(maximum) if isinstance(maximum, list) else str(maximum)
            edge_id = f"{u}:{v}:{key}"
            edge = RoadEdge(edge_id, u, v, key, geometry, metric, metric.length, highway, maximum)
            self.edges[edge_id] = edge
            self.graph.add_edge(u, v, key=key, edge_id=edge_id, length_m=edge.length_m,
                                highway=highway, maxspeed_raw=maximum, geometry=to_wkt(geometry, rounding_precision=-1))
        # Projected WKB can differ by nanometres between PROJ/platform versions.
        # Identity uses immutable WGS84 source geometry and the declared metric CRS.
        signature = {"identity_method": "wgs84_content_v2", "metric_crs": self.metric_crs,
                     "nodes": [(n, a["x"], a["y"]) for n, a in self.graph.nodes(data=True)],
                     "edges": [(e.edge_id, e.geometry.wkb_hex, e.highway, e.maxspeed_raw) for e in self.edges.values()]}
        self.portable_content_sha256 = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
        self.graph_version = self.portable_content_sha256
        self.graph_identity_method = "wgs84_content_v2"

    def save(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        nx.write_graphml(self.graph, folder / "road_graph.graphml")
        records = [{"edge_id": e.edge_id, "u": e.u, "v": e.v, "key": e.key,
                    "length_m": e.length_m, "highway": e.highway, "maxspeed_raw": e.maxspeed_raw or None,
                    "geometry": e.geometry.wkb, "graph_version": self.graph_version} for e in self.edges.values()]
        catalog = load_contracts()
        types = {"string": pa.string(), "int64": pa.int64(), "float64": pa.float64(), "binary:wkb": pa.binary()}
        schema = pa.schema([pa.field(name, types[spec["type"]], spec["nullable"])
                            for name, spec in catalog["tables"]["road_edges"]["fields"].items()])
        table = pa.Table.from_pylist(records, schema=schema)
        table = table.replace_schema_metadata({b"crs": b"EPSG:4326", b"geometry_encoding": b"WKB",
                                               b"graph_version": self.graph_version.encode(), b"schema_version": catalog["schema_version"].encode()})
        pq.write_table(table, folder / "road_edges.parquet", compression="zstd")
        metadata = {"graph_version": self.graph_version, "metric_crs": self.metric_crs,
                    "graph_identity_method": self.graph_identity_method,
                    "portable_content_sha256": self.portable_content_sha256,
                    "source_crs": "EPSG:4326", "provenance": self.provenance,
                    "nodes": self.graph.number_of_nodes(), "edges": len(self.edges),
                    "weak_components": nx.number_weakly_connected_components(self.graph),
                    "strong_components": nx.number_strongly_connected_components(self.graph),
                    "sha256": {name: sha256_file(folder / name) for name in ("road_graph.graphml", "road_edges.parquet")}}
        (folder / "graph_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, folder: Path):
        metadata = json.loads((folder / "graph_metadata.json").read_text(encoding="utf-8"))
        if set(metadata["sha256"]) != {"road_graph.graphml", "road_edges.parquet"}:
            raise ValueError("Graph metadata must checksum GraphML and edge Parquet")
        for name, checksum in metadata["sha256"].items():
            if sha256_file(folder / name) != checksum:
                raise ValueError(f"Corrupt graph artifact: {name}")
        graph = nx.read_graphml(folder / "road_graph.graphml", node_type=int, edge_key_type=int, force_multigraph=True)
        result = cls(graph, metadata["metric_crs"], metadata["provenance"])
        table = pq.ParquetFile(folder / "road_edges.parquet").read()
        rows = table.to_pylist()
        if (len(rows) != len(result.edges) or len({row["edge_id"] for row in rows}) != len(rows)
                or metadata["nodes"] != result.graph.number_of_nodes() or metadata["edges"] != len(rows)):
            raise ValueError("GraphML/Parquet counts or unique edge IDs differ")
        if table.schema.metadata.get(b"graph_version") != metadata["graph_version"].encode():
            raise ValueError("Graph version differs between metadata and Parquet")
        maximum_delta = 0.0
        for row in rows:
            edge = result.edges.get(row["edge_id"])
            if (edge is None or (edge.u, edge.v, edge.key, edge.highway, edge.maxspeed_raw or None)
                    != (row["u"], row["v"], row["key"], row["highway"], row["maxspeed_raw"])
                    or edge.geometry.wkb != row["geometry"] or row["graph_version"] != metadata["graph_version"]):
                raise ValueError("GraphML/Parquet edge identity or WGS84 geometry differs")
            original = graph[edge.u][edge.v][edge.key]
            if original.get("edge_id") != edge.edge_id or float(original["length_m"]) != row["length_m"]:
                raise ValueError("GraphML/Parquet edge attributes differ")
            delta = abs(edge.length_m - row["length_m"])
            if not math.isfinite(row["length_m"]) or delta > max(1e-6, row["length_m"] * 1e-9):
                raise ValueError("Projected edge length differs beyond numerical tolerance")
            maximum_delta = max(maximum_delta, delta)
        portable = metadata.get("portable_content_sha256")
        if portable is not None and portable != result.portable_content_sha256:
            raise ValueError("Portable graph content hash differs after round trip")
        method = metadata.get("graph_identity_method", "legacy_metric_wkb_v1")
        if method not in {"wgs84_content_v2", "legacy_metric_wkb_v1"}:
            raise ValueError("Unknown graph identity method")
        if method == "wgs84_content_v2" and metadata["graph_version"] != result.portable_content_sha256:
            raise ValueError("Graph version differs after GraphML round trip")
        # Preserve existing snapshot IDs so their GPS screening/joins remain valid.
        # Legacy loads require full checksums and exact source-geometry parity above.
        result.graph_version = metadata["graph_version"]
        result.graph_identity_method = method
        result.load_verification = {"source_geometry_parity": True, "checksums_verified": True,
                                    "maximum_projection_length_delta_m": maximum_delta,
                                    "graph_identity_method": method,
                                    "portable_content_sha256": result.portable_content_sha256}
        return result


