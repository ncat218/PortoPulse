"""Explicit matcher adapters; no automatic fallback or inferred timing as ground truth."""

import math
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

import networkx as nx
from shapely.geometry import Point
from shapely.strtree import STRtree


@dataclass(frozen=True)
class Candidate:
    edge_id: str
    offset_m: float
    residual_m: float


def apportion_gap(network, pieces: list[tuple], trip, gap_index: int, start, end) -> list[dict]:
    """Distribute an observed GPS interval by traveled distance; conserve its duration."""
    duration = (end - start).total_seconds()
    if duration <= 0:
        raise ValueError("GPS timestamps must increase")
    total = sum(b - a for _, a, b in pieces)
    if any(b < a for _, a, b in pieces):
        raise ValueError("Directed traversal offsets must not go backwards")
    if not pieces:
        raise ValueError("Gap contains no road path")
    rows = []
    cumulative = 0.0
    for i, (edge_id, a, b) in enumerate(pieces):
        edge = network.edges[edge_id]
        if a < -1e-6 or b > edge.length_m + 1e-6:
            raise ValueError("Traversal offset outside edge geometry")
        entry = start + timedelta(seconds=duration * cumulative / total) if total > 0 else start
        cumulative += b - a
        if i == len(pieces) - 1:
            exit_time = end
        elif total > 0:
            exit_time = start + timedelta(seconds=duration * cumulative / total)
        else:
            exit_time = start  # A zero path has elapsed time but no distributed movement.
        if exit_time < entry:
            raise ValueError("Nonmonotonic estimated edge timestamps")
        rows.append({"trip_id": trip.trip_id, "taxi_id": trip.taxi_id, "edge_id": edge_id,
                     "gap_index": gap_index, "start_offset_m": a, "end_offset_m": b,
                     "traveled_distance_m": b - a, "estimated_entry_utc": entry,
                     "estimated_exit_utc": exit_time, "graph_version": network.graph_version,
                     "time_allocation_method": "distance_proportional_uniform_gps_gap"})
    error = abs(sum((r["estimated_exit_utc"] - r["estimated_entry_utc"]).total_seconds() for r in rows) - duration)
    if error > 1e-5:
        raise ValueError("Inferred durations do not conserve observed GPS gap duration")
    return rows


class HMMMatcher:
    """Small-sample HMM: Gaussian emissions, directed-distance transitions, Viterbi decoding.

    This is an explicit transparent alternative for development, not a validated Porto matcher.
    """
    method = "hmm_viterbi_v1"

    def __init__(self, network, settings: dict):
        self.network, self.settings = network, settings
        self.edge_list = list(network.edges.values())
        self.tree = STRtree([edge.metric_geometry for edge in self.edge_list])

    def candidates(self, x: float, y: float) -> list[Candidate]:
        point = Point(x, y)
        radius = self.settings["candidate_radius_m"]
        candidates = []
        for index in self.tree.query(point.buffer(radius)):
            edge = self.edge_list[int(index)]
            residual = edge.metric_geometry.distance(point)
            if residual <= radius:
                candidates.append(Candidate(edge.edge_id, edge.metric_geometry.project(point), residual))
        return sorted(candidates, key=lambda c: (c.residual_m, c.edge_id))[:self.settings["max_candidates"]]

    @lru_cache(maxsize=10000)
    def middle_path(self, source: int, target: int):
        try:
            nodes = nx.shortest_path(self.network.graph, source, target, weight="length_m")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        result = []
        for u, v in zip(nodes, nodes[1:]):
            edge = min(self.network.graph[u][v].values(), key=lambda a: (a["length_m"], a["edge_id"]))
            result.append(edge["edge_id"])
        return tuple(result)

    def transition_path(self, a: Candidate, b: Candidate):
        first, last = self.network.edges[a.edge_id], self.network.edges[b.edge_id]
        if a.edge_id == b.edge_id and b.offset_m >= a.offset_m:
            return [(a.edge_id, a.offset_m, b.offset_m)]
        middle = self.middle_path(first.v, last.u)
        if middle is None:
            return None
        pieces = [(a.edge_id, a.offset_m, first.length_m)]
        pieces.extend((eid, 0.0, self.network.edges[eid].length_m) for eid in middle)
        pieces.append((b.edge_id, 0.0, b.offset_m))
        return [piece for piece in pieces if piece[2] - piece[1] > 1e-8]

    def match(self, trip) -> dict:
        xy = [self.network.to_metric.transform(lon, lat) for lon, lat in trip.coordinates]
        layers = [self.candidates(x, y) for x, y in xy]
        if any(not candidates for candidates in layers):
            return {"status": "failed", "reason": "no_candidates", "traversals": [], "residuals_m": [], "method": self.method}
        sigma, beta = self.settings["gps_sigma_m"], self.settings["transition_beta_m"]
        scores = [-0.5 * (candidate.residual_m / sigma) ** 2 for candidate in layers[0]]
        parents = []
        for i in range(1, len(layers)):
            next_scores, back = [], []
            observed_distance = math.dist(xy[i - 1], xy[i])
            for candidate in layers[i]:
                options = []
                for j, previous in enumerate(layers[i - 1]):
                    path = self.transition_path(previous, candidate)
                    if not path:
                        options.append(-math.inf)
                        continue
                    length = sum(end - start for _, start, end in path)
                    if length / 15 * 3.6 > self.settings["max_gap_speed_kmh"]:
                        options.append(-math.inf)
                        continue
                    options.append(scores[j] - abs(length - observed_distance) / beta)
                best = max(range(len(options)), key=lambda j: options[j])
                next_scores.append(options[best] - 0.5 * (candidate.residual_m / sigma) ** 2)
                back.append(best)
            if all(score == -math.inf for score in next_scores):
                return {"status": "failed", "reason": "directed_path_disconnected", "traversals": [], "residuals_m": [], "method": self.method}
            parents.append(back)
            scores = next_scores
        index = max(range(len(scores)), key=lambda j: scores[j])
        chosen = [index]
        for back in reversed(parents):
            index = back[index]
            chosen.append(index)
        chosen.reverse()
        candidates = [layer[j] for layer, j in zip(layers, chosen)]
        rows = []
        for i, (a, b) in enumerate(zip(candidates, candidates[1:])):
            start = trip.start_utc + timedelta(seconds=15 * i)
            rows.extend(apportion_gap(self.network, self.transition_path(a, b), trip, i, start, start + timedelta(seconds=15)))
        residuals = [candidate.residual_m for candidate in candidates]
        status = "success" if sorted(residuals)[len(residuals) // 2] <= self.settings["max_median_residual_m"] else "failed_quality"
        return {"status": status, "reason": "ok" if status == "success" else "large_residual",
                "traversals": rows, "residuals_m": residuals, "method": self.method}


class FastMMMatcher:
    """Fastmm binding adapter with explicit integer-ID map and independent time allocation.

    Native interpolated timestamps are audited, not treated as observations. API mismatch fails.
    """
    def __init__(self, network, settings: dict, cache_dir: Path):
        edge_budget = settings.get("max_graph_edges", 5000)
        if type(edge_budget) is not int or not 1 <= edge_budget <= 6000:
            raise ValueError("Fastmm edge budget must be explicit and within 1..6000")
        if len(network.edges) > edge_budget:
            raise ValueError(f"Fastmm graph has {len(network.edges)} edges; current authorized budget is {edge_budget}")
        import fastmm
        if version("fastmm") != "0.3.2":
            raise ValueError("Adapter is verified for fastmm 0.3.2 only; run a new API probe before changing version")
        self.module, self.network, self.settings = fastmm, network, settings
        self.method = f"fastmm:{version('fastmm')}"
        # The 0.3.2 binding borrows Network without a pybind11 keep_alive policy.
        # A local-only owner is destroyed at __init__ return and match() can abort.
        self.native_network = fastmm.Network()
        native = self.native_network
        self.numeric_to_edge = {i: eid for i, eid in enumerate(sorted(network.edges), 1)}
        for numeric, eid in self.numeric_to_edge.items():
            edge = network.edges[eid]
            native.add_edge(numeric, source=edge.u, target=edge.v, geom=list(edge.metric_geometry.coords))
        native.finalize()
        self.matcher = fastmm.FastMapMatch(native, fastmm.TransitionMode.SHORTEST,
            max_distance_between_candidates=settings["ubodt_distance_m"],
            cache_dir=cache_dir / network.graph_version)
        if not hasattr(fastmm.Trajectory, "from_xyt_tuples"):
            raise ValueError("Incompatible fastmm API: Trajectory.from_xyt_tuples missing; no automatic fallback")

    def match(self, trip) -> dict:
        xyt = [(*self.network.to_metric.transform(lon, lat), trip.start_utc.timestamp() + 15 * i)
               for i, (lon, lat) in enumerate(trip.coordinates)]
        result = self.matcher.match(self.module.Trajectory.from_xyt_tuples(xyt),
            max_candidates=self.settings["max_candidates"], candidate_search_radius=self.settings["candidate_radius_m"],
            gps_error=self.settings["gps_sigma_m"], reverse_tolerance=0.0)
        rows, covered, residuals, native_errors, path_errors = [], set(), {}, [], []
        native_segments = []
        native_subtrajectories = []
        zero_displacement = []
        for sub in result.subtrajectories:
            native_subtrajectories.append({"start_index": getattr(sub, "start_index", None),
                "end_index": getattr(sub, "end_index", None), "error_code": str(sub.error_code)})
            if sub.error_code != self.module.MatchErrorCode.SUCCESS:
                continue
            for segment in sub.segments:
                snapshot = native_segment_snapshot(segment)
                native_segments.append(snapshot)
                # Actual 0.3.2 wheels use zero-based indices, despite the .pyi text.
                i0, i1 = segment.p0.trajectory_index, segment.p1.trajectory_index
                if i1 != i0 + 1 or not (0 <= i0 < i1 < len(xyt)):
                    path_errors.append({"gap_index": i0, "reason": "nonadjacent_or_invalid_native_indices", "native_segment": snapshot})
                    continue  # Never bridge filtered GPS points or manufacture their timestamps.
                if any(candidate.t is None or abs(candidate.t - xyt[index][2]) > 1e-5
                       for candidate, index in ((segment.p0, i0), (segment.p1, i1))):
                    raise ValueError("Native candidate index/timestamp semantics changed")
                try:
                    pieces, native_duration = native_segment_pieces(segment, self.network, self.numeric_to_edge)
                except ValueError as exc:
                    path_errors.append({"gap_index": i0, "reason": str(exc), "native_segment": snapshot})
                    continue
                if not pieces:
                    path_errors.append({"gap_index": i0, "reason": "empty_native_path", "native_segment": snapshot})
                    continue
                path_distance = sum(b - a for _, a, b in pieces)
                if path_distance / 15 * 3.6 > self.settings["max_gap_speed_kmh"]:
                    path_errors.append({"gap_index": i0, "reason": "implausible_native_path_speed",
                                        "native_path_distance_m": path_distance, "native_inferred_speed_kmh": path_distance / 15 * 3.6,
                                        "native_segment": snapshot})
                    continue
                start = trip.start_utc + timedelta(seconds=15 * i0)
                allocated = apportion_gap(self.network, pieces, trip, i0, start, start + timedelta(seconds=15))
                rows.extend(allocated)
                covered.add(i0)
                if path_distance == 0.0:
                    # Native zero-length geometry has only the entry timestamp.
                    # Account observed elapsed time but do not claim native timing passed.
                    zero_displacement.append({"gap_index": i0, "native_elapsed_s": native_duration,
                                              "nominal_gps_elapsed_s": 15.0,
                                              "interpretation": "zero_matched_displacement_not_traffic_speed_evidence"})
                else:
                    native_errors.append(abs(native_duration - 15.0))
                for p in (segment.p0, segment.p1):
                    residuals[p.trajectory_index] = p.perpendicular_distance_to_matched_geometry
        status = "success" if len(covered) == len(xyt) - 1 else "partial" if covered else "failed"
        distances = list(residuals.values())
        if status == "success" and sorted(distances)[len(distances) // 2] > self.settings["max_median_residual_m"]:
            status = "failed_quality"
        return {"status": status, "reason": "ok" if status == "success" else "partial_or_unacceptable_match",
                "traversals": rows, "residuals_m": distances, "method": self.method,
                "native_path_errors": path_errors,
                "native_segments_diagnostic": native_segments,
                "native_subtrajectories_diagnostic": native_subtrajectories,
                "uncovered_gps_gap_indices": sorted(set(range(len(xyt)-1)) - covered),
                "zero_matched_displacement_gaps": zero_displacement,
                "native_time_conservation_max_error_s": max(native_errors, default=None)}


def native_segment_snapshot(segment) -> dict:
    """Record native evidence before QC; never treat rejected geometry as a traversal."""
    def fields(obj, names):
        values = {name: getattr(obj, name, None) for name in names}
        return {name: None if isinstance(value, float) and not math.isfinite(value) else value for name, value in values.items()}
    return {"p0": fields(segment.p0, ("trajectory_index", "x", "y", "t", "offset_from_start_of_edge")),
            "p1": fields(segment.p1, ("trajectory_index", "x", "y", "t", "offset_from_start_of_edge")),
            "edges": [{"edge_id": edge.edge_id, "reversed": edge.reversed, "point_count": len(edge.points),
                       "first_point": fields(edge.points[0], ("x", "y", "t", "edge_offset")) if edge.points else None,
                       "last_point": fields(edge.points[-1], ("x", "y", "t", "edge_offset")) if edge.points else None}
                      for edge in segment.edges]}


def native_segment_pieces(segment, network, numeric_to_edge: dict) -> tuple[list[tuple], float]:
    """Convert clipped native-edge offsets to absolute source-edge positions.

    Actual 0.3.2 MatchPoint offsets start at zero on each clipped geometry.
    MatchCandidate offsets reference the complete source edge. Verify XY endpoints,
    clipped length and directed continuity instead of trusting the stub descriptions.
    """
    pieces, duration = [], 0.0
    edges = segment.edges
    for index, native_edge in enumerate(edges):
        if native_edge.reversed:
            raise ValueError("reversed_native_edge")
        edge_id = numeric_to_edge[native_edge.edge_id]
        edge = network.edges[edge_id]
        a = segment.p0.offset_from_start_of_edge if index == 0 else 0.0
        b = segment.p1.offset_from_start_of_edge if index == len(edges) - 1 else edge.length_m
        # A clipped boundary or zero-displacement interval can have one point.
        # Only accept an exactly zero source span; never infer missing movement.
        if not native_edge.points or (len(native_edge.points) == 1 and a != b):
            raise ValueError("incomplete_native_edge")
        first, last = native_edge.points[0], native_edge.points[-1]
        if a < -1e-6 or b > edge.length_m + 1e-6 or b < a:
            raise ValueError("invalid_absolute_native_offsets")
        if (edge.metric_geometry.interpolate(a).distance(Point(first.x, first.y)) > 1e-5
                or edge.metric_geometry.interpolate(b).distance(Point(last.x, last.y)) > 1e-5
                or abs((last.edge_offset - first.edge_offset) - (b - a)) > 1e-5):
            raise ValueError("native_clipped_geometry_semantics_changed")
        if pieces and network.edges[pieces[-1][0]].v != edge.u:
            raise ValueError("native_directed_path_disconnected")
        pieces.append((edge_id, max(0.0, a), min(edge.length_m, b)))
        if first.t is not None and last.t is not None:
            duration += last.t - first.t
    return pieces, duration


def create_matcher(method: str, network, settings: dict, cache_dir: Path):
    if method == "hmm":
        return HMMMatcher(network, settings)
    if method == "fastmm":
        return FastMMMatcher(network, settings, cache_dir)
    raise ValueError("Matcher must be fastmm or explicitly selected hmm; no silent fallback")


def match_schema():
    import pyarrow as pa
    from .contracts import load_contracts
    fields = [("trip_id", pa.string()), ("taxi_id", pa.int64()), ("matched_subtrajectory_id", pa.string()),
              ("edge_id", pa.string()), ("position", pa.int64()), ("gap_index", pa.int64()),
              ("start_offset_m", pa.float64()), ("end_offset_m", pa.float64()), ("traveled_distance_m", pa.float64()),
              ("estimated_entry_utc", pa.timestamp("us", tz="UTC")), ("estimated_exit_utc", pa.timestamp("us", tz="UTC")),
              ("match_method", pa.string()), ("match_quality", pa.string()), ("time_allocation_method", pa.string()),
              ("graph_version", pa.string())]
    return pa.schema([pa.field(name, kind, False) for name, kind in fields], metadata={b"schema_version": load_contracts()["schema_version"].encode()})


def match_checkpoint(trip, matcher, root: Path) -> tuple[dict, bool]:
    """One small atomic Parquet partition per trip; verified reuse and no implicit method switch."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    from .storage import sha256_file, verify_checkpoint
    identity = {"trip_id": trip.trip_id, "taxi_id": trip.taxi_id, "start": trip.start_utc.isoformat(),
                "coordinates": trip.coordinates, "graph_version": matcher.network.graph_version,
                "method": matcher.method, "settings": matcher.settings,
                "implementation_sha256": sha256_file(Path(__file__))}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    root.mkdir(parents=True, exist_ok=True)
    final = root / key
    if final.exists():
        verify_checkpoint(final)
        result = json.loads((final / "result.json").read_text(encoding="utf-8"))
        result["traversals"] = pq.ParquetFile(final / "traversals.parquet").read().to_pylist()
        return result, True
    started = time.perf_counter()
    result = matcher.match(trip)
    durations = {}
    monotonic = True
    previous_exit = trip.start_utc
    for row in result["traversals"]:
        seconds = (row["estimated_exit_utc"] - row["estimated_entry_utc"]).total_seconds()
        durations[row["gap_index"]] = durations.get(row["gap_index"], 0.0) + seconds
        monotonic = monotonic and row["estimated_entry_utc"] >= previous_exit and row["estimated_exit_utc"] >= row["estimated_entry_utc"] and row["estimated_exit_utc"] <= trip.end_utc
        previous_exit = row["estimated_exit_utc"]
    conservation_error = max((abs(value - 15) for value in durations.values()), default=None)
    covered = len(durations) / (len(trip.coordinates) - 1)
    result["quality_checks"] = {"monotonic_timestamps": monotonic, "maximum_gps_gap_conservation_error_s": conservation_error,
        "covered_gps_gap_fraction": covered, "total_inferred_duration_s": sum(durations.values()),
        "raw_nominal_elapsed_s": (trip.end_utc - trip.start_utc).total_seconds()}
    if result["status"] == "success" and (not monotonic or covered != 1 or conservation_error is None or conservation_error > 1e-5):
        result.update(status="failed_quality", reason="timestamp_or_gap_conservation_failure")
    for index, row in enumerate(result["traversals"]):
        row.update(position=index, matched_subtrajectory_id=f"{trip.trip_id}:0",
                   match_method=result["method"], match_quality=result["status"])
    stage = root / f".{key}-{uuid.uuid4().hex}.tmp"
    stage.mkdir()
    pq.write_table(pa.Table.from_pylist(result["traversals"], schema=match_schema()), stage / "traversals.parquet", compression="zstd")
    summary = {name: value for name, value in result.items() if name != "traversals"}
    (stage / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    manifest = {"processed_trip_id": trip.trip_id, "identity": identity,
                "processing_seconds": time.perf_counter() - started,
                "outputs_sha256": {name: sha256_file(stage / name) for name in ("result.json", "traversals.parquet")}}
    (stage / "run_metadata.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(stage, final)
    return result, False
