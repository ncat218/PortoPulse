"""Finish a V1 report from its sealed, already ingested ledger, read-only.

The original matching Output AND the saved failed recovery Output are inputs.
Only the latter's SQLite member is staged (in bounded temporary storage) when
Kaggle supplies an archive. Large ledgers are never copied into saved Output.
"""
import argparse
import json
import os
import shutil
import sqlite3
import time
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path, PurePosixPath

import report_recovery as v1

GiB = 1024**3
V1_SCRIPT_SHA = 'c24d11ad11917b2bee742e8eb114aaf51b42c69cc2127ec4c355f5a1eb254263'
EXCLUDED = {'test_tmp', 'native_probe', 'report_recovery_synthetic_tests', 'report_continue_synthetic_tests'}
SCRATCH_CAP = 24*GiB
OUTPUT_CAP = 2*GiB
RESERVE = GiB


class StorageBlocked(OSError):
    pass


class SavedCache:
    def __init__(self, path):
        self.path = Path(path).resolve(); self.archive = None
        if self.path.is_file():
            self.archive = zipfile.ZipFile(self.path)
            names = self.archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError('Duplicate saved cache archive members')
            roots = [n[:-len('ledger_checkpoint.json')] for n in names
                     if n.endswith('portoflow_recovery/ledger_checkpoint.json')
                     and not EXCLUDED.intersection(PurePosixPath(n).parts)]
            roots = [r for r in roots if r+'recovery_evidence.sqlite' in names and r+'source_receipt.json' in names]
            if len(roots) != 1:
                raise ValueError('Select the saved FAILED RECOVERY Output containing its ledger checkpoint')
            self.prefix = roots[0]
        else:
            if not (self.path/'ledger_checkpoint.json').is_file():
                roots = [p.parent for p in self.path.rglob('ledger_checkpoint.json')
                         if p.parent.name == 'portoflow_recovery' and not EXCLUDED.intersection(p.parts)]
                if len(roots) != 1:
                    raise ValueError('Select the saved FAILED RECOVERY Output directory')
                self.path = roots[0]

    def read_json(self, name):
        if self.archive:
            info = self.archive.getinfo(self.prefix+name)
            if info.file_size > 16*1024**2:
                raise ValueError('Unexpected oversized recovery metadata')
            return json.loads(self.archive.read(info))
        return json.loads((self.path/name).read_text(encoding='utf-8'))

    def ledger_size(self):
        if self.archive:
            return self.archive.getinfo(self.prefix+'recovery_evidence.sqlite').file_size
        return (self.path/'recovery_evidence.sqlite').stat().st_size

    def close(self):
        if self.archive:
            self.archive.close()


def find_cache(input_root):
    """Select the real recovery, ignoring synthetic tests and the review ZIP."""
    root = Path(input_root)
    candidates = [p.parent for p in root.rglob('ledger_checkpoint.json')
                  if p.parent.name == 'portoflow_recovery' and
                  not EXCLUDED.intersection(p.relative_to(root).parts)]
    if not candidates:
        for path in root.rglob('*.zip'):
            if EXCLUDED.intersection(path.relative_to(root).parts):
                continue
            try:
                with closing(SavedCache(path)):
                    candidates.append(path)
            except (ValueError, zipfile.BadZipFile, KeyError):
                continue
    if len(candidates) != 1:
        raise ValueError('Attach the FAILED RECOVERY Notebook Output as an Input; set CACHE explicitly if several exist')
    return candidates[0]


def tree_bytes(root):
    return sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file())


def storage_preflight(cache, scratch, work, *, free=None, output_free=None):
    scratch = Path(scratch); work = Path(work)
    scratch.mkdir(parents=True, exist_ok=True); work.mkdir(parents=True, exist_ok=True)
    ledger_bytes = cache.ledger_size()
    if cache.archive and (scratch.resolve() == work.resolve() or scratch.resolve().is_relative_to(work.resolve())
                          or scratch.as_posix().startswith('/kaggle/working/')):
        raise ValueError('Large ledger scratch must be outside the saved report Output')
    available = shutil.disk_usage(scratch).free if free is None else free
    output_available = (shutil.disk_usage(work).free if free is None else free) if output_free is None else output_free
    expected = cache.read_json('ledger_checkpoint.json')['ledger_sha256']
    staged = scratch/('ledger-'+expected[:20]+'.sqlite')
    already_staged = staged.is_file() and staged.stat().st_size == ledger_bytes
    required = (ledger_bytes if cache.archive and not already_staged else 0)+OUTPUT_CAP+RESERVE
    facts = {'ledger_bytes': ledger_bytes, 'ledger_in_archive': bool(cache.archive),
             'scratch_cap_bytes': SCRATCH_CAP, 'saved_report_cap_bytes': OUTPUT_CAP,
             'available_bytes': available, 'required_free_bytes': required,
             'saved_output_available_bytes': output_available,
             'large_ledger_copied_to_output': False}
    print('STORAGE PREFLIGHT:', json.dumps(facts), flush=True)
    if cache.archive and ledger_bytes > SCRATCH_CAP:
        raise StorageBlocked(f'Ledger needs {ledger_bytes/GiB:.2f} GiB temporary storage; finite cap is {SCRATCH_CAP/GiB:.0f} GiB. No report started.')
    if available < required:
        raise StorageBlocked(f'Need {required/GiB:.2f} GiB free including report reserve; have {available/GiB:.2f} GiB. No report started.')
    if output_available < OUTPUT_CAP+RESERVE:
        raise StorageBlocked(f'Saved Output needs 3 GiB free reserve; have {output_available/GiB:.2f} GiB. No report started.')
    if tree_bytes(work) > OUTPUT_CAP:
        raise StorageBlocked('Saved report Output already exceeds its 2 GiB cap; retain it and use a fresh WORK')
    return facts


class Guard(v1.Guard):
    def __init__(self, work, plan, seconds):
        # Operational cap only. Scientific plan/config/identity stay unchanged.
        super().__init__(work, dict(plan, max_output_gb=OUTPUT_CAP/GiB), seconds)
        self.last_disk_check = time.monotonic()

    def __call__(self):
        try:
            super().__call__()
        except OSError as exc:
            if 'Output disk ceiling' in str(exc):
                raise StorageBlocked('Saved report reached its finite 2 GiB cap; small caches retained') from exc
            raise


def stage_ledger(cache, scratch, expected, guard):
    if not cache.archive:
        ledger = cache.path/'recovery_evidence.sqlite'
        print('VERIFY sealed ledger SHA256; open mounted database read-only, no copy', flush=True)
        if v1.sha256_file(ledger) != expected:
            raise ValueError('Saved recovery ledger checkpoint checksum differs')
        guard()
        return ledger
    # A version-specific pathname prevents stale scratch from another input being reused.
    scratch = Path(scratch); ledger = scratch/('ledger-'+expected[:20]+'.sqlite')
    if ledger.is_file():
        if v1.sha256_file(ledger) != expected:
            raise ValueError('Temporary ledger checksum differs; retain original saved Input')
        return ledger
    temporary = ledger.with_suffix('.partial')
    if temporary.exists():
        # Only our exact unfinished extraction file is removed, never a saved Input.
        temporary.unlink()
    print('STAGE only sealed ledger to temporary storage; no whole-Output extraction', flush=True)
    checksum = v1.hashlib.sha256(); completed = 0; last_notice = 0.
    try:
        with cache.archive.open(cache.prefix+'recovery_evidence.sqlite') as source, temporary.open('xb') as target:
            while block := source.read(8*1024**2):
                guard(); target.write(block); checksum.update(block); completed += len(block)
                if completed > SCRATCH_CAP:
                    raise StorageBlocked('Temporary ledger extraction exceeded finite 24 GiB cap')
                if time.monotonic()-last_notice > 15:
                    last_notice = time.monotonic()
                    print(f'STAGE ledger {completed/GiB:.2f}/{cache.ledger_size()/GiB:.2f} GiB', flush=True)
                    if shutil.disk_usage(scratch).free < OUTPUT_CAP+RESERVE:
                        raise StorageBlocked('Free disk reached reserved space; stopped temporary extraction')
        if completed != cache.ledger_size() or checksum.hexdigest() != expected:
            raise ValueError('Saved recovery ledger checkpoint checksum differs')
        os.replace(temporary, ledger)
    except BaseException:
        if temporary.exists():
            temporary.unlink()
        raise
    return ledger


class CheckedCursor:
    def __init__(self, cursor, guard):
        self.cursor, self.guard = cursor, guard

    def __iter__(self):
        for index, row in enumerate(self.cursor):
            if index % 10000 == 0:
                self.guard()
            yield row

    def fetchall(self):
        return list(self)

    def fetchone(self):
        return self.cursor.fetchone()


class CheckedDB:
    def __init__(self, connection, guard):
        self.connection, self.guard = connection, guard

    def execute(self, sql, values=()):
        self.guard()
        return CheckedCursor(self.connection.execute(sql, values), self.guard)


def finish(source, db, work, graph_root, network, matching, key, ledger_key, config, cutoff, guard):
    identity = matching['identity']; plan = identity['plan']
    print('REUSE sealed INGEST_COMPLETE ledger | 0 batch imports | 0 index builds', flush=True)
    profiles = v1.cached_profiles(db, work/'profile_cache'/key[:20], network, config, cutoff, key, guard)
    coverage = v1.coverage_report(network, profiles, plan['reference_coverage_fraction'])
    core, _, _, _ = v1.original.region_geometry(plan)
    lengths = {eid: e.metric_geometry.intersection(core).length for eid,e in network.edges.items()}
    total_length = sum(lengths.values())
    for label, bucket in coverage['buckets'].items():
        day, hour = label.split('/')
        bucket['known_length_fraction'] = sum(lengths[p['edge_id']] for p in profiles
            if p['day_group']==day and p['time_bucket']==hour and p['status']!='unknown')/total_length
    coverage['denominator'] = 'fixed directed edges with positive length in the exact 100 km2 square'
    coverage['target_role'] = 'reference only; unchanged scientific classification rules'
    v1.json_atomic(work/'coverage_report.json', coverage)
    output = work/'candidate_export'; output.mkdir(exist_ok=True)
    evaluation = v1.cached_evaluation(source, db, work, output, network, profiles, config, cutoff, key, guard)
    v1.json_atomic(work/'evaluation.json', evaluation)
    guard(); target_graph = output/'graph'; target_graph.mkdir(exist_ok=True)
    for path in graph_root.iterdir():
        shutil.copyfile(path, target_graph/path.name)
    v1.write_profiles(output/'congestion_profiles.parquet', profiles)
    v1.write_json(output/'pipeline_config.json', config)
    v1.write_json(output/'coverage.json', coverage['buckets'])
    v1.write_json(output/'coverage_report.json', coverage)
    v1.write_json(output/'evaluation.json', evaluation)
    geo = output/'traffic.geojson'; temporary = geo.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        stream.write('{"type":"FeatureCollection","features":[')
        for index, row in enumerate(profiles):
            if index % 1000 == 0:
                guard()
            properties = {k:v for k,v in row.items() if k!='train_cutoff'}
            properties.update(color=v1.COLORS[row['status']], highway=network.edges[row['edge_id']].highway)
            feature = {'type':'Feature','geometry':v1.mapping(network.edges[row['edge_id']].geometry),'properties':properties}
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
    guard()
    manifest = {'run_id':v1.digest([identity,v1.VERSION,ledger_key])[:20], 'graph_version':network.graph_version,
        'cutoff_utc':cutoff.isoformat(), 'data_kind':'SYNTHETIC' if identity['source']['synthetic'] else 'REAL_INPUT_UNVERIFIED_PROVENANCE',
        'status':'CANDIDATE_PENDING_MANUAL_QC_AND_HOLDOUT_REVIEW', 'matching_complete':matching['all_eligible_complete'],
        'outputs_sha256':{p.relative_to(output).as_posix():v1.sha256_file(p) for p in output.rglob('*')
                          if p.is_file() and p.name!='run_metadata.json' and p.suffix!='.tmp'}}
    v1.write_json(output/'run_metadata.json',manifest); v1.json_atomic(work/'candidate_manifest.json',manifest)
    result = {'status':'REPORT_CONTINUE_COMPLETE','postprocessing_complete':True,
        'matching_complete':matching['all_eligible_complete'],'matched_parents':matching['completed_parents'],
        'expected_parents':matching['expected_parents'],'coverage':coverage,'evaluation':evaluation,
        'verified_batch_count':len(source.ids),'ledger_receipt_sha256':ledger_key,
        'parent_qc_counts':{s:{'whole_parent_complete':n,'parents_with_accepted_core_observations':a}
            for s,n,a in db.execute('SELECT split,SUM(complete),SUM(accepted>0) FROM verified_parents GROUP BY split')},
        'candidate_export':str(output),'native_matching_performed':False,'raw_scan_performed':False,
        'batch_imports':0,'index_builds':0,'large_ledger_copied_to_output':False}
    v1.json_atomic(work/'result_summary.json',result)
    return result


def continue_report(source_path, cache_path, work, scratch, seconds=5400):
    if type(seconds) is not int or not 1 <= seconds <= 5400:
        raise ValueError('Report budget must be finite, at most 5400 seconds')
    work = Path(work).resolve(); work.mkdir(parents=True, exist_ok=True)
    cache = SavedCache(cache_path); source = None; connection = None; phase = 'preflight'
    try:
        checkpoint = cache.read_json('ledger_checkpoint.json'); receipt = cache.read_json('source_receipt.json')
        facts = storage_preflight(cache, scratch, work)
        v1.json_atomic(work/'storage_preflight.json', facts)
        source = v1.Source(source_path)
        matching_bytes = source.read('matching_summary.json'); matching = json.loads(matching_bytes)
        identity = matching['identity']; plan = identity['plan']; config = identity['config']
        v1.original.validate_plan(plan)
        guard = Guard(work, plan, seconds)
        complete = all(matching['completed_parents'].get(s,0)==matching['expected_parents'].get(s,0) for s in ('train','holdout'))
        if complete != matching['all_eligible_complete']:
            raise ValueError('Original matching completion flag disagrees with parent counts')
        if identity['code'] != v1.original.code_identity() or v1.sha256_file(Path(v1.__file__)) != V1_SCRIPT_SHA:
            raise ValueError('Original frozen matching/recovery code identity differs')
        if identity['runtime'] != {name:v1.original.version(name) for name in identity['runtime']}:
            raise ValueError('Scientific library versions differ from original matching')
        recovery_identity = {'version':v1.VERSION, 'matching':identity, 'recovery_script_sha256':V1_SCRIPT_SHA}
        if checkpoint['identity'] != v1.digest(recovery_identity) or receipt['recovery_script_sha256'] != V1_SCRIPT_SHA:
            raise ValueError('Saved ledger belongs to a different matching/recovery identity')
        if receipt['matching_summary_sha256'] != v1.sha(matching_bytes):
            raise ValueError('Original matching summary differs from the saved recovery Input')
        if source.archive:
            print('VERIFY original matching Output ZIP SHA256 sequentially', flush=True)
            source_sha = v1.sha256_file(source.path); guard()
            if source_sha != checkpoint.get('source_zip_sha256') or source_sha != receipt.get('source_zip_sha256'):
                raise ValueError('Original matching Output ZIP differs from the verified recovery source')
        else:
            # The fast continuation relies on an immutable full archive digest, not only batch names.
            raise ValueError('Use the ORIGINAL matching _output_.zip for sealed continuation; do not rebuild or alter that archive')
        phase = 'stage_ledger'; ledger = stage_ledger(cache, scratch, checkpoint['ledger_sha256'], guard)
        graph_root = work/'graph'; graph_root.mkdir(exist_ok=True)
        metadata_bytes = source.read('graph/graph_metadata.json'); metadata = json.loads(metadata_bytes)
        for name, checksum in metadata['sha256'].items():
            if '/' in name or '\\' in name:
                raise ValueError('Unexpected graph filename')
            data = source.read('graph/'+name)
            if v1.sha(data) != checksum:
                raise ValueError('Original graph checksum differs')
            v1.atomic(graph_root/name,data)
        v1.atomic(graph_root/'graph_metadata.json',metadata_bytes)
        network = v1.RoadNetwork.load(graph_root)
        if network.graph_version != identity['core_graph']:
            raise ValueError('Original graph and matching identity differ')
        # immutable/read-only avoids journal creation or accidental writes to a saved checkpoint.
        connection = sqlite3.connect(ledger.as_uri()+'?mode=ro&immutable=1',uri=True)
        connection.execute('PRAGMA query_only=ON'); connection.execute('PRAGMA cache_size=-131072')
        connection.set_progress_handler(lambda:int(time.monotonic() >= guard.deadline), 100000)
        row = connection.execute("SELECT value FROM recovery_meta WHERE key='identity'").fetchone()
        if not row or row[0] != checkpoint['identity']:
            raise ValueError('Ledger internal identity differs')
        row = connection.execute("SELECT value FROM recovery_meta WHERE key='ingest_complete'").fetchone()
        if not row:
            raise ValueError('Ledger import was not finished; this notebook requires INGEST_COMPLETE')
        ledger_key = json.loads(row[0])
        receipts = list(connection.execute('SELECT batch,receipt FROM verified_batches ORDER BY batch'))
        if len(receipts) != len(source.ids) or v1.digest(receipts) != ledger_key:
            raise ValueError('Sealed verified-batch receipts differ')
        counts = dict(connection.execute('SELECT split,COUNT(*) FROM verified_parents GROUP BY split'))
        if any(counts.get(s,0) != matching['completed_parents'].get(s,0) for s in ('train','holdout')):
            raise ValueError('Sealed original parent counts differ')
        required_indexes = {'evidence_edge','evidence_night'}
        if not required_indexes.issubset({r[1] for r in connection.execute('PRAGMA index_list(evidence)')}):
            raise ValueError('Required saved ledger indexes are missing; no index will be rebuilt')
        key = v1.digest([recovery_identity,ledger_key]); cutoff = datetime.fromisoformat(plan['train_cutoff_utc'].replace('Z','+00:00'))
        v1.json_atomic(work/'continuation_receipt.json', {'cache_input':str(cache.path),'source_input':str(source.path),
            'source_zip_sha256':source_sha,'ledger_sha256':checkpoint['ledger_sha256'],'key':key,
            'matching_complete':complete,'matched_parents':counts,'expected_parents':matching['expected_parents'],
            'verified_batches':len(receipts),'frozen_v1_script_sha256':V1_SCRIPT_SHA,
            'scientific_identity':identity,'resources':facts,'budget_seconds':seconds,
            'read_only_ledger':True,'batch_imports':0,'index_builds':0})
        phase = 'profiles_evaluation_export'
        result = finish(source,CheckedDB(connection,guard),work,graph_root,network,matching,key,ledger_key,config,cutoff,guard)
        print('REPORT_CONTINUE_COMPLETE | 0 matching | 0 imports | 0 index builds', flush=True)
        return result
    except (TimeoutError, StorageBlocked) as exc:
        result = {'status':'REPORT_CONTINUE_PARTIAL' if isinstance(exc,TimeoutError) else 'REPORT_CONTINUE_STORAGE_BLOCKED',
            'phase':phase,'postprocessing_complete':False,'reason':str(exc),'native_matching_performed':False,
            'raw_scan_performed':False,'original_inputs_preserved':True,
            'resume':'Keep BOTH original matching and failed recovery Inputs; retain this small report Output for its caches'}
        v1.json_atomic(work/'result_summary.json',result); print(json.dumps(result),flush=True)
        return result
    except sqlite3.OperationalError as exc:
        if 'interrupt' in str(exc).lower():
            result = {'status':'REPORT_CONTINUE_PARTIAL','phase':phase,'reason':'SQL time budget reached',
                      'postprocessing_complete':False,'original_inputs_preserved':True}
            v1.json_atomic(work/'result_summary.json',result); return result
        raise
    except Exception as exc:
        v1.json_atomic(work/'result_summary.json',{'status':'REPORT_CONTINUE_FAILED','phase':phase,
            'postprocessing_complete':False,'error':str(exc),'original_inputs_preserved':True})
        raise
    finally:
        if connection:
            connection.close()
        if source:
            source.close()
        cache.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--scratch',type=Path,default=Path('/tmp/portoflow_sealed_ledger'))
    parser.add_argument('--budget-seconds',type=int,default=5400)
    args = parser.parse_args()
    cache_path = args.cache if args.cache.is_file() or (args.cache/'ledger_checkpoint.json').is_file() else find_cache(args.cache)
    print(json.dumps(continue_report(args.source,cache_path,args.work,args.scratch,args.budget_seconds),default=str,indent=2),flush=True)
