"""Region geometry, admission, clipping, leakage and resumable SYNTHETIC execution."""
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pyarrow.parquet as pq
import pytest
import yaml
from shapely.geometry import LineString

from portoflow import pipeline as r
from portoflow.config import load_config
from portoflow.graph import RoadNetwork
from portoflow.preprocess import Trip
from portoflow.storage import verify_checkpoint
from portoflow.synthetic import make_demo

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture(tmp_path):
    plan = yaml.safe_load((ROOT/'configs/study_area.yaml').read_text(encoding='utf-8'))
    plan.update(raw_batch_rows=5, match_batch_trips=3, matching_timeout_seconds=120,
                scan_timeout_seconds=120, report_timeout_seconds=120,
                train_cutoff_utc='2014-01-01T00:00:00Z')
    source, graph_path, _ = make_demo(tmp_path/'fixture', load_config(ROOT/'configs/default.yaml'))
    context, core, summary = r.build_networks(RoadNetwork.load(graph_path).graph, plan, synthetic=True)
    work = tmp_path/'work'; work.mkdir()
    context.save(work/'context_graph'); core.save(work/'graph')
    config = r.scientific_config(plan, ROOT/'configs/default.yaml')
    return source, work, plan, config, context, core


def test_exact_metric_square_and_scoped_limits(fixture):
    _, _, plan, _, _, _ = fixture
    core, context, _, _ = r.region_geometry(plan)
    assert core.area == 100000000
    assert core.bounds[2]-core.bounds[0] == 10000
    assert context.area == 121000000
    for key, bad in [('width_m', 8000), ('max_graph_edges', 1000000), ('stop_at_coverage_target', True)]:
        with pytest.raises(ValueError):
            r.validate_plan(dict(plan, **{key: bad}))


def test_cross_region_parent_keeps_all_disjoint_blocks(fixture):
    _, _, plan, _, _, _ = fixture
    square, _, _, inverse = r.region_geometry(plan)
    x = (square.bounds[0]+square.bounds[2])/2; y = (square.bounds[1]+square.bounds[3])/2
    points = [inverse.transform(x+6000, y)]*10
    for _ in range(3):
        points += [inverse.transform(x+i*10, y) for i in range(8)]
        points += [inverse.transform(x+6000, y)]*10
    parent = Trip('crossing', 1, datetime(2013, 7, 1, tzinfo=timezone.utc), tuple(points), 1)
    assert len(r.block_ranges(parent, plan)) == 3
    assert sum(b-a for a, b in r.block_ranges(parent, plan))/len(points) < .9


def test_clip_offsets_conserve_retained_distance_and_duration(fixture):
    _, _, plan, _, context, core = fixture
    assert r.inside_intervals(LineString([(-10, 0), (10, 0)]), (-5, -5, 5, 5)) == [(5., 15.)]
    assert r.inside_intervals(LineString([(0, 10), (20, 10)]), (-5, -5, 5, 5)) == []
    square, _, _, inverse = r.region_geometry(plan)
    y = (square.bounds[1]+square.bounds[3])/2
    import networkx as nx
    graph = nx.MultiDiGraph(crs='EPSG:4326')
    for node, x in [(1, square.bounds[0]-100), (2, square.bounds[0]+100)]:
        lon, lat = inverse.transform(x, y); graph.add_node(node, x=lon, y=lat)
    graph.add_edge(1, 2, key=0, geometry=LineString([(graph.nodes[n]['x'], graph.nodes[n]['y']) for n in (1, 2)]))
    context, core, _ = r.build_networks(graph, plan, synthetic=True)
    edge = next(iter(context.edges.values())); start = datetime(2013, 7, 1, tzinfo=timezone.utc)
    clipped = r.clip_rows([{'edge_id': edge.edge_id, 'start_offset_m': 0., 'end_offset_m': edge.length_m,
        'traveled_distance_m': edge.length_m, 'estimated_entry_utc': start,
        'estimated_exit_utc': start+timedelta(seconds=15), 'graph_version': context.graph_version}], context, core, plan)
    assert sum(v['traveled_distance_m'] for v in clipped) == pytest.approx(100, abs=.001)
    assert (clipped[0]['estimated_exit_utc']-clipped[0]['estimated_entry_utc']).total_seconds() == pytest.approx(7.5, abs=.001)
    assert clipped[0]['graph_version'] == core.graph_version


def test_eof_resume_duplicate_quarantine_and_holdout_isolation(fixture):
    source, work, plan, config, _, _ = fixture
    with source.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream); names = reader.fieldnames; rows = list(reader)
    rows.append(dict(rows[0], MISSING_DATA='True'))
    with source.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=names); writer.writeheader(); writer.writerows(rows)
    scanned = r.scan_source(source, work, plan, config, synthetic=True)
    assert scanned['rows'] == 34 and scanned['duplicate_ids'] == 1
    assert r.scan_source(source, work, plan, config, synthetic=True) == scanned
    summary = r.run_matching(work, plan, config, synthetic=True)
    assert summary['all_eligible_complete']
    assert summary['completed_parents'] == scanned['eligible_unique_parents']
    with patch.object(r.HMMMatcher, 'match', side_effect=AssertionError('resume must not repeat native work')):
        assert r.run_matching(work, plan, config, synthetic=True) == summary
    candidate = r.report(work, plan, config)
    assert not candidate['automatic_app_update']
    manifest = verify_checkpoint(work/'review_export')
    assert manifest['data_kind'] == 'SYNTHETIC'
    import sqlite3
    with sqlite3.connect(work/'region_evidence.sqlite') as db:
        ids = {row[0] for row in db.execute('SELECT DISTINCT trip_id FROM evidence')}
    assert ids and all('2013' in identifier for identifier in ids)
    assert rows[0]['TRIP_ID'] not in ids
    assert len(candidate['coverage']['buckets']) == 12
    evaluation = candidate['evaluation']
    assert evaluation['holdout_excluded_from_profiles']
    assert evaluation['metrics']['static']['n'] == evaluation['metrics']['bucket']['n'] > 0
    with (work/'review_export/holdout_components.csv').open(newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            assert '2014' in row['trip_id']
            assert float(row['raw_elapsed_s']) == 15*(int(row['last_gap'])-int(row['first_gap'])+1)
    profiles = pq.read_table(work/'review_export/congestion_profiles.parquet').to_pylist()
    assert any(row['status'] == 'unknown' for row in profiles)


def test_partial_scan_cannot_match(fixture):
    source, work, plan, config, _, _ = fixture
    plan['max_raw_rows'] = 10
    with pytest.raises(ValueError, match='ceiling'):
        r.scan_source(source, work, plan, config, synthetic=True)
    assert not (work/'source_summary.json').exists()
    with pytest.raises(FileNotFoundError):
        r.run_matching(work, plan, config, synthetic=True)


def test_committed_batch_survives_session_timeout(fixture):
    source, work, plan, config, _, _ = fixture
    r.scan_source(source, work, plan, config, synthetic=True)
    original = r.guard_resources
    calls = 0
    def interrupt(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise TimeoutError('synthetic session deadline')
        return original(*args, **kwargs)
    with patch.object(r, 'guard_resources', side_effect=interrupt):
        first = r.run_matching(work, plan, config, synthetic=True)
    assert not first['all_eligible_complete']
    assert first['completed_parents']['train'] == 4
    completed = r.run_matching(work, plan, config, synthetic=True)
    assert completed['all_eligible_complete']
    assert completed['completed_parents'] == completed['expected_parents']


def test_tampered_source_index_rejected_before_matching(fixture):
    source, work, plan, config, _, _ = fixture
    r.scan_source(source, work, plan, config, synthetic=True)
    import sqlite3
    with sqlite3.connect(work/'source_index.sqlite') as db:
        db.execute('DELETE FROM parents WHERE rownum=(SELECT MIN(rownum) FROM parents)')
    with pytest.raises(ValueError, match='checksum'):
        r.run_matching(work, plan, config, synthetic=True)


def test_native_region_adapter_uses_inherited_decoder(fixture):
    pytest.importorskip('fastmm')
    source, work, plan, config, context, core = fixture
    with source.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    row = next(row for row in rows if len(json.loads(row['POLYLINE'])) >= 6)
    from portoflow.preprocess import parse_trip
    parent = parse_trip(row, 1, config)
    for _ in range(3):
        matcher = r.RegionFastMMMatcher(context, config['matching'], work/'native_cache', plan)
        observations, summary, native = r.match_parent(parent, r.block_ranges(parent, plan), 'train', matcher, context, core, config, plan)
        assert observations and summary['accepted_observations'] > 0
        assert native[0]['result']['method'] == 'fastmm:0.3.2'
        assert all(v['graph_version'] == core.graph_version for v in observations)
        matcher.close()


def test_native_synthetic_end_to_end(fixture):
    """Real fastmm through scan/match/report; every input remains labeled synthetic."""
    pytest.importorskip('fastmm')
    source, work, plan, config, _, _ = fixture
    r.scan_source(source, work, plan, config, synthetic=True)
    native = lambda network, settings: r.RegionFastMMMatcher(network, settings, work/'native_cache', plan)
    with patch.object(r, 'HMMMatcher', side_effect=native):
        summary = r.run_matching(work, plan, config, synthetic=True)
    assert summary['all_eligible_complete']
    assert summary['parents_with_accepted_core_observations']['train'] > 0
    result = r.report(work, plan, config)
    assert result['evaluation']['metrics']['bucket']['n'] > 0
    assert verify_checkpoint(work/'review_export')['data_kind'] == 'SYNTHETIC'
