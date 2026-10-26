"""Synthetic parity, ZIP recovery, durable progress and corruption rejection."""
import csv
import importlib.util
import json
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
import yaml

from portoflow import pipeline as old
from portoflow.config import load_config
from portoflow.graph import RoadNetwork
from portoflow.profiles import apply_observations, disk_profiles, open_evidence
from portoflow.storage import sha256_file, verify_checkpoint
from portoflow.synthetic import make_demo

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('report_recovery',ROOT/'scripts/report_recovery.py')
recovery=importlib.util.module_from_spec(spec); spec.loader.exec_module(recovery)


@pytest.fixture
def saved(tmp_path):
    plan=yaml.safe_load((ROOT/'configs/study_area.yaml').read_text(encoding='utf-8'))
    plan.update(raw_batch_rows=5,match_batch_trips=3,matching_timeout_seconds=120,
                scan_timeout_seconds=120,report_timeout_seconds=120,train_cutoff_utc='2014-01-01T00:00:00Z')
    source,graph,_=make_demo(tmp_path/'fixture',load_config(ROOT/'configs/default.yaml'))
    # Densify invented night traces to exercise the unchanged night-reference formula.
    with source.open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream); names=reader.fieldnames; rows=list(reader)
    for row in rows:
        try:
            coordinates=json.loads(row['POLYLINE'])
        except ValueError:
            continue
        if len(coordinates)==5:
            dense=[]
            for a,b in zip(coordinates,coordinates[1:]):
                dense.extend([a,[(a[0]+b[0])/2,(a[1]+b[1])/2]])
            row['POLYLINE']=json.dumps(dense+[coordinates[-1]])
    with source.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=names); writer.writeheader();writer.writerows(rows)
    context,core,_=old.build_networks(RoadNetwork.load(graph).graph,plan,synthetic=True)
    work=tmp_path/'portoflow_run';work.mkdir()
    context.save(work/'context_graph');core.save(work/'graph')
    config=old.scientific_config(plan,ROOT/'configs/default.yaml')
    old.scan_source(source,work,plan,config,synthetic=True)
    matching=old.run_matching(work,plan,config,synthetic=True)
    return work,plan,config,core,matching


def test_bulk_aggregation_is_exactly_the_original(saved,tmp_path):
    work,plan,config,network,matching=saved
    cutoff=old.datetime.fromisoformat(plan['train_cutoff_utc'].replace('Z','+00:00'))
    source=recovery.Source(work)
    legacy=open_evidence(tmp_path/'legacy.sqlite')
    optimized=recovery.open_ledger(tmp_path/'optimized.sqlite',{'test':'synthetic'})
    guard=recovery.Guard(tmp_path,plan,120)
    try:
        for bid in source.ids:
            table=pq.read_table(work/'region_batches'/bid/'observations.parquet')
            apply_observations(legacy,bid,table.to_pylist(),network,cutoff)
        recovery.ingest(source,optimized,network,matching,cutoff,guard)
        query='SELECT * FROM evidence ORDER BY trip_id,edge_id,local_date,day_group,bucket'
        assert optimized.execute(query).fetchall()==legacy.execute(query).fetchall()
        key='synthetic-profile-parity'
        profiles=recovery.cached_profiles(optimized,tmp_path/'profile_cache',network,config,cutoff,key,guard,chunk_size=2)
        assert profiles==disk_profiles(legacy,network,config,cutoff)
        # Cached profiles must load without recomputing statistics.
        with patch.object(recovery,'_stats',side_effect=AssertionError('profile chunk was recomputed')):
            assert recovery.cached_profiles(optimized,tmp_path/'profile_cache',network,config,cutoff,key,guard,chunk_size=2)==profiles
    finally:
        source.close();legacy.close();optimized.close()


def test_saved_output_zip_report_only_matches_baseline(saved,tmp_path):
    work,plan,config,network,matching=saved
    baseline=old.report(work,plan,config)
    archive_path=tmp_path/'_output_.zip'
    with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED) as archive:
        selected=[work/'matching_summary.json']+list((work/'graph').iterdir())+list((work/'region_batches').rglob('*'))
        # Reverse archive order and include ./ prefix, as real Output archives may do.
        for path in reversed(selected):
            if path.is_file():
                archive.write(path,'./portoflow_run/'+path.relative_to(work).as_posix())
    with patch.object(old,'run_matching',side_effect=AssertionError('must not call matching')),\
         patch.object(old,'scan_source',side_effect=AssertionError('must not scan raw')):
        result=recovery.recover(archive_path,tmp_path/'recovered',120)
    assert result['postprocessing_complete'] and not result['native_matching_performed']
    assert result['matched_parents']==matching['completed_parents']
    candidate=tmp_path/'recovered/candidate_export'
    assert verify_checkpoint(candidate)['data_kind']=='SYNTHETIC'
    assert pq.read_table(candidate/'congestion_profiles.parquet').to_pylist()==pq.read_table(work/'review_export/congestion_profiles.parquet').to_pylist()
    assert result['coverage']['buckets'].keys()==baseline['coverage']['buckets'].keys()
    for label,counts in result['coverage']['buckets'].items():
        assert counts['known']==baseline['coverage']['buckets'][label]['known']
    for method in ('static','bucket'):
        assert result['evaluation']['metrics'][method]==pytest.approx(baseline['evaluation']['metrics'][method],abs=1e-12)
    read=recovery.Source.read
    def no_batch_replay(self,relative):
        if relative.startswith('region_batches/'):
            raise AssertionError('verified ZIP cache replayed a matching batch')
        return read(self,relative)
    with patch.object(recovery.Source,'read',no_batch_replay):
        assert recovery.recover(archive_path,tmp_path/'recovered',120)['postprocessing_complete']


def test_timeout_preserves_ingest_and_resume_skips_aggregation(saved,tmp_path):
    work,plan,config,network,matching=saved
    destination=tmp_path/'recovered'
    original_guard=recovery.Guard
    class Deadline(original_guard):
        calls=0
        def __call__(self):
            self.calls+=1
            if self.calls==4:
                raise TimeoutError('synthetic report deadline')
            super().__call__()
    with patch.object(recovery,'Guard',Deadline):
        partial=recovery.recover(work,destination,120)
    assert partial['status']=='REPORT_RECOVERY_PARTIAL'
    with sqlite3.connect(destination/'recovery_evidence.sqlite') as db:
        committed=db.execute('SELECT COUNT(*) FROM verified_batches').fetchone()[0]
    assert committed==3
    aggregate=recovery.aggregate
    with patch.object(recovery,'aggregate',wraps=aggregate) as tracked:
        result=recovery.recover(work,destination,120)
    assert result['postprocessing_complete']
    assert tracked.call_count==len(list((work/'region_batches').iterdir()))-committed


def test_changed_committed_batch_is_rejected(saved,tmp_path):
    work,plan,config,network,matching=saved
    destination=tmp_path/'recovered'
    recovery.recover(work,destination,120)
    path=next((work/'region_batches').glob('*/observations.parquet'))
    with path.open('ab') as stream:
        stream.write(b'SYNTHETIC_CORRUPTION')
    with pytest.raises(ValueError,match='checksum'):
        recovery.recover(work,destination,120)


def test_duplicate_original_parent_is_never_counted_twice(saved,tmp_path):
    work,plan,config,network,matching=saved
    first=next((work/'region_batches').iterdir())
    parents=json.loads((first/'parents.json').read_text()); parent=parents[0]
    table=pq.read_table(first/'observations.parquet')
    table=table.filter(pc.equal(table['trip_id'],parent['trip_id']))
    bid=recovery.digest([matching['identity'],[parent['trip_id']]])[:24]
    duplicate=work/'region_batches'/bid;duplicate.mkdir()
    pq.write_table(table,duplicate/'observations.parquet')
    old.write_json(duplicate/'parents.json',[parent]);old.write_json(duplicate/'review_cases.json',[])
    old.write_json(duplicate/'run_metadata.json',{'identity':matching['identity'],'outputs_sha256':{
        name:sha256_file(duplicate/name) for name in recovery.FILES}})
    with pytest.raises(sqlite3.IntegrityError):
        recovery.recover(work,tmp_path/'recovered',120)


def test_partial_native_run_is_not_presented_as_full_matching(saved,tmp_path):
    work,plan,config,network,matching=saved
    matching['expected_parents']['train']+=10;matching['all_eligible_complete']=False
    old.write_json(work/'matching_summary.json',matching)
    result=recovery.recover(work,tmp_path/'recovered',120)
    assert result['postprocessing_complete'] and result['matching_complete'] is False
    assert result['expected_parents']['train']-result['matched_parents']['train']==10


def test_changed_recovery_database_is_not_trusted(saved,tmp_path):
    work,plan,config,network,matching=saved
    destination=tmp_path/'recovered'
    recovery.recover(work,destination,120)
    with sqlite3.connect(destination/'recovery_evidence.sqlite') as db:
        db.execute('UPDATE evidence SET duration=duration+1 WHERE rowid=(SELECT MIN(rowid) FROM evidence)')
    with pytest.raises(ValueError,match='ledger checkpoint'):
        recovery.recover(work,destination,120)


def test_directory_cache_can_continue_from_the_same_output_zipped(saved,tmp_path):
    work,plan,config,network,matching=saved
    destination=tmp_path/'recovered'
    recovery.recover(work,destination,120)
    archive=tmp_path/'_output_.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
        for path in work.rglob('*'):
            if path.is_file():
                output.write(path,'portoflow_run/'+path.relative_to(work).as_posix())
    with patch.object(recovery,'aggregate',side_effect=AssertionError('must reuse verified ledger rows')):
        assert recovery.recover(archive,destination,120)['postprocessing_complete']


def test_main_report_cli_uses_checkpointed_recovery(saved,tmp_path):
    work,plan,config,network,matching=saved
    plan_file=tmp_path/'plan.yaml';plan_file.write_text(yaml.safe_dump(plan))
    graph_sha=sha256_file(work/'graph/road_graph.graphml')
    completed=subprocess.run([sys.executable,str(ROOT/'scripts/run_pipeline.py'),'--phase','report',
        '--work',str(work),'--plan',str(plan_file),'--config',str(ROOT/'configs/default.yaml'),
        '--authorize-run',old.TOKEN],cwd=ROOT,capture_output=True,text=True,timeout=60)
    assert completed.returncode==0,completed.stdout+completed.stderr
    result=json.loads((work/'result_summary.json').read_text())
    assert result['status']=='REPORT_RECOVERY_COMPLETE'
    assert (work/'portoflow_recovery/recovery_evidence.sqlite').is_file()
    assert not (work/'region_evidence.sqlite').exists()
    assert sha256_file(work/'graph/road_graph.graphml')==graph_sha
