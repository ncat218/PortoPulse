"""Bounded, resumable metadata-only QC audit of the ORIGINAL saved PortoFlow ZIP.

Standard library only. Never extracts the ZIP, reads observation Parquet, uses
the recovery ledger, rematches GPS, changes profiles or activates an export.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import time
import zipfile

VERSION = 'PORTOFLOW_PARENT_QC_AUDIT_V1'
SOURCE_SHA = '71e0a5ee45f1a241835b32254068e9009983d4c5067ef8f4edc821840803a93b'
CORE_GRAPH = '401fea1a982be227710b427ea651784d87d78b0ded45433c5c8f72866b385031'
MiB = 1024**2
DEFAULT_LIMITS = dict(seconds=2700, output_bytes=768*MiB, reserve_bytes=256*MiB,
                      rss_mb=1536, max_new_batches=100000)
ALLOWED_OUTPUTS = {'audit_state.sqlite', 'audit_state.sqlite-journal', 'summary.json',
                   'examples.json', 'budget.json', 'last_attempt.json'}


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name('.'+path.name+'.tmp')
    temporary.write_bytes(encode(value))
    os.replace(temporary, path)


class Budget:
    def __init__(self, work, limits):
        self.work, self.limits = work, limits
        self.deadline = time.monotonic()+limits['seconds']-min(30, limits['seconds']/10)

    def check(self):
        if time.monotonic() >= self.deadline:
            raise TimeoutError('Finite audit deadline reached; committed batches retained')
        size = sum(p.stat().st_size for p in self.work.iterdir() if p.is_file())
        if size > self.limits['output_bytes']:
            raise OSError('Audit Output cap reached; committed batches retained')
        if shutil.disk_usage(self.work).free < self.limits['reserve_bytes']:
            raise OSError('Audit disk reserve reached; committed batches retained')
        status = Path('/proc/self/status')
        if status.is_file():
            for line in status.read_text().splitlines():
                if line.startswith('VmRSS:') and int(line.split()[1]) > self.limits['rss_mb']*1024:
                    raise MemoryError('Audit soft RAM ceiling reached; committed batches retained')


def sha_file(path, check=lambda: None):
    h = hashlib.sha256(); size = 0; announced = 0
    with Path(path).open('rb') as stream:
        while True:
            check(); data = stream.read(8*MiB)
            if not data: break
            h.update(data); size += len(data)
            if size-announced >= 512*MiB:
                print('VERIFY original ZIP:', round(size/MiB), 'MiB read', flush=True); announced = size
    return h.hexdigest()


class SavedZip:
    def __init__(self, path):
        self.archive = zipfile.ZipFile(path)
        try:
            names = {}
            for info in self.archive.infolist():
                parts = PurePosixPath(info.filename)
                if parts.is_absolute() or '..' in parts.parts or '\\' in info.filename:
                    raise ValueError('Unsafe archive member')
                name = parts.as_posix()
                if name in names: raise ValueError('Duplicate canonical ZIP member')
                names[name] = info
            roots = [n[:-len('matching_summary.json')] for n in names if n.endswith('/matching_summary.json') or n == 'matching_summary.json']
            roots = [r for r in roots if r+'graph/graph_metadata.json' in names]
            preferred = [r for r in roots if r.rstrip('/').endswith('portoflow_run')]
            roots = preferred or roots
            if len(roots) != 1: raise ValueError('Select original matching Output with exactly one PortoFlow run')
            prefix = roots[0]
            self.members = {n[len(prefix):]: info for n,info in names.items() if n.startswith(prefix)}
            self.ids = sorted({n.split('/')[1] for n in self.members
                if n.startswith('region_batches/') and n.endswith('/run_metadata.json') and not n.split('/')[1].startswith('.')},
                key=lambda bid:self.members['region_batches/'+bid+'/run_metadata.json'].header_offset)
            if not self.ids: raise ValueError('No committed parent batches')
        except Exception:
            self.archive.close(); raise

    def read(self, name):
        info = self.members[name]
        if info.file_size > 16*MiB: raise ValueError('Audit metadata member exceeds16MiB cap')
        return self.archive.read(info)  # CRC checked by zipfile.

    def json(self, name):
        return json.loads(self.read(name))

    def close(self):
        self.archive.close()


def parent_reason(row):
    if row['accepted_observations'] > 0: return 'has_accepted_core_observations'
    blocks = row['blocks']
    if not blocks: return 'no_saved_candidate_blocks'
    if all(b['native_status'] not in {'success','partial'} for b in blocks):
        return 'all_native_blocks_unsuccessful'
    if all(b.get('qc',{}).get('accepted_gaps',0) == 0 for b in blocks):
        return 'no_accepted_gaps_in_saved_block_qc'
    return 'block_qc_accepted_gaps_but_no_accepted_core_observations'


def batch_statistics(parents):
    metrics = Counter(); examples = []
    for row in parents:
        if (row['split'] not in {'train','holdout'} or not isinstance(row['trip_id'],str)
                or not 0 < len(row['trip_id']) <= 128 or type(row['source_row']) is not int
                or row['source_row'] < 0 or type(row['accepted_observations']) is not int
                or row['accepted_observations'] < 0 or type(row['whole_parent_complete']) is not bool):
            raise ValueError('Invalid saved parent record')
        split = row['split']
        metrics[(split,'parents')] += 1
        metrics[(split,'parents_with_accepted_core_observations')] += int(row['accepted_observations'] > 0)
        metrics[(split,'whole_parent_complete')] += int(row['whole_parent_complete'])
        metrics[(split,'accepted_observation_rows_reported')] += row['accepted_observations']
        if split != 'train': continue  # Holdout is bookkeeping, never a recovery target.
        reason = parent_reason(row)
        metrics[(split,'parent_reason/'+reason)] += 1
        for block in row['blocks']:
            metrics[(split,'native_status/'+str(block['native_status']))] += 1
            qc = block.get('qc',{})
            if qc.get('rejection'): metrics[(split,'qc_rejection/'+str(qc['rejection']))] += 1
            for label,count in qc.get('rejected_gaps',{}).items():
                if type(count) is not int or count < 0: raise ValueError('Invalid rejected-gap count')
                metrics[(split,'rejected_gap_reason/'+str(label))] += count
        if row['accepted_observations'] == 0:
            examples.append({'reason':reason, **row})
    return metrics, examples


def open_state(work, identity):
    db = sqlite3.connect(work/'audit_state.sqlite')
    db.execute('PRAGMA journal_mode=DELETE'); db.execute('PRAGMA cache_size=-16384')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS batches(batch TEXT PRIMARY KEY,receipt TEXT);
        CREATE TABLE IF NOT EXISTS parents(trip_id TEXT PRIMARY KEY,source_row INTEGER UNIQUE,split TEXT);
        CREATE TABLE IF NOT EXISTS metrics(split TEXT,label TEXT,n INTEGER,PRIMARY KEY(split,label));
        CREATE TABLE IF NOT EXISTS examples(trip_id TEXT PRIMARY KEY,reason TEXT,record TEXT);
    ''')
    stored = db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()
    fingerprint = digest(encode(identity))
    if stored and stored[0] != fingerprint:
        db.close(); raise ValueError('Resume audit state belongs to another source/tool identity')
    with db:
        db.execute("INSERT OR IGNORE INTO meta VALUES ('identity',?)",(fingerprint,))
    return db


def snapshot(db, matching, status, phase, error, source_sha, limits, batches_total):
    values = {split:dict(db.execute('SELECT label,n FROM metrics WHERE split=?',(split,)))
              for split in ('train','holdout')} if db else {}
    return {'status':status,'phase':phase,'error':error,'source_zip_sha256':source_sha,
        'tool_version':VERSION,'budget':limits,'committed_batches':db.execute('SELECT COUNT(*) FROM batches').fetchone()[0] if db else 0,
        'available_batches':batches_total,'metrics':values,
        'matching_completed_parents_reported':matching.get('completed_parents') if matching else None,
        'matching_expected_parents_reported':matching.get('expected_parents') if matching else None,
        'matching_complete_reported':matching.get('all_eligible_complete') if matching else None,
        'coverage_changed':False,'can_estimate_additional_coverage':False,
        'interpretation':'Parent/block QC metadata audit only; zero accepted core observations is not proof of a matcher bug.',
        'limits':['No observation Parquet, raw GPS, sealed ledger or matching is read or executed.',
            'Block accepted_gaps is before later trimming/clipping/speed filtering; not a causal diagnosis.',
            'No rejected parent is accepted or recolored by this tool.',
            'Holdout counts are bookkeeping only; examples/recovery targets are train only.']}


def audit(source, work, *, limits=None, expected_sha=SOURCE_SHA, expected_graph=CORE_GRAPH):
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    if any(type(value) is not int or value <= 0 for value in limits.values()):
        raise ValueError('Finite positive integer audit limits required')
    source,work = Path(source).resolve(),Path(work).resolve()
    if not source.is_file() or source.stat().st_size > 8*1024**3:
        raise ValueError('Attach original matching Output ZIP, maximum8GiB; do not select recovery ledger')
    if source.is_relative_to(work): raise ValueError('Audit Output cannot contain the original source')
    work.mkdir(parents=True,exist_ok=True)
    if any(p.name not in ALLOWED_OUTPUTS for p in work.iterdir()):
        raise ValueError('Use a dedicated audit Output directory, never an app export or matching run')
    atomic_json(work/'budget.json',limits)
    budget=Budget(work,limits);db=saved=None;matching=None;batch_total=0;phase='source_sha';actual=None
    status='PARENT_QC_AUDIT_FAILED';error=None
    try:
        budget.check();actual=sha_file(source,budget.check)
        if actual != expected_sha: raise ValueError('Original Output ZIP SHA differs; select the pinned initial matching version')
        phase='source_metadata';saved=SavedZip(source);budget.check()
        matching=saved.json('matching_summary.json');identity=matching['identity']
        source_summary=saved.json('source_summary.json')
        if source_summary['status'] != 'SOURCE_EOF_COMPLETE' or source_summary['identity'] != identity['source']:
            raise ValueError('Source EOF/identity mismatch')
        if identity['core_graph'] != expected_graph or saved.json('graph/graph_metadata.json')['graph_version'] != expected_graph:
            raise ValueError('Core graph mismatch')
        batch_total=len(saved.ids)
        state_file=work/'audit_state.sqlite'
        if state_file.exists():
            previous_summary=json.loads((work/'summary.json').read_bytes())
            if sha_file(state_file,budget.check) != previous_summary.get('audit_state_sha256'):
                raise ValueError('Resume audit-state seal differs; keep original Output and use a fresh audit directory')
        db=open_state(work,{'source_sha':actual,'matching':identity,'version':VERSION,
                           'auditor_sha':sha_file(Path(__file__))})
        phase='parent_batches';processed=0
        for bid in saved.ids:
            budget.check()
            previous=db.execute('SELECT receipt FROM batches WHERE batch=?',(bid,)).fetchone()
            # Every resume re-hashes the entire pinned original ZIP and tool identity.
            if previous: continue
            if processed >= limits['max_new_batches']: raise TimeoutError('Finite per-run batch cap reached')
            base='region_batches/'+bid+'/'
            manifest_data=saved.read(base+'run_metadata.json');manifest=json.loads(manifest_data)
            if manifest['identity'] != identity: raise ValueError('Batch matching identity differs: '+bid)
            data=saved.read(base+'parents.json')
            if digest(data) != manifest['outputs_sha256']['parents.json']:
                raise ValueError('Saved parent checksum differs: '+bid)
            parents=json.loads(data)
            if not isinstance(parents,list) or not parents: raise ValueError('Empty/invalid parent batch')
            metrics,examples=batch_statistics(parents)
            with db:
                try:
                    db.executemany('INSERT INTO parents VALUES (?,?,?)',[(r['trip_id'],r['source_row'],r['split']) for r in parents])
                except sqlite3.IntegrityError as exc:
                    raise ValueError('Duplicate original parent ID/source row across batches') from exc
                for (split,label),n in metrics.items():
                    db.execute('INSERT INTO metrics VALUES (?,?,?) ON CONFLICT(split,label) DO UPDATE SET n=n+excluded.n',(split,label,n))
                count=db.execute('SELECT COUNT(*) FROM examples').fetchone()[0]
                for example in examples:
                    if count >= 100: break
                    per_reason=db.execute('SELECT COUNT(*) FROM examples WHERE reason=?',(example['reason'],)).fetchone()[0]
                    if per_reason >= 25: continue
                    encoded=encode(example)
                    if len(encoded) > 64*1024: continue
                    db.execute('INSERT INTO examples VALUES (?,?,?)',(example['trip_id'],example['reason'],encoded.decode()))
                    count += 1
                db.execute('INSERT INTO batches VALUES (?,?)',(bid,digest(manifest_data+data)))
            processed += 1
            if processed%1000 == 0:
                print('AUDIT committed',db.execute('SELECT COUNT(*) FROM batches').fetchone()[0],'/',batch_total,'batches',flush=True)
        phase='reconciliation'
        for split in ('train','holdout'):
            values=dict(db.execute('SELECT label,n FROM metrics WHERE split=?',(split,)))
            if values.get('parents',0) != matching['completed_parents'].get(split,0):
                raise ValueError('Parent total differs from saved matching summary: '+split)
            if values.get('parents_with_accepted_core_observations',0) != matching['parents_with_accepted_core_observations'].get(split,0):
                raise ValueError('Accepted-parent total differs from saved matching summary: '+split)
        status='PARENT_QC_AUDIT_COMPLETE';phase='complete'
    except (TimeoutError,MemoryError,OSError) as exc:
        status='PARENT_QC_AUDIT_PARTIAL';error=str(exc)
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
    finally:
        result=snapshot(db,matching,status,phase,error,actual,limits,batch_total)
        if matching:
            result['data_kind']='SYNTHETIC' if matching['identity']['source'].get('synthetic') else 'REAL_SAVED_METADATA_PENDING_RAW_QC'
            result['source_scan_inventory_reported']=source_summary.get('inventory') if 'source_summary' in locals() else None
        if db:
            examples=[json.loads(row[0]) for row in db.execute('SELECT record FROM examples ORDER BY reason,trip_id')]
            atomic_json(work/'examples.json',examples);db.close()
            result['audit_state_sha256']=sha_file(work/'audit_state.sqlite')
        if saved: saved.close()
        if db is None and (work/'audit_state.sqlite').exists():
            # A failed source/state check must never destroy the last good seal.
            result['resume_state_untouched'] = True
            atomic_json(work/'last_attempt.json',result)
        else:
            atomic_json(work/'summary.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=audit(a.source,a.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['status']=='PARENT_QC_AUDIT_FAILED': raise SystemExit(1)


if __name__=='__main__': main()
