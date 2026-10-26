"""Directed static/bucket routing with explicit unknown fractions and one comparison estimator."""

import math
import networkx as nx

from .congestion import parse_maxspeed


def profile_lookup(profiles: list[dict], graph_version: str) -> dict:
    if any(row["graph_version"] != graph_version for row in profiles):
        raise ValueError("Route/profile graph versions differ")
    return {(r["edge_id"], r["day_group"], r["time_bucket"]): r for r in profiles}


def edge_speed(edge, profile: dict | None, model: str, fallback_kmh: float) -> tuple[float, bool, str]:
    if model == "bucket" and profile and profile["status"] != "unknown" and profile["median_speed_kmh"]:
        return profile["median_speed_kmh"], False, "supported_bucket_estimate"
    if profile and profile.get("static_speed_kmh"):
        return profile["static_speed_kmh"], model == "bucket", "training_static_proxy"
    maximum = parse_maxspeed(edge.maxspeed_raw)
    return maximum or fallback_kmh, True, "maxspeed_weak_proxy" if maximum else "configured_unknown_fallback"


def nearest_node(network, lon: float, lat: float, maximum_distance_m: float = 300) -> int:
    x, y = network.to_metric.transform(lon, lat)
    distances = [(math.dist((x, y), network.to_metric.transform(a["x"], a["y"])), n)
                 for n, a in network.graph.nodes(data=True)]
    distance, node = min(distances)
    if distance > maximum_distance_m:
        raise ValueError(f"Endpoint is {distance:.1f} m from nearest graph node, above {maximum_distance_m} m limit")
    return node


def score_edges(network, edge_ids: list[str], lookup: dict, day: str, bucket: str, config: dict, model: str = "bucket") -> dict:
    length, seconds, unknown, unknown_edges = 0.0, 0.0, 0.0, 0
    for eid in edge_ids:
        edge = network.edges[eid]
        speed, weak, _ = edge_speed(edge, lookup.get((eid, day, bucket)), model, config["route_rules"]["fallback_speed_kmh"])
        length += edge.length_m
        seconds += edge.length_m / (speed / 3.6)
        if weak:
            unknown += edge.length_m
            unknown_edges += 1
    return {"distance_m": length, "estimated_eta_s": seconds,
            "unknown_distance_fraction": unknown / length if length else 0.0,
            "unknown_edge_fraction": unknown_edges / len(edge_ids) if edge_ids else 0.0}


def recommend_routes(network, profiles: list[dict], source: int, target: int, day: str, bucket: str, config: dict) -> dict:
    lookup = profile_lookup(profiles, network.graph_version)
    choices = {}
    for optimization in ("distance", "static", "bucket"):
        graph = nx.DiGraph()
        graph.add_nodes_from(network.graph.nodes)
        for edge in network.edges.values():
            profile = lookup.get((edge.edge_id, day, bucket))
            speed, unknown, _ = edge_speed(edge, profile, "static" if optimization == "static" else "bucket", config["route_rules"]["fallback_speed_kmh"])
            cost = edge.length_m if optimization == "distance" else edge.length_m / (speed / 3.6)
            if optimization == "bucket" and unknown:
                cost *= config["route_rules"]["unknown_cost_multiplier"]
            old = graph.get_edge_data(edge.u, edge.v)
            if old is None or (cost, edge.edge_id) < (old["weight"], old["edge_id"]):
                graph.add_edge(edge.u, edge.v, weight=cost, edge_id=edge.edge_id)
        try:
            nodes = nx.shortest_path(graph, source, target, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            raise ValueError("No directed route between endpoints on this graph") from None
        edges = [graph[u][v]["edge_id"] for u, v in zip(nodes, nodes[1:])]
        choices[optimization] = {"nodes": nodes, "edge_ids": edges,
                                 **score_edges(network, edges, lookup, day, bucket, config, "bucket"),
                                 "static_model_eta_s": score_edges(network, edges, lookup, day, bucket, config, "static")["estimated_eta_s"]}
    return {"graph_version": network.graph_version, "day_group": day, "time_bucket": bucket,
            "eta_comparison_model": "same_bucket_estimator_for_all_routes", "bucket_policy": "fixed_departure_bucket_for_whole_route",
            "interpretation": "Estimated ETA difference only; no realized travel-time savings measured", "routes": choices}
