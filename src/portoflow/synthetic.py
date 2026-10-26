"""Small labeled known-network demo. All coordinates/trips are invented."""

import copy
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import networkx as nx
from pyproj import Transformer
from shapely.geometry import LineString

from .data import RAW_COLUMNS
from .graph import RoadNetwork


def make_demo(root: Path, config: dict) -> tuple[Path, Path, dict]:
    root.mkdir(parents=True, exist_ok=True)
    metric = Transformer.from_crs("EPSG:4326", "EPSG:32629", always_xy=True)
    inverse = Transformer.from_crs("EPSG:32629", "EPSG:4326", always_xy=True)
    anchor_x, anchor_y = metric.transform(-8.61, 41.15)
    positions = {1: (0, 0), 2: (100, 0), 3: (200, 0), 4: (300, 0), 5: (100, 100), 6: (200, 100), 7: (400, 0)}
    graph = nx.MultiDiGraph(crs="EPSG:4326")
    for node, (dx, dy) in positions.items():
        lon, lat = inverse.transform(anchor_x + dx, anchor_y + dy)
        graph.add_node(node, x=lon, y=lat)
    pairs = [(1, 2), (2, 3), (3, 4), (4, 7), (2, 5), (5, 6), (6, 3)]
    for u, v in pairs + [(v, u) for u, v in pairs]:
        graph.add_edge(u, v, key=0, highway="residential", maxspeed="40",
                       geometry=LineString([(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in (u, v)]))
    network = RoadNetwork(graph, provenance={"kind": "SYNTHETIC", "note": "Invented 100-m grid near Porto coordinates, not OSM data"})
    graph_folder = root / "graph"
    network.save(graph_folder)
    rows = []
    zone = ZoneInfo("Europe/Lisbon")
    for year, month, dates in ((2013, 7, [1, 2, 3]), (2014, 1, [6, 7])):
        for date in dates:
            for taxi in [1001, 1002, 1003]:
                for hour, step in [(2, 70), (7, 20)]:
                    xs = list(range(10, 291, step))
                    coords = [inverse.transform(anchor_x + x, anchor_y + 0.2 * (taxi - 1002)) for x in xs]
                    start = datetime(year, month, date, hour, taxi - 1001, tzinfo=zone)
                    rows.append(dict(zip(RAW_COLUMNS, [f"SYNTHETIC_DEMO_{year}_{date}_{taxi}_{hour}", "C", "", "", str(taxi),
                        str(int(start.timestamp())), "A", "False", json.dumps(coords)])))
    extra = dict(rows[0], TRIP_ID="SYNTHETIC_DEMO_OFF_NETWORK", TIMESTAMP=str(int(datetime(2013, 7, 1, 8, tzinfo=zone).timestamp())),
                 POLYLINE=json.dumps([inverse.transform(anchor_x + x, anchor_y + 250) for x in (10, 50, 90)]))
    rows.append(extra)
    rows.append(dict(rows[0], TRIP_ID="SYNTHETIC_DEMO_MISSING", MISSING_DATA="True"))
    rows.append(dict(rows[0], TRIP_ID="SYNTHETIC_DEMO_MALFORMED", POLYLINE="broken"))
    source = root / "synthetic_demo.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=RAW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    settings = copy.deepcopy(config)
    settings["split"]["train_cutoff_utc"] = "2014-01-01T00:00:00+00:00"
    settings["profile_rules"] = {"min_distinct_trips": 3, "min_distinct_taxis": 2, "min_distinct_dates": 2,
                                  "slow_ratio_threshold": 0.7, "high_slowdown_ratio_threshold": 0.4}
    return source, graph_folder, settings
