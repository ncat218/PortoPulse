"""Resumable report-only recovery from immutable PortoFlow directory/Output ZIP.

The original portoflow package stays byte-for-byte unchanged. No raw scan,
OSM fetch, native matching, threshold change, or app activation occurs here.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sqlite3
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path, PurePosixPath
from statistics import median

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from shapely.geometry import mapping

from portoflow import pipeline as original
from portoflow.congestion import parse_maxspeed, quantile, validate_rules
from portoflow.export import COLORS, write_json, write_profiles
from portoflow.graph import RoadNetwork
from portoflow.profiles import _stats, coverage_report
from portoflow.state import digest, guard_resources
from portoflow.storage import sha256_file

VERSION = 'REPORT_RECOVERY_V1'
FILES = {'observations.parquet', 'parents.json', 'review_cases.json'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.'+path.name+'.tmp')
    temporary.write_bytes(data); os.replace(temporary, path)


def json_atomic(path, value):
    atomic(path, (json.dumps(value, default=str, allow_nan=False, indent=2)+'\n').encode())


class Source:
    """Read only required members; never unpack the multi-GB saved Output."""
    def __init__(self, path):
        self.path = Path(path).resolve(); self.archive = None; self.trusted_cache = False
        if self.path.is_file():
            self.archive = zipfile.ZipFile(self.path)
            names = self.archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError('Duplicate archive members')
            roots = []
            for name in names:
                parts = PurePosixPath(name).parts
                if any((p.startswith('.') and p != '.') or p in {'test_tmp', 'native_probe','report_recovery_synthetic_tests'} for p in parts):
                    continue
                if name.endswith('/matching_summary.json') or name == 'matching_summary.json':
                    prefix = name[:-len('matching_summary.json')]
                    if prefix+'graph/graph_metadata.json' in names:
                        roots.append(prefix)
            preferred = [r for r in roots if r.rstrip('/').endswith('portoflow_run')]
            roots = preferred or roots
            if len(roots) != 1:
                raise ValueError('Select the original PortoFlow Output archive with one real run')
            self.prefix = roots[0]
            self.members = {name[len(self.prefix):]: self.archive.getinfo(name)
                            for name in names if name.startswith(self.prefix)}
            self.ids = sorted({p.split('/')[1] for p in self.members
                               if p.startswith('region_batches/') and p.endswith('/run_metadata.json')
                               and not p.split('/')[1].startswith('.')},
                              key=lambda bid: self.members['region_batches/'+bid+'/observations.parquet'].header_offset)
        else:
            if not (self.path/'matching_summary.json').is_file():
                roots = [p.parent for p in self.path.rglob('matching_summary.json')
                         if p.parent.name == 'portoflow_run']
                if len(roots) != 1:
                    raise ValueError('Select the saved portoflow_run directory or its Output ZIP')
                self.path = roots[0]
            self.ids = sorted(p.name for p in (self.path/'region_batches').iterdir()
                              if p.is_dir() and not p.name.startswith('.'))
        if not self.ids:
            raise ValueError('No committed matching batches in saved Output')

    def read(self, relative):
        parts = PurePosixPath(relative)
        if parts.is_absolute() or '..' in parts.parts or '\\' in relative:
            raise ValueError('Unsafe source member')
        if self.archive:
            info = self.members[relative]
            if info.file_size > 512*1024**2:
                raise ValueError('Single report input exceeds 512 MiB bound')
            return self.archive.read(info)  # zipfile also checks each member CRC.
        path = (self.path/relative).resolve()
        if not path.is_relative_to(self.path):
            raise ValueError('Source path escapes run directory')
        return path.read_bytes()

    def close(self):
        if self.archive:
            self.archive.close()


def open_ledger(path, identity):
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=DELETE')
    db.execute('PRAGMA temp_store=FILE')
    db.execute('PRAGMA cache_size=-131072')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS recovery_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS verified_batches(batch TEXT PRIMARY KEY,receipt TEXT NOT NULL,
            train INTEGER,holdout INTEGER);
        CREATE TABLE IF NOT EXISTS verified_parents(trip TEXT PRIMARY KEY,split TEXT,batch TEXT,
            complete INTEGER,accepted INTEGER);
        CREATE TABLE IF NOT EXISTS evidence(trip_id TEXT,taxi_id INTEGER,edge_id TEXT,local_date TEXT,
            day_group TEXT,bucket TEXT,distance REAL,duration REAL,complete INTEGER,highway TEXT,
            PRIMARY KEY(trip_id,edge_id,local_date,day_group,bucket));
    ''')
    fingerprint = digest(identity)
    previous = db.execute("SELECT value FROM recovery_meta WHERE key='identity'").fetchone()
    if previous and previous[0] != fingerprint:
        raise ValueError('Recovery cache belongs to another source/code/config')
    if not previous:
        db.execute("INSERT INTO recovery_meta VALUES ('identity',?)", (fingerprint,)); db.commit()
    return db


def aggregate(table, network, cutoff, parents):
    """Same Python summation order and keys as the original apply_observations.

    Arrow filters before Python decoding, avoids datetime conversion for every
    observation, and executemany below replaces row-by-row indexed inserts.
    """
    links = table.select(['trip_id', 'split']).to_pydict()
    allowed = {row['trip_id']: row['split'] for row in parents}
    if any(allowed.get(tid) != split for tid, split in zip(links['trip_id'], links['split'])):
        raise ValueError('Observation parent/split mismatch')
    accepted_ids = table.filter(pc.equal(table['quality_flag'], 'accepted_inferred'))['trip_id'].to_pylist()
    actual_counts = Counter(accepted_ids)
    if any(row['accepted_observations'] != actual_counts[row['trip_id']] for row in parents):
        raise ValueError('Saved accepted-observation count differs from Parquet')
    train = pc.equal(table['split'], 'train')
    invalid = pc.or_(pc.greater_equal(table['estimated_exit_utc'],
        pa.scalar(cutoff, type=table.schema.field('estimated_exit_utc').type)),
        pc.not_equal(table['graph_version'], network.graph_version))
    if pc.any(pc.and_(train, invalid)).as_py():
        raise ValueError('Temporal leakage or graph mismatch')
    mask = pc.and_(train, pc.equal(table['quality_flag'], 'accepted_inferred'))
    names = ['trip_id', 'taxi_id', 'edge_id', 'local_date', 'day_group', 'time_bucket',
             'complete_trip_evidence', 'traveled_distance_m', 'observed_or_inferred_duration_s']
    selected = table.select(names).filter(mask)
    selected = selected.set_column(3, 'local_date', pc.cast(selected['local_date'], pa.string()))
    columns = selected.to_pydict(); grouped = {}
    for tid, taxi, eid, day, group, bucket, complete, distance, duration in zip(*(columns[n] for n in names)):
        key = (tid, taxi, eid, day, group, bucket, int(complete), network.edges[eid].highway)
        if key not in grouped:
            grouped[key] = [0., 0.]
        grouped[key][0] += distance; grouped[key][1] += duration
    return [(tid, taxi, eid, day, group, bucket, distance, duration, complete, highway)
            for (tid, taxi, eid, day, group, bucket, complete, highway), (distance, duration) in grouped.items()]


def ingest(source, db, network, matching, cutoff, guard):
    cached = db.execute("SELECT value FROM recovery_meta WHERE key='ingest_complete'").fetchone()
    if source.trusted_cache and cached:
        print('INGEST cache verified by ledger SHA + full immutable Output ZIP SHA; no batch replay',flush=True)
        return json.loads(cached[0])
    completed = 0
    for bid in source.ids:
        guard()
        previous = db.execute('SELECT receipt FROM verified_batches WHERE batch=?', (bid,)).fetchone()
        if source.trusted_cache and previous:
            completed += 1
            continue
        base = 'region_batches/'+bid+'/'
        manifest_bytes = source.read(base+'run_metadata.json')
        metadata = json.loads(manifest_bytes)
        if metadata['identity'] != matching['identity'] or set(metadata['outputs_sha256']) != FILES:
            raise ValueError('Batch identity or file set differs: '+bid)
        # Always verify source bytes. Already imported batches are not decoded or reinserted.
        files = {name: source.read(base+name) for name in FILES}
        hashes = {name: sha(data) for name, data in files.items()}
        if hashes != metadata['outputs_sha256']:
            raise ValueError('Batch checksum differs: '+bid)
        receipt = digest([sha(manifest_bytes), hashes])
        if previous:
            if previous[0] != receipt:
                raise ValueError('Committed batch changed: '+bid)
        else:
            parents = json.loads(files['parents.json'])
            ids = [row['trip_id'] for row in parents]
            if len(ids) != len(set(ids)) or bid != digest([matching['identity'], ids])[:24]:
                raise ValueError('Batch parent IDs/name differ')
            if any(row['split'] not in {'train', 'holdout'} for row in parents):
                raise ValueError('Unknown parent split')
            table = pq.ParquetFile(pa.BufferReader(files['observations.parquet'])).read()
            rows = aggregate(table, network, cutoff, parents)
            counts = Counter(row['split'] for row in parents)
            with db:
                # One original parent may appear in only one committed batch.
                db.executemany('INSERT INTO verified_parents VALUES (?,?,?,?,?)',
                    [(row['trip_id'], row['split'], bid, int(row['whole_parent_complete']), row['accepted_observations']) for row in parents])
                db.executemany('INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
                db.execute('INSERT INTO verified_batches VALUES (?,?,?,?)',
                           (bid, receipt, counts['train'], counts['holdout']))
        completed += 1
        if files['review_cases.json'].strip() != b'[]' and len(files['review_cases.json']) <= 16*1024**2:
            atomic(guard.work/'review_cases'/(bid+'.json'), files['review_cases.json'])
        if completed % 100 == 0 or completed == len(source.ids):
            print(f'INGEST verified {completed}/{len(source.ids)} batches | committed ledger preserved', flush=True)
    counts = dict(db.execute('SELECT split,COUNT(*) FROM verified_parents GROUP BY split'))
    if any(counts.get(s, 0) != matching['completed_parents'].get(s, 0) for s in ('train', 'holdout')):
        raise ValueError('Verified original parent counts differ from matching summary')
    if db.execute('SELECT COUNT(*) FROM verified_batches').fetchone()[0] != len(source.ids):
        raise ValueError('Recovery ledger contains batches absent from this saved Output')
    for name, expression in [('evidence_edge', 'edge_id'), ('evidence_night', 'highway,bucket')]:
        guard(); print('INDEX', name, flush=True)
        db.set_progress_handler(lambda: int(time.monotonic() >= guard.deadline), 100000)
        try:
            db.execute(f'CREATE INDEX IF NOT EXISTS {name} ON evidence({expression})'); db.commit()
        except sqlite3.OperationalError as exc:
            if 'interrupt' in str(exc).lower():
                raise TimeoutError('Index budget reached; imported batches remain committed') from exc
            raise
        finally:
            db.set_progress_handler(None, 0)
    key=digest(list(db.execute('SELECT batch,receipt FROM verified_batches ORDER BY batch')))
    with db:
        db.execute("INSERT OR REPLACE INTO recovery_meta VALUES ('ingest_complete',?)",(json.dumps(key),))
    return key


def cached_profiles(db, root, network, config, cutoff, key, guard, chunk_size=200):
    """Unchanged original formula; checkpoint night references and every edge chunk."""
    root.mkdir(parents=True, exist_ok=True)
    rules = config['profile_rules']; validate_rules(rules)
    adequate = lambda counts: all(counts[k] >= rules['min_'+k] for k in counts)
    cache = root/'night.json'
    state = json.loads(cache.read_text()) if cache.is_file() else {'key': key, 'night': {}}
    if state['key'] != key:
        raise ValueError('Night-reference cache identity differs')
    night = state['night']
    for highway in sorted({e.highway for e in network.edges.values()}):
        if highway in night:
            continue
        guard()
        speeds, counts = _stats(db.execute('SELECT trip_id,taxi_id,local_date,day_group,bucket,distance,duration '
            "FROM evidence WHERE highway=? AND bucket='00-06'", (highway,)))
        night[highway] = quantile(speeds, .85) if speeds and adequate(counts) else None
        json_atomic(cache, state)
    edges = list(network.edges.values()); result = []
    for offset in range(0, len(edges), chunk_size):
        guard(); part = root/f'profiles-{offset:06d}.parquet'; manifest = part.with_suffix('.json')
        selected = edges[offset:offset+chunk_size]
        if manifest.is_file():
            saved = json.loads(manifest.read_text())
            if saved['key'] != key or saved['edges'] != [e.edge_id for e in selected] or sha256_file(part) != saved['sha256']:
                raise ValueError('Profile chunk identity/checksum differs')
            profiles = pq.ParquetFile(part).read().to_pylist()
        else:
            profiles = []
            for edge in selected:
                guard()
                rows = db.execute('SELECT trip_id,taxi_id,local_date,day_group,bucket,distance,duration '
                                  'FROM evidence WHERE edge_id=?', (edge.edge_id,)).fetchall()
                speeds, counts = _stats(rows)
                static = median(speeds) if speeds and adequate(counts) else None
                if speeds and adequate(counts):
                    reference, reference_source = quantile(speeds, .85), 'edge_p85'
                elif night[edge.highway] is not None:
                    reference, reference_source = night[edge.highway], 'class_night_p85'
                else:
                    reference = parse_maxspeed(edge.maxspeed_raw)
                    reference_source = 'maxspeed_weak_proxy' if reference else None
                groups = defaultdict(list)
                for row in rows:
                    groups[(row[3], row[4])].append(row)
                for group in ('weekday', 'weekend'):
                    for start, end in zip(config['time']['bucket_boundaries_hour'], config['time']['bucket_boundaries_hour'][1:]):
                        bucket = f'{start:02d}-{end:02d}'
                        values, support = _stats(groups[(group, bucket)])
                        speed = median(values) if values else None
                        status, confidence, slowdown = 'unknown', 'insufficient', None
                        if speed is not None and reference is not None and reference > 0 and adequate(support):
                            ratio = speed/reference
                            status = ('high_slowdown' if ratio < rules['high_slowdown_ratio_threshold'] else
                                      'slow' if ratio < rules['slow_ratio_threshold'] else 'normal')
                            confidence = 'weak_reference' if reference_source == 'maxspeed_weak_proxy' else 'supported_uncalibrated'
                            slowdown = max(0., 1-ratio)
                        profiles.append({'edge_id': edge.edge_id, 'day_group': group, 'time_bucket': bucket,
                            'median_speed_kmh': speed, 'reference_speed_kmh': reference, 'reference_source': reference_source,
                            'static_speed_kmh': static, 'slowdown_ratio': slowdown, **support, 'confidence': confidence,
                            'status': status, 'graph_version': network.graph_version, 'train_cutoff': cutoff})
            temporary = part.with_suffix('.tmp'); write_profiles(temporary, profiles); os.replace(temporary, part)
            json_atomic(manifest, {'key': key, 'edges': [e.edge_id for e in selected], 'sha256': sha256_file(part)})
        result.extend(profiles)
        print(f'PROFILES {min(offset+chunk_size,len(edges))}/{len(edges)} edges | 12 buckets', flush=True)
    return result


def cached_evaluation(source, db, work, output, network, profiles, config, cutoff, key, guard):
    """Run the frozen original evaluator per holdout-containing batch, with cache."""
    cache = work/'evaluation_cache'/key[:20]; cache.mkdir(parents=True,exist_ok=True)
    scratch = work/'evaluation_scratch'; scratch.mkdir(exist_ok=True)
    lookup = original.profile_lookup(profiles, network.graph_version)
    original_lookup = original.profile_lookup
    bids = [r[0] for r in db.execute('SELECT batch FROM verified_batches WHERE holdout>0 ORDER BY batch')]
    summaries = []; csv_files = []
    try:
        original.profile_lookup = lambda p, v: lookup if v == network.graph_version else original_lookup(p, v)
        for index, bid in enumerate(bids):
            guard(); destination = cache/bid; manifest = destination/'receipt.json'
            if manifest.is_file():
                saved = json.loads(manifest.read_text())
                if saved['key'] != key or sha256_file(destination/'holdout_components.csv') != saved['csv_sha256']:
                    raise ValueError('Evaluation cache changed')
                summary = saved['summary']
            else:
                # Only one small batch is materialized, never the whole 5+GB Output.
                batch_work = scratch/bid
                directory = batch_work/'region_batches'/bid; directory.mkdir(parents=True,exist_ok=True)
                data = source.read('region_batches/'+bid+'/observations.parquet')
                metadata = json.loads(source.read('region_batches/'+bid+'/run_metadata.json'))
                if sha(data) != metadata['outputs_sha256']['observations.parquet']:
                    raise ValueError('Evaluation input checksum differs')
                atomic(directory/'observations.parquet', data)
                stage = cache/('.'+bid+'.tmp'); stage.mkdir(exist_ok=True)
                summary = original.evaluate_saved_holdout(batch_work, stage, network, profiles, config, cutoff, guard)
                json_atomic(stage/'receipt.json', {'key': key, 'summary': summary,
                    'csv_sha256': sha256_file(stage/'holdout_components.csv')})
                os.replace(stage, destination)
                (directory/'observations.parquet').unlink(); directory.rmdir()
            summaries.append(summary); csv_files.append(destination/'holdout_components.csv')
            if (index+1) % 100 == 0 or index+1 == len(bids):
                print(f'EVALUATION {index+1}/{len(bids)} holdout batches | train-only batches skipped', flush=True)
    finally:
        original.profile_lookup = original_lookup
    # CSV round-trips preserve Python float values; common-cohort sums retain lexical batch order.
    metrics = {name: {'n': 0, 'absolute': 0., 'squared': 0.} for name in ('static', 'bucket')}
    fields = ['trip_id','first_gap','last_gap','raw_elapsed_s','distance_m','static_eta_s',
              'bucket_eta_s','unknown_distance_fraction','scored']
    merged = output/'holdout_components.csv'; temporary = merged.with_suffix('.tmp')
    with temporary.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for path in csv_files:
            guard()
            with path.open(newline='', encoding='utf-8') as part:
                for row in csv.DictReader(part):
                    writer.writerow(row)
                    if row['scored'] == 'True':
                        target = float(row['raw_elapsed_s'])
                        for name, m in metrics.items():
                            error = float(row[name+'_eta_s'])-target
                            m['n'] += 1; m['absolute'] += abs(error); m['squared'] += error*error
    os.replace(temporary, merged)
    exclusions = Counter()
    for item in summaries:
        exclusions.update(item['exclusions'])
    return {'status': 'SAVED_HELDOUT_COMPONENT_EVALUATION',
        'components_considered': sum(s['components_considered'] for s in summaries),
        'holdout_parents_with_observations': sum(s['holdout_parents_with_observations'] for s in summaries),
        'scored_parents': sum(s['scored_parents'] for s in summaries),
        'metrics': {name: {'n': m['n'], 'mae_s': m['absolute']/m['n'] if m['n'] else None,
            'rmse_s': math.sqrt(m['squared']/m['n']) if m['n'] else None} for name,m in metrics.items()},
        'exclusions': dict(exclusions), 'holdout_excluded_from_profiles': True,
        'target': '15 seconds times contiguous fully retained original GPS gaps',
        'bucket_policy': 'fixed component departure bucket; no passage-time lookahead',
        'limitation': 'QA-retained in-region components only; not full-trip accuracy or realized route savings'}


class Guard:
    def __init__(self, work, plan, seconds):
        self.work, self.plan = work, plan
        self.deadline = time.monotonic()+seconds
        self.last_disk_check = 0.
    def __call__(self):
        now = time.monotonic(); disk = now-self.last_disk_check > 30
        guard_resources(self.work, self.plan, self.deadline, check_disk=disk)
        if disk:
            self.last_disk_check = now


def recover(source_path, work, seconds=5400):
    if type(seconds) is not int or not 1 <= seconds <= 5400:
        raise ValueError('Report recovery budget must be finite, at most 5400 seconds')
    work = Path(work).resolve(); work.mkdir(parents=True, exist_ok=True)
    source = Source(source_path); phase = 'verify_source'
    try:
        matching = json.loads(source.read('matching_summary.json'))
        computed_complete=all(matching['completed_parents'].get(s,0)==matching['expected_parents'].get(s,0)
                              for s in ('train','holdout'))
        if computed_complete != matching['all_eligible_complete']:
            raise ValueError('Saved matching completion flag disagrees with its parent counts')
        identity = matching['identity']; plan = identity['plan']; config = identity['config']
        original.validate_plan(plan)
        if identity['code'] != original.code_identity():
            raise ValueError('Frozen matching source bytes differ; use the dedicated recovery code Dataset')
        if identity['runtime'] != {name: original.version(name) for name in identity['runtime']}:
            raise ValueError('Scientific library versions differ from saved matching')
        cutoff = datetime.fromisoformat(plan['train_cutoff_utc'].replace('Z', '+00:00'))
        guard = Guard(work, plan, seconds)
        snapshot_sha=None
        if source.archive:
            print('VERIFY original Output ZIP SHA256 sequentially; no extraction',flush=True)
            snapshot_sha=sha256_file(source.path)
            guard()
        graph_root = work/'graph'; graph_root.mkdir(exist_ok=True)
        graph_metadata = json.loads(source.read('graph/graph_metadata.json'))
        for name, expected in graph_metadata['sha256'].items():
            if '/' in name or '\\' in name:
                raise ValueError('Unexpected graph member')
            data = source.read('graph/'+name)
            if sha(data) != expected:
                raise ValueError('Original graph checksum differs')
            if not (graph_root/name).is_file() or sha256_file(graph_root/name) != expected:
                atomic(graph_root/name, data)
        atomic(graph_root/'graph_metadata.json', source.read('graph/graph_metadata.json'))
        network = RoadNetwork.load(graph_root)
        if network.graph_version != identity['core_graph']:
            raise ValueError('Matching and graph identities differ')
        recovery_identity = {'version': VERSION, 'matching': identity,
                             'recovery_script_sha256': sha256_file(Path(__file__))}
        json_atomic(work/'source_receipt.json', {'source': str(source.path), 'matching_summary_sha256': sha(source.read('matching_summary.json')),
            'source_zip_sha256':snapshot_sha,
            'core_graph_version':identity['core_graph'],'context_graph_version':identity['context_graph'],
            'frozen_matching_code':identity['code'],'scientific_config':config,'plan':plan,'runtime':identity['runtime'],
            'recovery_script_sha256':recovery_identity['recovery_script_sha256'],
            'matching_complete': matching['all_eligible_complete'], 'expected_parents': matching['expected_parents'],
            'matched_parents': matching['completed_parents'], 'committed_batches': len(source.ids),
            'raw_scan_performed': False, 'native_matching_performed': False})
        print('SAVED MATCHING:', matching['completed_parents'], '| all eligible complete:', matching['all_eligible_complete'], flush=True)
        ledger=work/'recovery_evidence.sqlite'; checkpoint=work/'ledger_checkpoint.json'
        source.trusted_cache=False
        if ledger.is_file():
            if not checkpoint.is_file():
                raise ValueError('Unsealed recovery cache from a hard interruption; retain it and use a fresh report cache. Original matching is intact.')
            saved=json.loads(checkpoint.read_text())
            if saved['identity']!=digest(recovery_identity) or saved['ledger_sha256']!=sha256_file(ledger):
                raise ValueError('Recovery ledger checkpoint identity/checksum differs; do not trust this cache')
            source.trusted_cache=snapshot_sha is not None and saved.get('source_zip_sha256')==snapshot_sha
        db = open_ledger(ledger, recovery_identity)
        try:
            phase = 'ingest'; ledger_key = ingest(source, db, network, matching, cutoff, guard)
            phase = 'profiles'; key = digest([recovery_identity, ledger_key])
            profiles = cached_profiles(db, work/'profile_cache'/key[:20], network, config, cutoff, key, guard)
            phase = 'coverage'; coverage = coverage_report(network, profiles, plan['reference_coverage_fraction'])
            core, _, _, _ = original.region_geometry(plan)
            lengths = {eid: edge.metric_geometry.intersection(core).length for eid,edge in network.edges.items()}
            total_length = sum(lengths.values())
            for label, bucket in coverage['buckets'].items():
                day, hour = label.split('/')
                bucket['known_length_fraction'] = sum(lengths[p['edge_id']] for p in profiles
                    if p['day_group']==day and p['time_bucket']==hour and p['status']!='unknown')/total_length
            coverage['denominator'] = 'fixed directed edges with positive length in the exact 100 km2 square'
            coverage['target_role'] = 'reference only; unchanged scientific classification rules'
            json_atomic(work/'coverage_report.json', coverage)
            output = work/'candidate_export'; output.mkdir(exist_ok=True)
            phase = 'evaluation'; evaluation = cached_evaluation(source, db, work, output, network, profiles, config, cutoff, key, guard)
            json_atomic(work/'evaluation.json', evaluation)
            phase = 'export'; guard()
            target_graph = output/'graph'; target_graph.mkdir(exist_ok=True)
            for path in graph_root.iterdir():
                shutil.copyfile(path, target_graph/path.name)
            write_profiles(output/'congestion_profiles.parquet', profiles)
            write_json(output/'pipeline_config.json', config)
            write_json(output/'coverage.json', coverage['buckets'])
            write_json(output/'coverage_report.json', coverage)
            write_json(output/'evaluation.json', evaluation)
            geo = output/'traffic.geojson'; temporary = geo.with_suffix('.tmp')
            with temporary.open('w', encoding='utf-8') as stream:
                stream.write('{"type":"FeatureCollection","features":[')
                for index, row in enumerate(profiles):
                    if index % 1000 == 0:
                        guard()
                    properties = {k:v for k,v in row.items() if k!='train_cutoff'}
                    properties.update(color=COLORS[row['status']], highway=network.edges[row['edge_id']].highway)
                    feature = {'type':'Feature','geometry':mapping(network.edges[row['edge_id']].geometry),'properties':properties}
                    if index:
                        stream.write(',')
                    stream.write(json.dumps(feature, allow_nan=False, separators=(',',':')))
                stream.write(']}')
            os.replace(temporary, geo)
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(12,4),layout='constrained')
            ax.bar(list(coverage['buckets']), [b['known_edge_fraction']*100 for b in coverage['buckets'].values()])
            ax.set(ylim=(0,100),ylabel='Supported directed edges (%)'); ax.tick_params(axis='x',rotation=60)
            fig.savefig(output/'diagnostics.png',dpi=130); plt.close(fig)
            manifest = {'run_id':digest([identity,VERSION,ledger_key])[:20], 'graph_version':network.graph_version,
                'cutoff_utc':cutoff.isoformat(), 'data_kind':'SYNTHETIC' if identity['source']['synthetic'] else 'REAL_INPUT_UNVERIFIED_PROVENANCE',
                'status':'CANDIDATE_PENDING_MANUAL_QC_AND_HOLDOUT_REVIEW', 'matching_complete':matching['all_eligible_complete'],
                'outputs_sha256':{p.relative_to(output).as_posix():sha256_file(p) for p in output.rglob('*')
                                  if p.is_file() and p.name!='run_metadata.json' and p.suffix!='.tmp'}}
            write_json(output/'run_metadata.json',manifest)
            json_atomic(work/'candidate_manifest.json',manifest)
            result = {'status':'REPORT_RECOVERY_COMPLETE','postprocessing_complete':True,
                'matching_complete':matching['all_eligible_complete'],'matched_parents':matching['completed_parents'],
                'expected_parents':matching['expected_parents'],'coverage':coverage,'evaluation':evaluation,
                'verified_batch_count':len(source.ids),'ledger_receipt_sha256':ledger_key,
                'parent_qc_counts':{s:{'whole_parent_complete':n,'parents_with_accepted_core_observations':a}
                    for s,n,a in db.execute('SELECT split,SUM(complete),SUM(accepted>0) FROM verified_parents GROUP BY split')},
                'candidate_export':str(output),'native_matching_performed':False,'raw_scan_performed':False}
            json_atomic(work/'result_summary.json',result)
            print('REPORT_RECOVERY_COMPLETE | native matching calls: 0',flush=True)
            return result
        finally:
            db.close()
            # Seal only our committed cache, never the legacy mutable report DB.
            json_atomic(checkpoint,{'identity':digest(recovery_identity),'ledger_sha256':sha256_file(ledger),
                                    'source_zip_sha256':snapshot_sha})
    except TimeoutError:
        result = {'status':'REPORT_RECOVERY_PARTIAL','phase':phase,'postprocessing_complete':False,
                  'native_matching_performed':False,'raw_scan_performed':False,
                  'resume':'Retain this recovery Output and resume its cache; keep the original matching Output attached'}
        json_atomic(work/'result_summary.json',result)
        print('REPORT_RECOVERY_PARTIAL | phase:',phase,'| committed progress preserved',flush=True)
        return result
    except Exception as exc:
        json_atomic(work/'result_summary.json',{'status':'REPORT_RECOVERY_FAILED','phase':phase,
            'postprocessing_complete':False,'error':str(exc),'native_matching_performed':False,
            'raw_scan_performed':False,'original_matching_preserved':True})
        raise
    finally:
        source.close()


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--budget-seconds',type=int,default=5400)
    args=parser.parse_args()
    print(json.dumps(recover(args.source,args.work,args.budget_seconds),default=str,indent=2),flush=True)
