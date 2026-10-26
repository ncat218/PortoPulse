"""Independent 10 km Porto run; whole-parent split, buffered blocks, EOF completion.

Legacy experiments and their scientific settings are not edited. Native decoding
and gap QC are reused. Full-region exports remain candidates pending review.
"""
import copy
import csv
import json
import math
import os
import sqlite3
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import networkx as nx
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer
from shapely import transform as project_geometry
from shapely.geometry import LineString, box, mapping

from .config import load_config
from .data import _stream_batches
from .export import serve_geojson, write_json, write_profiles
from .graph import RoadNetwork
from .state import digest, guard_resources, state_get, state_set
from .profiles import apply_observations, coverage_report, disk_profiles, open_evidence
from .schemas import observation_schema
from .matching import FastMMMatcher, HMMMatcher
from .preprocess import Trip, TripRejected, assign_split, parse_trip
from .route import edge_speed, profile_lookup
from .config import bucket_for_local_time
from .segment_qc import usable_traversals
from .speed import build_observations
from .storage import sha256_file, verify_checkpoint

TOKEN = 'PORTOFLOW_FULL_SOURCE_V1'


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name('.'+path.name+'.tmp')
    write_json(temporary, value)
    os.replace(temporary, path)


def validate_plan(plan):
    if (plan.get('authorization') != TOKEN or plan.get('width_m') != 10000 or
            plan.get('height_m') != 10000 or plan.get('metric_crs') != 'EPSG:32629' or
            plan.get('stop_at_coverage_target') is not False or
            plan.get('automatic_app_update') is not False):
        raise ValueError('Require the explicit 10 km full-source scope')
    lon, lat = plan['center_lonlat']
    if not (-8.8 < lon < -8.4 and 41.0 < lat < 41.4):
        raise ValueError('Center must remain in Porto')
    limits = {'matching_buffer_m': (0, 500), 'max_raw_rows': (1, 2000000),
              'raw_batch_rows': (1, 1000), 'max_points_per_trip': (6, 2000),
              'minimum_block_points': (6, 20), 'match_batch_trips': (1, 20),
              'max_batch_observations': (1, 250000), 'max_graph_edges': (1, 60000),
              'scan_timeout_seconds': (1, 5400), 'matching_timeout_seconds': (1, 21600),
              'report_timeout_seconds': (1, 1800), 'max_rss_mb': (128, 12000),
              'max_output_gb': (1, 12)}
    for key, (low, high) in limits.items():
        if type(plan.get(key)) is not int or not low <= plan[key] <= high:
            raise ValueError('Invalid region ceiling: '+key)
    if (plan.get('partial_policy') != 'validated_blocks_v1' or
            plan.get('partial_minimum_gap_fraction') != .9 or
            plan.get('partial_boundary_trim_gaps') != 1 or
            plan.get('partial_minimum_block_gaps') != 3 or
            plan.get('reference_coverage_fraction') != .8):
        raise ValueError('Gap QC/support are explicit; do not silently relax them')
    start = datetime.fromisoformat(plan['window_start_local']).replace(tzinfo=ZoneInfo('Europe/Lisbon'))
    end = datetime.fromisoformat(plan['window_end_local_exclusive']).replace(tzinfo=ZoneInfo('Europe/Lisbon'))
    cutoff = datetime.fromisoformat(plan['train_cutoff_utc'].replace('Z', '+00:00'))
    if cutoff.utcoffset() != timedelta(0) or not start < cutoff < end or (end-start).days > 366:
        raise ValueError('Invalid whole-parent temporal split')
    return start, end, cutoff


@lru_cache(maxsize=8)
def _geometry(lon, lat, buffer_m, crs):
    forward = Transformer.from_crs('EPSG:4326', crs, always_xy=True)
    inverse = Transformer.from_crs(crs, 'EPSG:4326', always_xy=True)
    x, y = forward.transform(lon, lat)
    core = box(x-5000, y-5000, x+5000, y+5000)
    context = box(x-5000-buffer_m, y-5000-buffer_m, x+5000+buffer_m, y+5000+buffer_m)
    return core, context, forward, inverse


def region_geometry(plan):
    return _geometry(*plan['center_lonlat'], plan['matching_buffer_m'], plan['metric_crs'])


def scientific_config(plan, path):
    config = copy.deepcopy(load_config(path))
    config['s01']['max_points_per_trip'] = plan['max_points_per_trip']
    config['split']['train_cutoff_utc'] = plan['train_cutoff_utc']
    config['profile_rules'].update(min_distinct_trips=3, min_distinct_taxis=2,
        min_distinct_dates=2, slow_ratio_threshold=.7, high_slowdown_ratio_threshold=.4)
    config['matching']['max_graph_edges'] = plan['max_graph_edges']
    return config


def code_identity():
    folder = Path(__file__).parent
    return {p.name: sha256_file(p) for p in sorted(folder.iterdir()) if p.suffix in {'.py', '.json'}}


def build_networks(graph, plan, *, synthetic=False):
    core, _, _, inverse = region_geometry(plan)
    if len(graph.edges) > plan['max_graph_edges']:
        raise ValueError('Fetched graph exceeds region ceiling; do not truncate silently')
    common = {'kind': 'SYNTHETIC' if synthetic else 'OSM_CURRENT', 'region_scope': TOKEN,
              'region_plan': plan, 'core_polygon_lonlat': mapping(project_geometry(core, inverse.transform, interleaved=False)),
              'fetch_utc': datetime.now(timezone.utc).isoformat()}
    context = RoadNetwork(graph, plan['metric_crs'], dict(common, role='matching_context'))
    retained = [edge for edge in context.edges.values() if edge.metric_geometry.intersection(core).length > 1e-6]
    if not retained:
        raise ValueError('No positive-length driving edges in the study region')
    directed = nx.MultiDiGraph(crs='EPSG:4326')
    for edge in retained:
        for node in (edge.u, edge.v):
            directed.add_node(node, **dict(context.graph.nodes[node]))
        directed.add_edge(edge.u, edge.v, key=edge.key, geometry=edge.geometry,
                          highway=edge.highway, maxspeed_raw=edge.maxspeed_raw)
    serving = RoadNetwork(directed, plan['metric_crs'], dict(common, role='study_region',
                          context_graph_version=context.graph_version))
    summary = {'core_area_m2': core.area, 'core_directed_edges': len(serving.edges),
               'context_directed_edges': len(context.edges),
               'core_directed_length_m': sum(e.metric_geometry.intersection(core).length for e in retained),
               'context_graph_version': context.graph_version, 'core_graph_version': serving.graph_version,
               'center_lonlat': plan['center_lonlat'], 'core_polygon_lonlat': common['core_polygon_lonlat'],
               'matching_buffer_m': plan['matching_buffer_m']}
    return context, serving, summary


def fetch_region(work, plan):
    """One explicit driving graph; saved OSM geometry has its own content identity."""
    validate_plan(plan)
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    if (work/'region.json').is_file():
        existing = json.loads((work/'region.json').read_text(encoding='utf-8'))
        if existing['plan'] != plan:
            raise ValueError('Region plan changed; use another workspace')
        RoadNetwork.load(work/'context_graph'); RoadNetwork.load(work/'graph')
        return existing
    import osmnx as ox
    _, context, _, inverse = region_geometry(plan)
    polygon = project_geometry(context, inverse.transform, interleaved=False)
    previous = {k: getattr(ox.settings, k) for k in ('cache_folder', 'use_cache', 'requests_timeout')}
    try:
        ox.settings.cache_folder = str(work/'osm_cache')
        ox.settings.use_cache = True
        ox.settings.requests_timeout = 180
        graph = ox.graph_from_polygon(polygon, network_type='drive', simplify=True,
                                      retain_all=True, truncate_by_edge=True)
    finally:
        for key, value in previous.items():
            setattr(ox.settings, key, value)
    context_network, core_network, summary = build_networks(graph, plan)
    context_network.save(work/'context_graph'); core_network.save(work/'graph')
    summary.update(plan=plan, osmnx_version=ox.__version__,
                   limitation='Current OSM, compared with 2013-2014 taxi GPS')
    atomic_json(work/'region.json', summary)
    return summary


def block_ranges(trip, plan):
    """All continuous sampled-point runs in context; no two-block limit or 90% admission."""
    core, context, forward, _ = region_geometry(plan)
    xs, ys = forward.transform(*zip(*trip.coordinates))
    xy = list(zip(xs, ys)); bounds = context.bounds
    flags = [bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3] for x, y in xy]
    result = []; low = None
    for index in range(len(xy)+1):
        inside = index < len(xy) and flags[index]
        if inside and low is None:
            low = index
        elif not inside and low is not None:
            if index-low >= plan['minimum_block_points'] and LineString(xy[low:index]).intersection(core).length > 1e-6:
                result.append((low, index))
            low = None
    return result


def scan_source(source, work, plan, config, *, synthetic=False):
    start, end, cutoff = validate_plan(plan)
    work = Path(work); source = Path(source)
    if not synthetic:
        RoadNetwork.load(work/'graph')
    work.mkdir(parents=True, exist_ok=True)
    identity = {'source_sha256': sha256_file(source), 'source_size': source.stat().st_size,
                'plan': plan, 'config': config, 'code': code_identity(), 'synthetic': synthetic}
    deadline = time.monotonic()+plan['scan_timeout_seconds']
    db = sqlite3.connect(work/'source_index.sqlite')
    try:
        db.executescript('''CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS seen(trip_id TEXT PRIMARY KEY,n INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS parents(rownum INTEGER PRIMARY KEY,trip_id TEXT,taxi_id INTEGER,
                start_utc TEXT,coordinates TEXT,split TEXT,blocks TEXT);
            CREATE INDEX IF NOT EXISTS parent_split ON parents(split,rownum);
            CREATE TABLE IF NOT EXISTS inventory(reason TEXT PRIMARY KEY,n INTEGER NOT NULL);''')
        previous = state_get(db, 'identity')
        if previous is not None and previous != identity:
            raise ValueError('Source/plan/code changed; do not reuse the index')
        if previous is None:
            state_set(db, 'identity', identity); db.commit()
        if not state_get(db, 'complete', False):
            committed = state_get(db, 'rows', 0); schema = {}
            for batch in _stream_batches(source, batch_size=plan['raw_batch_rows'], max_rows=plan['max_raw_rows']+1,
                    member=config['dataset']['expected_csv_member'], schema_info=schema):
                guard_resources(work, plan, deadline)
                with db:
                    for number, row in batch:
                        if number <= committed:
                            continue
                        if number > plan['max_raw_rows']:
                            raise ValueError('Source ceiling exceeded before EOF; index remains incomplete')
                        tid = (row.get('TRIP_ID') or '').strip()
                        db.execute('INSERT INTO seen VALUES (?,1) ON CONFLICT(trip_id) DO UPDATE SET n=n+1', (tid,))
                        try:
                            trip = parse_trip(row, number, config)
                            if not start <= trip.start_utc < end:
                                raise TripRejected('outside_study_year')
                            split = assign_split(trip, cutoff)
                            if split == 'boundary_purged':
                                raise TripRejected('temporal_boundary_purged')
                            blocks = block_ranges(trip, plan)
                            if not blocks:
                                raise TripRejected('no_eligible_continuous_region_block')
                            db.execute('INSERT INTO parents VALUES (?,?,?,?,?,?,?)', (number, tid, trip.taxi_id,
                                trip.start_utc.isoformat(), json.dumps(trip.coordinates), split, json.dumps(blocks)))
                            reason = 'candidate_'+split
                        except TripRejected as exc:
                            reason = str(exc)
                        db.execute('INSERT INTO inventory VALUES (?,1) ON CONFLICT(reason) DO UPDATE SET n=n+1', (reason,))
                        state_set(db, 'rows', number)
                    state_set(db, 'input_schema', schema)
                print('SOURCE committed', state_get(db, 'rows'), flush=True)
            state_set(db, 'complete', True); db.commit()
        counts = dict(db.execute('SELECT p.split,COUNT(*) FROM parents p JOIN seen s USING(trip_id) WHERE s.n=1 GROUP BY p.split'))
        result = {'status': 'SOURCE_EOF_COMPLETE', 'rows': state_get(db, 'rows', 0),
                  'eligible_unique_parents': counts, 'identity': identity,
                  'index_sha256': sha256_file(work/'source_index.sqlite'),
                  'inventory': dict(db.execute('SELECT reason,n FROM inventory')),
                  'duplicate_ids': db.execute('SELECT COUNT(*) FROM seen WHERE n>1').fetchone()[0],
                  'resume': 'ZIP prefix is decompressed again; committed GPS is not reparsed'}
        atomic_json(work/'source_summary.json', result)
        return result
    finally:
        db.close()


class RegionFastMMMatcher(FastMMMatcher):
    """Same inherited decoder/match; explicit larger initialization scope only."""
    def __init__(self, network, settings, cache_dir, plan):
        validate_plan(plan)
        if network.provenance.get('region_scope') != TOKEN or network.provenance.get('region_plan') != plan:
            raise ValueError('Region matcher requires its own verified graph scope')
        if not 0 < len(network.edges) <= plan['max_graph_edges']:
            raise ValueError('Region graph budget exceeded')
        import fastmm
        if version('fastmm') != '0.3.2':
            raise ValueError('Verified fastmm 0.3.2 required; no automatic fallback')
        self.module, self.network, self.settings = fastmm, network, settings
        self.method = 'fastmm:0.3.2'
        self.native_network = fastmm.Network()  # Keep the borrowed native owner alive.
        self.numeric_to_edge = {i: eid for i, eid in enumerate(sorted(network.edges), 1)}
        for numeric, eid in self.numeric_to_edge.items():
            edge = network.edges[eid]
            self.native_network.add_edge(numeric, source=edge.u, target=edge.v, geom=list(edge.metric_geometry.coords))
        self.native_network.finalize()
        self.matcher = fastmm.FastMapMatch(self.native_network, fastmm.TransitionMode.SHORTEST,
            max_distance_between_candidates=settings['ubodt_distance_m'], cache_dir=Path(cache_dir)/network.graph_version)
        if not hasattr(fastmm.Trajectory, 'from_xyt_tuples'):
            raise ValueError('Incompatible native API')

    def close(self):
        # FastMapMatch borrows Network: destroy the borrower before its owner.
        # Attribute insertion/destruction order alone is not a lifetime contract.
        self.matcher = None
        self.native_network = None

    def __del__(self):
        self.close()


def inside_intervals(line, bounds):
    """Clip each straight segment to a metric rectangle, preserving line offsets."""
    intervals = []; offset = 0.0
    for (x0, y0), (x1, y1) in zip(line.coords, list(line.coords)[1:]):
        dx, dy = x1-x0, y1-y0; length = math.hypot(dx, dy)
        if length == 0:
            continue
        low, high = 0.0, 1.0
        for p, q in ((-dx, x0-bounds[0]), (dx, bounds[2]-x0), (-dy, y0-bounds[1]), (dy, bounds[3]-y0)):
            if p == 0:
                if q < 0:
                    high = -1; break
            elif p < 0:
                low = max(low, q/p)
            else:
                high = min(high, q/p)
        if high > low:
            a, b = offset+low*length, offset+high*length
            if intervals and abs(intervals[-1][1]-a) < 1e-6:
                intervals[-1] = (intervals[-1][0], b)
            else:
                intervals.append((a, b))
        offset += length
    return intervals


def clip_rows(rows, context, core_network, plan):
    core, _, _, _ = region_geometry(plan)
    result = []
    intervals = {}
    for row in rows:
        if row['edge_id'] not in core_network.edges:
            continue
        a, b = row['start_offset_m'], row['end_offset_m']
        if b <= a:
            continue  # Existing speed policy excludes zero matched displacement.
        edge = context.edges[row['edge_id']]
        if edge.edge_id not in intervals:
            intervals[edge.edge_id] = inside_intervals(edge.metric_geometry, core.bounds)
        ranges = intervals[edge.edge_id]
        duration = (row['estimated_exit_utc']-row['estimated_entry_utc']).total_seconds()
        for low, high in ranges:
            left, right = max(a, low), min(b, high)
            if right <= left:
                continue
            result.append(dict(row, start_offset_m=left, end_offset_m=right, traveled_distance_m=right-left,
                estimated_entry_utc=row['estimated_entry_utc']+timedelta(seconds=duration*(left-a)/(b-a)),
                estimated_exit_utc=row['estimated_entry_utc']+timedelta(seconds=duration*(right-a)/(b-a)),
                graph_version=core_network.graph_version))
    return result


def match_parent(parent, ranges, split, matcher, context, core_network, config, plan):
    selected = []; block_info = []; native_cases = []
    complete_parent = False
    for low, high in ranges:
        block = Trip(parent.trip_id, parent.taxi_id, parent.start_utc+timedelta(seconds=15*low),
                     parent.coordinates[low:high], parent.source_row)
        raw = matcher.match(block)
        full, kept, qc = usable_traversals(block, raw, context, config, plan)
        entire_parent = low == 0 and high == len(parent.coordinates)
        if full and not entire_parent:
            # A successful cropped block still has artificial boundaries.
            trim = plan['partial_boundary_trim_gaps']; last_gap = len(block.coordinates)-2
            kept = [r for r in kept if trim <= r['gap_index'] <= last_gap-trim]
        if len({r['gap_index'] for r in kept}) < plan['partial_minimum_block_gaps']:
            kept = []
        complete_parent = complete_parent or bool(full and entire_parent)
        native_cases.append({'point_offset': low, 'point_stop': high, 'result': raw})
        selected.extend(dict(r, gap_index=r['gap_index']+low) for r in kept)
        block_info.append({'point_start': low, 'point_stop': high, 'native_status': raw['status'], 'qc': qc})
    observations = build_observations(clip_rows(selected, context, core_network, plan), config)
    for row in observations:
        row.update(split=split, complete_trip_evidence=complete_parent)
    summary = {'trip_id': parent.trip_id, 'source_row': parent.source_row, 'split': split,
               'whole_parent_complete': complete_parent, 'blocks': block_info,
               'accepted_observations': sum(r['quality_flag'] == 'accepted_inferred' for r in observations)}
    return observations, summary, native_cases


def run_matching(work, plan, config, *, synthetic=False):
    validate_plan(plan); work = Path(work)
    context = RoadNetwork.load(work/'context_graph'); core_network = RoadNetwork.load(work/'graph')
    if synthetic != (context.provenance.get('kind') == 'SYNTHETIC'):
        raise ValueError('Synthetic/native source mismatch')
    source = json.loads((work/'source_summary.json').read_text(encoding='utf-8'))
    if source.get('status') != 'SOURCE_EOF_COMPLETE' or sha256_file(work/'source_index.sqlite') != source['index_sha256']:
        raise ValueError('Source index checksum differs or EOF scan is incomplete')
    identity = {'source': source['identity'], 'context_graph': context.graph_version,
                'core_graph': core_network.graph_version, 'code': code_identity(), 'plan': plan,
                'config': config, 'runtime': {k: version(k) for k in ('pyarrow', 'shapely', 'pyproj', 'networkx')}}
    if source['identity']['config'] != config or source['identity']['plan'] != plan or source['identity']['code'] != code_identity():
        raise ValueError('Complete source index identity differs')
    batches = work/'region_batches'; batches.mkdir(exist_ok=True)
    done = set(); outcomes = Counter(); accepted = Counter(); review_counts = Counter()
    for folder in sorted(batches.iterdir()):
        if folder.name.startswith('.'):
            continue
        metadata = verify_checkpoint(folder)
        if metadata['identity'] != identity:
            raise ValueError('Matching batch identity differs')
        review_counts.update(r['split'] for r in json.loads((folder/'review_cases.json').read_text(encoding='utf-8')))
        for row in json.loads((folder/'parents.json').read_text(encoding='utf-8')):
            if row['trip_id'] in done:
                raise ValueError('Duplicate committed parent')
            done.add(row['trip_id']); outcomes[row['split']] += 1
            accepted[row['split']] += int(row['accepted_observations'] > 0)
    deadline = time.monotonic()+plan['matching_timeout_seconds']-min(60, plan['matching_timeout_seconds']/10)
    db = sqlite3.connect(work/'source_index.sqlite')
    matcher = None; pending = []; records = []; review = []; status = 'MATCHING_ALL_ELIGIBLE_COMPLETE'
    base_bytes = sum(p.stat().st_size for p in work.rglob('*') if p.is_file() and 'native_cache' not in p.relative_to(work).parts)
    def commit():
        nonlocal pending, records, review, base_bytes
        if not records:
            return
        name = digest([identity, [r['trip_id'] for r in records]])[:24]
        staging = batches/('.'+name+'-'+uuid.uuid4().hex+'.tmp'); staging.mkdir()
        pq.write_table(pa.Table.from_pylist(pending, schema=observation_schema()), staging/'observations.parquet', compression='zstd')
        write_json(staging/'parents.json', records)
        write_json(staging/'review_cases.json', review)
        write_json(staging/'run_metadata.json', {'identity': identity, 'outputs_sha256': {
            n: sha256_file(staging/n) for n in ('observations.parquet', 'parents.json', 'review_cases.json')}})
        os.replace(staging, batches/name)
        base_bytes += sum(p.stat().st_size for p in (batches/name).iterdir())
        for row in records:
            done.add(row['trip_id']); outcomes[row['split']] += 1
            accepted[row['split']] += int(row['accepted_observations'] > 0)
        pending = []; records = []; review = []
        atomic_json(work/'matching_progress.json', {'completed_parents': dict(outcomes), 'parents_with_accepted_core_observations': dict(accepted)})
        print('MATCH committed', dict(outcomes), flush=True)
        native_bytes = sum(p.stat().st_size for p in (work/'native_cache').rglob('*') if p.is_file())
        if base_bytes+native_bytes > plan['max_output_gb']*1024**3:
            raise OSError('Output ceiling reached; committed batches retained')
    try:
        if not state_get(db, 'complete', False) or state_get(db, 'identity') != source['identity']:
            raise ValueError('Only the verified complete EOF index may feed matching')
        for split in ('train', 'holdout'):
            cursor = db.execute('SELECT p.* FROM parents p JOIN seen s USING(trip_id) WHERE s.n=1 AND p.split=? ORDER BY p.rownum', (split,))
            for number, tid, taxi, start, coords, label, ranges in cursor:
                if tid in done:
                    continue
                guard_resources(work, plan, deadline, check_disk=False)
                if matcher is None:
                    matcher = (HMMMatcher(context, config['matching']) if synthetic else
                               RegionFastMMMatcher(context, config['matching'], work/'native_cache', plan))
                parent = Trip(tid, taxi, datetime.fromisoformat(start), tuple(map(tuple, json.loads(coords))), number)
                observed, record, native = match_parent(parent, json.loads(ranges), label, matcher, context, core_network, config, plan)
                if len(pending)+len(observed) > plan['max_batch_observations']:
                    commit()
                if len(observed) > plan['max_batch_observations']:
                    raise MemoryError('Single parent exceeds observation ceiling')
                pending.extend(observed); records.append(record)
                # Small raw GPS/native examples support review; the full corpus stores compact evidence.
                if review_counts[label] < 10:
                    review.append({'split': label, 'parent': parent.__dict__, 'native': native})
                    review_counts[label] += 1
                if len(records) >= plan['match_batch_trips']:
                    commit()
        commit()
    except (TimeoutError, MemoryError, OSError):
        commit(); status = 'MATCHING_PARTIAL_CHECKPOINTED'
    finally:
        db.close()
        if isinstance(matcher, RegionFastMMMatcher):
            matcher.close()
    expected = source['eligible_unique_parents']
    complete = all(outcomes[k] == expected.get(k, 0) for k in ('train', 'holdout'))
    result = {'status': status if complete else 'MATCHING_PARTIAL_CHECKPOINTED', 'all_eligible_complete': complete,
              'expected_parents': expected, 'completed_parents': dict(outcomes),
              'parents_with_accepted_core_observations': dict(accepted), 'identity': identity,
              'coverage_is_not_a_stop_condition': True, 'automatic_app_update': False}
    atomic_json(work/'matching_summary.json', result)
    return result


def evaluate_saved_holdout(work, output, network, profiles, config, cutoff, guard):
    """Score continuous complete GPS gaps, against their raw nominal elapsed time.

    Boundary-clipped/incomplete gaps are excluded instead of treating inferred
    sub-edge durations as independently observed targets. Both models use the
    same eligible components and their departure bucket.
    """
    lookup = profile_lookup(profiles, network.graph_version)
    metrics = {name: {'n': 0, 'absolute': 0., 'squared': 0.} for name in ('static', 'bucket')}
    trips = set(); scored_trips = set(); exclusions = Counter(); components = 0
    with (output/'holdout_components.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['trip_id', 'first_gap', 'last_gap', 'raw_elapsed_s',
            'distance_m', 'static_eta_s', 'bucket_eta_s', 'unknown_distance_fraction', 'scored'])
        writer.writeheader()
        for folder in sorted((work/'region_batches').iterdir()):
            if folder.name.startswith('.'):
                continue
            guard()
            by_trip = defaultdict(lambda: defaultdict(list))
            for row in pq.ParquetFile(folder/'observations.parquet').read().to_pylist():
                if row['split'] != 'holdout':
                    continue
                if row['graph_version'] != network.graph_version or row['estimated_entry_utc'] < cutoff:
                    raise ValueError('Holdout temporal/graph identity mismatch')
                trips.add(row['trip_id'])
                if row['quality_flag'] == 'accepted_inferred':
                    by_trip[row['trip_id']][row['gap_index']].append(row)
            for tid, gaps in by_trip.items():
                runs = []
                for index, rows in sorted(gaps.items()):
                    elapsed = sum(row['observed_or_inferred_duration_s'] for row in rows)
                    if abs(elapsed-15) > 1e-5:
                        exclusions['incomplete_or_boundary_clipped_gaps'] += 1
                        continue
                    if not runs or runs[-1][-1][0]+1 != index:
                        runs.append([])
                    runs[-1].append((index, rows))
                for run in runs:
                    if len(run) < 3:
                        exclusions['components_under_three_complete_gaps'] += 1
                        continue
                    rows = [row for _, pieces in run for row in pieces]
                    departure = min(row['estimated_entry_utc'] for row in rows)
                    day, bucket = bucket_for_local_time(departure.astimezone(ZoneInfo('Europe/Lisbon')), config)
                    estimates = {'static': 0., 'bucket': 0.}; unknown = 0.; distance = 0.
                    for row in rows:
                        edge = network.edges[row['edge_id']]; length = row['traveled_distance_m']
                        profile = lookup.get((edge.edge_id, day, bucket))
                        for name in estimates:
                            speed, weak, _ = edge_speed(edge, profile, name, config['route_rules']['fallback_speed_kmh'])
                            estimates[name] += length/(speed/3.6)
                            if name == 'bucket' and weak:
                                unknown += length
                        distance += length
                    fraction = unknown/distance if distance else 1.
                    eligible = distance > 0 and fraction <= config['evaluation']['maximum_unknown_distance_fraction']
                    target = 15*len(run); components += 1
                    writer.writerow({'trip_id': tid, 'first_gap': run[0][0], 'last_gap': run[-1][0],
                        'raw_elapsed_s': target, 'distance_m': distance, 'static_eta_s': estimates['static'],
                        'bucket_eta_s': estimates['bucket'], 'unknown_distance_fraction': fraction, 'scored': eligible})
                    if eligible:
                        scored_trips.add(tid)
                        for name, prediction in estimates.items():
                            error = prediction-target; metric = metrics[name]
                            metric['n'] += 1; metric['absolute'] += abs(error); metric['squared'] += error*error
                    else:
                        exclusions['insufficient_profile_coverage_components'] += 1
    return {'status': 'SAVED_HELDOUT_COMPONENT_EVALUATION', 'components_considered': components,
        'holdout_parents_with_observations': len(trips), 'scored_parents': len(scored_trips),
        'metrics': {name: {'n': m['n'], 'mae_s': m['absolute']/m['n'] if m['n'] else None,
            'rmse_s': math.sqrt(m['squared']/m['n']) if m['n'] else None} for name, m in metrics.items()},
        'exclusions': dict(exclusions), 'holdout_excluded_from_profiles': True,
        'target': '15 seconds times the count of contiguous fully retained original GPS gaps',
        'bucket_policy': 'fixed component departure bucket; no holdout passage-time lookahead',
        'limitation': 'QA-retained in-region components only, not full-trip accuracy, independent congestion labels or realized route savings'}


def report(work, plan, config):
    """Rebuild checksummed train evidence; prepare a review candidate, never activate it."""
    _, _, cutoff = validate_plan(plan); work = Path(work)
    network = RoadNetwork.load(work/'graph')
    matching = json.loads((work/'matching_summary.json').read_text(encoding='utf-8'))
    if matching['identity']['code'] != code_identity() or matching['identity']['config'] != config:
        raise ValueError('Report code/config differs from matching')
    deadline = time.monotonic()+plan['report_timeout_seconds']
    guard = lambda: guard_resources(work, plan, deadline, check_disk=False)
    db = open_evidence(work/'region_evidence.sqlite')
    try:
        with db:
            db.execute('DELETE FROM evidence'); db.execute('DELETE FROM applied')
        for folder in sorted((work/'region_batches').iterdir()):
            if folder.name.startswith('.'):
                continue
            guard(); metadata = verify_checkpoint(folder)
            if metadata['identity'] != matching['identity']:
                raise ValueError('Report batch identity differs')
            rows = pq.ParquetFile(folder/'observations.parquet').read().to_pylist()
            apply_observations(db, folder.name, rows, network, cutoff)
        profiles = disk_profiles(db, network, config, cutoff, check=guard)
    finally:
        db.close()
    coverage = coverage_report(network, profiles, plan['reference_coverage_fraction'])
    core, _, _, _ = region_geometry(plan)
    total = sum(e.metric_geometry.intersection(core).length for e in network.edges.values())
    for key, row in coverage['buckets'].items():
        day, bucket = key.split('/')
        known = {p['edge_id'] for p in profiles if p['day_group'] == day and p['time_bucket'] == bucket and p['status'] != 'unknown'}
        row['known_length_fraction'] = sum(network.edges[e].metric_geometry.intersection(core).length for e in known)/total
    coverage['denominator'] = 'positive-length directed edges in the exact 100 km2 metric square; lengths clipped to square'
    coverage['target_role'] = 'reference only; not an export gate or matching stop'
    # Existing app compatibility is useful for review, but activation remains explicit.
    output = work/'review_export'; output.mkdir(exist_ok=True)
    network.save(output/'graph')
    write_profiles(output/'congestion_profiles.parquet', profiles)
    write_json(output/'pipeline_config.json', config)
    write_json(output/'traffic.geojson', serve_geojson(network, profiles))
    write_json(output/'coverage.json', coverage['buckets'])
    write_json(output/'coverage_report.json', coverage)
    evaluation = evaluate_saved_holdout(work, output, network, profiles, config, cutoff, guard)
    write_json(output/'evaluation.json', evaluation)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axis = plt.subplots(figsize=(12, 4), layout='constrained')
    keys = list(coverage['buckets'])
    axis.bar(keys, [coverage['buckets'][k]['known_edge_fraction']*100 for k in keys])
    axis.set_ylabel('Supported directed edges (%)'); axis.set_ylim(0, 100); axis.tick_params(axis='x', rotation=60)
    fig.savefig(output/'diagnostics.png', dpi=130); plt.close(fig)
    metadata = {'run_id': digest(matching['identity'])[:20], 'stage': 'REGION_10KM_FULL_SOURCE_REVIEW',
                'data_kind': 'SYNTHETIC' if matching['identity']['source']['synthetic'] else 'REAL_INPUT_UNVERIFIED_PROVENANCE',
                'graph_version': network.graph_version, 'cutoff_utc': cutoff.isoformat(),
                'status': 'CANDIDATE_PENDING_MANUAL_QC_AND_HOLDOUT_REVIEW',
                'matching_complete': matching['all_eligible_complete'],
                'outputs_sha256': {p.relative_to(output).as_posix(): sha256_file(p) for p in output.rglob('*') if p.is_file() and p.name != 'run_metadata.json'}}
    write_json(output/'run_metadata.json', metadata)
    result = {'status': metadata['status'], 'matching_complete': matching['all_eligible_complete'],
              'coverage': coverage, 'evaluation': evaluation,
              'candidate_export': str(output), 'automatic_app_update': False}
    atomic_json(work/'result_summary.json', result)
    return result
