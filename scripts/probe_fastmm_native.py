"""Tiny native fastmm API/time/direction probe. All XY roads and traces are SYNTHETIC."""

import argparse
import json
import platform
from importlib.metadata import version
from pathlib import Path


def probe(output: Path) -> dict:
    import fastmm

    output.mkdir(parents=True, exist_ok=True)
    network = fastmm.Network()
    for edge_id, u, v, x0, x1 in ((101, 10, 20, 0, 100), (102, 20, 30, 100, 200), (103, 30, 40, 200, 300)):
        network.add_edge(edge_id, source=u, target=v, geom=[(x0, 0), (x1, 0)])
    network.finalize()
    matcher = fastmm.FastMapMatch(network, fastmm.TransitionMode.SHORTEST,
                                  max_distance_between_candidates=1000.0, cache_dir=output / "synthetic_ubodt")
    start = 1372636800.0
    trajectory = fastmm.Trajectory.from_xyt_tuples([(10, 0, start), (90, 0, start + 15),
                                                   (150, 0, start + 30), (250, 0, start + 45)])
    result = matcher.match(trajectory, max_candidates=4, candidate_search_radius=5.0,
                           gps_error=2.0, reverse_tolerance=0.0)
    segments = [segment for sub in result.subtrajectories if sub.error_code == fastmm.MatchErrorCode.SUCCESS
                for segment in sub.segments]
    candidate_offsets = [[s.p0.offset_from_start_of_edge, s.p1.offset_from_start_of_edge] for s in segments]
    assert candidate_offsets == [[10.0, 90.0], [90.0, 50.0], [50.0, 50.0]], "Candidate source-offset semantics changed"
    assert all(s.edges[0].points[0].edge_offset == 0.0 for s in segments), "Clipped-offset semantics changed"
    gaps, edge_ids, errors = [], set(), []
    for segment in segments:
        i0, i1 = segment.p0.trajectory_index, segment.p1.trajectory_index
        assert i1 == i0 + 1, "Native index/gap semantics changed"
        gaps.append([i0, i1])
        native_duration = 0.0
        for edge in segment.edges:
            assert not edge.reversed
            assert edge.edge_id in {101, 102, 103}
            edge_ids.add(edge.edge_id)
            assert len(edge.points) >= 2
            first, last = edge.points[0], edge.points[-1]
            assert first.t is not None and last.t is not None and last.t >= first.t
            assert last.edge_offset >= first.edge_offset
            native_duration += last.t - first.t
        errors.append(abs(native_duration - 15.0))
    assert sorted(gaps) == [[0, 1], [1, 2], [2, 3]], "Native did not cover the known path with observed zero-based indices"
    assert edge_ids == {101, 102, 103}
    assert max(errors) <= 1e-5, "Native timestamps failed the synthetic conservation check"
    reverse = matcher.match(fastmm.Trajectory.from_xyt_tuples([(250, 0, start), (10, 0, start + 15)]),
                            max_candidates=4, candidate_search_radius=5.0, gps_error=2.0, reverse_tolerance=0.0)
    reverse_segments = [s for sub in reverse.subtrajectories if sub.error_code == fastmm.MatchErrorCode.SUCCESS
                        for s in sub.segments]
    assert not reverse_segments, "Native incorrectly routed backward through one-way edges"
    report = {"data_kind": "SYNTHETIC_NATIVE_API_PROBE", "python": platform.python_version(),
              "platform": platform.platform(), "fastmm_distribution_version": version("fastmm"),
              "nodes": network.get_node_count(), "edges": network.get_edge_count(),
              "covered_gaps_zero_based": gaps, "matched_edge_ids": sorted(edge_ids),
              "candidate_source_offsets_m": candidate_offsets, "clipped_offsets_start_at_zero": True,
              "maximum_native_time_conservation_error_s": max(errors),
              "one_way_reverse_rejected": True, "status": "PASS_SYNTHETIC_ONLY"}
    (output / "native_probe.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.output), indent=2))
