"""Synthetic sealed-ledger continuation, storage preflight, and corruption guards."""
import ast
import hashlib
import importlib.util
import json
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pyarrow.parquet as pq
import pytest

from test_report_recovery import saved
from portoflow import pipeline as old
from portoflow.storage import sha256_file, verify_checkpoint

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import report_continue as continuation
v1=continuation.v1


@pytest.fixture(autouse=True)
def synthetic_disk_budget(monkeypatch):
    # Tiny synthetic ledgers must not depend on spare capacity on the host C:.
    # Storage-specific tests below override this explicit synthetic capacity.
    usage=shutil._ntuple_diskusage(total=100*continuation.GiB,used=50*continuation.GiB,free=50*continuation.GiB)
    monkeypatch.setattr(continuation.shutil,'disk_usage',lambda path:usage)


@pytest.fixture
def disk_capped(saved,tmp_path):
    work,plan,config,network,matching=saved
    # Keep matching explicitly partial, despite a complete postprocessing ledger.
    matching['expected_parents']['train']+=7;matching['all_eligible_complete']=False
    old.write_json(work/'matching_summary.json',matching)
    baseline=old.report(work,plan,config)
    original=tmp_path/'original_output.zip'
    with zipfile.ZipFile(original,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in work.rglob('*'):
            if path.is_file():
                archive.write(path,'./portoflow_run/'+path.relative_to(work).as_posix())
    destination=tmp_path/'failed/portoflow_recovery'
    with patch.object(v1,'cached_profiles',side_effect=OSError('Output disk ceiling exceeded; retain checkpoints and stop')):
        with pytest.raises(OSError,match='disk ceiling'):
            v1.recover(original,destination,120)
    assert json.loads((destination/'result_summary.json').read_text())['phase']=='profiles'
    assert (destination/'ledger_checkpoint.json').is_file()
    return original,destination,baseline,work


@pytest.mark.parametrize('archive_mode',[False,True])
def test_disk_capped_cache_finishes_read_only_without_imports_or_indexes(disk_capped,tmp_path,archive_mode):
    original,cache,baseline,work=disk_capped
    checksum=sha256_file(cache/'recovery_evidence.sqlite')
    if archive_mode:
        path=tmp_path/'failed_recovery_output.zip'
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
            for item in cache.rglob('*'):
                if item.is_file():
                    archive.write(item,'./portoflow_recovery/'+item.relative_to(cache).as_posix())
    else:
        path=cache
    cached_profiles=v1.cached_profiles
    def assert_read_only(db,*args,**kwargs):
        with pytest.raises(sqlite3.OperationalError,match='readonly'):
            db.execute('UPDATE evidence SET duration=duration+1')
        return cached_profiles(db,*args,**kwargs)
    destination=tmp_path/'portoflow_report_final';scratch=tmp_path/'temporary_ledger'
    with patch.object(v1,'ingest',side_effect=AssertionError('must not import')) ,\
         patch.object(v1,'open_ledger',side_effect=AssertionError('must not create ledger/indexes')),\
         patch.object(old,'run_matching',side_effect=AssertionError('must not match')),\
         patch.object(old,'scan_source',side_effect=AssertionError('must not scan')),\
         patch.object(v1,'cached_profiles',side_effect=assert_read_only):
        result=continuation.continue_report(original,path,destination,scratch,120)
    assert result['status']=='REPORT_CONTINUE_COMPLETE'
    assert result['postprocessing_complete'] and not result['matching_complete']
    assert result['batch_imports']==result['index_builds']==0
    assert result['expected_parents']['train']-result['matched_parents']['train']==7
    assert result['coverage']['buckets']==baseline['coverage']['buckets']
    assert result['coverage']['all_buckets_target_met']==baseline['coverage']['all_buckets_target_met']
    for method in ('static','bucket'):
        assert result['evaluation']['metrics'][method]==pytest.approx(baseline['evaluation']['metrics'][method],abs=1e-12)
    assert verify_checkpoint(destination/'candidate_export')['data_kind']=='SYNTHETIC'
    assert pq.read_table(destination/'candidate_export/congestion_profiles.parquet').to_pylist()==pq.read_table(work/'review_export/congestion_profiles.parquet').to_pylist()
    assert not list(destination.rglob('*.sqlite'))
    assert sha256_file(cache/'recovery_evidence.sqlite')==checksum
    assert bool(list(scratch.glob('*.sqlite')))==archive_mode
    with patch.object(v1,'_stats',side_effect=AssertionError('must reuse profile cache')):
        assert continuation.continue_report(original,path,destination,scratch,120)['postprocessing_complete']


def test_more_than_12_gib_preflight_is_bounded_and_fails_before_expensive_work(tmp_path):
    class FakeCache:
        archive=True
        def ledger_size(self): return 13*continuation.GiB
        def read_json(self,name): return {'ledger_sha256':'a'*64}
    cache=FakeCache()
    facts=continuation.storage_preflight(cache,tmp_path/'scratch',tmp_path/'work',free=20*continuation.GiB)
    assert facts['ledger_bytes']>12*continuation.GiB
    assert facts['required_free_bytes']==16*continuation.GiB
    assert not facts['large_ledger_copied_to_output']
    with pytest.raises(continuation.StorageBlocked,match='No report started'):
        continuation.storage_preflight(cache,tmp_path/'scratch',tmp_path/'work',free=2*continuation.GiB)
    with pytest.raises(ValueError,match='outside'):
        continuation.storage_preflight(cache,tmp_path/'work/scratch',tmp_path/'work',free=30*continuation.GiB)
    with pytest.raises(continuation.StorageBlocked,match='Saved Output needs'):
        continuation.storage_preflight(cache,tmp_path/'scratch',tmp_path/'work',free=30*continuation.GiB,output_free=continuation.GiB)
    with pytest.raises(continuation.StorageBlocked,match='finite cap'):
        cache.ledger_size=lambda:25*continuation.GiB
        continuation.storage_preflight(cache,tmp_path/'scratch',tmp_path/'work',free=40*continuation.GiB)


@pytest.mark.parametrize('damage',['checksum','unfinished'])
def test_corrupt_or_unfinished_ledger_never_reimports(disk_capped,tmp_path,damage):
    original,cache,_,_=disk_capped
    if damage=='checksum':
        with (cache/'recovery_evidence.sqlite').open('ab') as stream:
            stream.write(b'SYNTHETIC_CORRUPTION')
    else:
        with sqlite3.connect(cache/'recovery_evidence.sqlite') as db:
            db.execute("DELETE FROM recovery_meta WHERE key='ingest_complete'")
        checkpoint=json.loads((cache/'ledger_checkpoint.json').read_text())
        checkpoint['ledger_sha256']=sha256_file(cache/'recovery_evidence.sqlite')
        v1.json_atomic(cache/'ledger_checkpoint.json',checkpoint)
    with patch.object(v1,'ingest',side_effect=AssertionError('must not import')):
        with pytest.raises(ValueError,match='checksum' if damage=='checksum' else 'not finished'):
            continuation.continue_report(original,cache,tmp_path/'final',tmp_path/'scratch',120)


def test_saved_cache_auto_selection_ignores_synthetic_and_review_archives(disk_capped,tmp_path):
    _,cache,_,_=disk_capped
    input_root=tmp_path/'inputs';input_root.mkdir()
    output=input_root/'failed_output.zip'
    with zipfile.ZipFile(output,'w') as archive:
        for name in ('ledger_checkpoint.json','source_receipt.json','recovery_evidence.sqlite'):
            archive.write(cache/name,'portoflow_recovery/'+name)
    with zipfile.ZipFile(input_root/'review.zip','w') as archive:
        archive.writestr('ledger_checkpoint.json','{}')
    with zipfile.ZipFile(input_root/'synthetic.zip','w') as archive:
        for name in ('ledger_checkpoint.json','source_receipt.json','recovery_evidence.sqlite'):
            archive.writestr('report_continue_synthetic_tests/portoflow_recovery/'+name,'{}')
    assert continuation.find_cache(input_root)==output


def notebook_code():
    notebook=json.loads((ROOT/'notebooks/PortoFlow_Report_Continue.ipynb').read_text(encoding='utf-8'))
    code={c['id']:''.join(c['source']) for c in notebook['cells'] if c['cell_type']=='code'}
    for body in code.values():
        compile(body,'<continuation_notebook>','exec')
    return code


def test_continue_delivery_pins_original_v1_and_frozen_scientific_files(tmp_path):
    code=notebook_code()
    with zipfile.ZipFile(ROOT/'deliverables/portoflow_report_continue.zip') as archive:
        assert archive.testzip() is None
        revisions=json.loads(archive.read('portoflow_report_continue/code_revisions.json'))
        assert revisions['scripts/report_recovery.py']==continuation.V1_SCRIPT_SHA
        for name,checksum in revisions.items():
            assert hashlib.sha256(archive.read('portoflow_report_continue/'+name)).hexdigest()==checksum
        # Compare to the original recovery Dataset, which is also a Kaggle Input.
        for name in revisions:
            if name.startswith('src/portoflow/'):
                assert archive.read('portoflow_report_continue/'+name)==(ROOT/name).read_bytes()
    execute=code['report-continue-execute']
    assert 'report_continue.py' in execute and "'--cache',CACHE" in execute
    assert "'--scratch',SCRATCH" in execute and "'match'" not in execute
    assert '/tmp/report_continue_synthetic_tests' in execute
    input_root=tmp_path/'inputs';input_root.mkdir()
    shutil.copyfile(ROOT/'deliverables/portoflow_report_continue.zip',input_root/'portoflow_report_continue.zip')
    namespace={'INPUT':input_root,'PROJECT':tmp_path/'project','EXPECTED':revisions,
               'hashlib':hashlib,'shutil':shutil,'zipfile':zipfile}
    node=next(n for n in ast.parse(code['report-continue-bootstrap']).body if isinstance(n,ast.FunctionDef) and n.name=='restore_code')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<restore_code>','exec'),namespace)
    namespace['restore_code']()
    assert all(hashlib.sha256((tmp_path/'project'/n).read_bytes()).hexdigest()==h for n,h in revisions.items())


def test_storage_block_is_reported_before_hashing_or_loading_large_inputs(disk_capped,tmp_path):
    original,cache,_,_=disk_capped
    low=shutil._ntuple_diskusage(total=10*continuation.GiB,used=9*continuation.GiB,free=continuation.GiB)
    with patch.object(continuation.shutil,'disk_usage',return_value=low),\
         patch.object(continuation,'stage_ledger',side_effect=AssertionError('must not stage')),\
         patch.object(v1,'sha256_file',side_effect=AssertionError('must not hash before space check')):
        result=continuation.continue_report(original,cache,tmp_path/'final',tmp_path/'scratch',120)
    assert result['status']=='REPORT_CONTINUE_STORAGE_BLOCKED'
    assert result['phase']=='preflight'
    assert 'No report started' in result['reason']


@pytest.mark.parametrize('archive_mode',[False,True])
def test_small_resume_never_copies_large_ledger(tmp_path,archive_mode):
    code=notebook_code()['report-continue-bootstrap']
    original=tmp_path/'prior/portoflow_report_final';original.mkdir(parents=True)
    (original/'continuation_receipt.json').write_text('{}')
    (original/'profile_cache/a').mkdir(parents=True);(original/'profile_cache/a/chunk.json').write_text('{}')
    (original/'recovery_evidence.sqlite').write_bytes(b'MUST_NOT_COPY')
    path=original
    if archive_mode:
        path=tmp_path/'small_output.zip'
        with zipfile.ZipFile(path,'w') as archive:
            for item in original.rglob('*'):
                if item.is_file():
                    archive.write(item,'portoflow_report_final/'+item.relative_to(original).as_posix())
    work=tmp_path/'work';work.mkdir()
    namespace={'WORK':work,'Path':Path,'shutil':shutil,'zipfile':zipfile}
    node=next(n for n in ast.parse(code).body if isinstance(n,ast.FunctionDef) and n.name=='restore_cache')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<restore_small>','exec'),namespace)
    namespace['restore_cache'](path)
    assert (work/'profile_cache/a/chunk.json').is_file()
    assert not list(work.rglob('*.sqlite'))
