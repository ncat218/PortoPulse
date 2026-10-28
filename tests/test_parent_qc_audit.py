"""Synthetic stdlib audit fixtures: no raw matching, coverage gain or real QC claim."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import audit_saved_parents as tool


def row(tid,n,accepted,*,split='train',native='success',accepted_gaps=4):
    return dict(trip_id=tid,source_row=n,split=split,whole_parent_complete=native=='success',
        accepted_observations=accepted,blocks=[dict(point_start=0,point_stop=10,native_status=native,
        qc=dict(accepted_gaps=accepted_gaps,rejected_gaps={'gap_speed':1} if not accepted else {}))])


def archive(tmp_path,*,duplicate=False,corrupt=False,count_mismatch=False):
    batches=[[row('SYNTHETIC_A',1,2),row('SYNTHETIC_B',2,0,native='failed',accepted_gaps=0)],
             [row('SYNTHETIC_C',3,0,accepted_gaps=0),row('SYNTHETIC_D',4,0)],
             [row('SYNTHETIC_E',5,5,split='holdout')]]
    if duplicate: batches[1][0]['trip_id']='SYNTHETIC_A'
    identity={'source':{'synthetic':True},'core_graph':'SYNTHETIC_GRAPH'}
    matching=dict(identity=identity,all_eligible_complete=True,completed_parents={'train':4,'holdout':1},
        expected_parents={'train':4,'holdout':1},parents_with_accepted_core_observations={'train':1,'holdout':1})
    if count_mismatch: matching['completed_parents']['train']+=1
    path=tmp_path/'SYNTHETIC_output.zip'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        prefix='./portoflow_run/'
        z.writestr(prefix+'matching_summary.json',tool.encode(matching))
        z.writestr(prefix+'source_summary.json',tool.encode({'status':'SOURCE_EOF_COMPLETE','identity':identity['source'],'inventory':{'candidate_train':4}}))
        z.writestr(prefix+'graph/graph_metadata.json',tool.encode({'graph_version':'SYNTHETIC_GRAPH'}))
        for i,parents in enumerate(batches):
            data=tool.encode(parents)
            manifest={'identity':identity,'outputs_sha256':{'parents.json':tool.digest(data)}}
            if corrupt and i==1: data+=b' '
            z.writestr(prefix+f'region_batches/b{i}/parents.json',data)
            z.writestr(prefix+f'region_batches/b{i}/run_metadata.json',tool.encode(manifest))
    return path


def run(source,work,**kwargs):
    return tool.audit(source,work,expected_sha=tool.sha_file(source),expected_graph='SYNTHETIC_GRAPH',**kwargs)


def test_audit_counts_split_qc_categories_and_train_only_examples(tmp_path):
    source=archive(tmp_path);before=source.read_bytes();work=tmp_path/'audit'
    result=run(source,work)
    assert result['status']=='PARENT_QC_AUDIT_COMPLETE' and result['data_kind']=='SYNTHETIC'
    assert not result['coverage_changed'] and not result['can_estimate_additional_coverage']
    train=result['metrics']['train'];assert train['parents']==4 and train['parents_with_accepted_core_observations']==1
    assert train['parent_reason/all_native_blocks_unsuccessful']==1
    assert train['parent_reason/no_accepted_gaps_in_saved_block_qc']==1
    assert train['parent_reason/block_qc_accepted_gaps_but_no_accepted_core_observations']==1
    assert train['rejected_gap_reason/gap_speed']==3
    examples=json.loads((work/'examples.json').read_bytes())
    assert len(examples)==3 and all(r['split']=='train' for r in examples)
    assert source.read_bytes()==before
    assert not list(work.glob('*.parquet')) and not list(work.glob('*evidence*'))


def test_partial_commits_and_resume_reuses_verified_parents_exactly(tmp_path):
    source=archive(tmp_path);work=tmp_path/'audit'
    partial=run(source,work,limits={'max_new_batches':1})
    assert partial['status']=='PARENT_QC_AUDIT_PARTIAL' and partial['committed_batches']==1
    assert partial['audit_state_sha256']==tool.sha_file(work/'audit_state.sqlite')
    complete=run(source,work)
    assert complete['status']=='PARENT_QC_AUDIT_COMPLETE' and complete['committed_batches']==3
    assert complete['metrics']['train']['parents']==4
    assert run(source,work)['metrics']==complete['metrics']


@pytest.mark.parametrize('failure',['duplicate','corrupt','count_mismatch'])
def test_invalid_input_never_claims_complete_and_preserves_prior_commits(tmp_path,failure):
    source=archive(tmp_path,**{failure:True})
    result=run(source,tmp_path/'audit')
    assert result['status']=='PARENT_QC_AUDIT_FAILED' and result['error']
    assert not result['coverage_changed']
    if failure!='count_mismatch': assert result['committed_batches']==1


def test_wrong_zip_sha_fails_before_creating_state(tmp_path):
    source=archive(tmp_path);work=tmp_path/'audit'
    result=tool.audit(source,work,expected_sha='0'*64,expected_graph='SYNTHETIC_GRAPH')
    assert result['status']=='PARENT_QC_AUDIT_FAILED' and result['phase']=='source_sha'
    assert not (work/'audit_state.sqlite').exists()


def test_resume_state_corruption_does_not_replace_good_seal(tmp_path):
    source=archive(tmp_path);work=tmp_path/'audit'
    run(source,work,limits={'max_new_batches':1})
    receipt=(work/'summary.json').read_bytes()
    with sqlite3.connect(work/'audit_state.sqlite') as db: db.execute('UPDATE metrics SET n=n+1')
    result=run(source,work)
    assert result['status']=='PARENT_QC_AUDIT_FAILED' and result['resume_state_untouched']
    assert (work/'summary.json').read_bytes()==receipt
    assert (work/'last_attempt.json').is_file()


def test_resource_stop_before_source_access_is_partial(monkeypatch,tmp_path):
    source=archive(tmp_path)
    def stop(self): raise MemoryError('SYNTHETIC resource stop')
    monkeypatch.setattr(tool.Budget,'check',stop)
    result=run(source,tmp_path/'audit')
    assert result['status']=='PARENT_QC_AUDIT_PARTIAL' and result['committed_batches']==0


def test_dedicated_output_guard_protects_serving_folder(tmp_path):
    source=archive(tmp_path);work=tmp_path/'export';work.mkdir();(work/'run_metadata.json').write_text('{}')
    with pytest.raises(ValueError,match='dedicated'): run(source,work)
    assert (work/'run_metadata.json').read_text()=='{}'


def test_notebook_embeds_exact_stdlib_script_and_finite_caps():
    path=ROOT/'notebooks/PortoFlow_Coverage_Audit.ipynb'
    notebook=json.loads(path.read_bytes())
    code=''.join(notebook['cells'][1]['source']);tree=ast.parse(code)
    assignments={node.targets[0].id:node.value for node in tree.body if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name)}
    embedded=ast.literal_eval(assignments['SCRIPT'])
    assert embedded.encode()==(ROOT/'scripts/audit_saved_parents.py').read_bytes()
    assert ast.literal_eval(assignments['EXPECTED_SCRIPT_SHA'])==hashlib.sha256(embedded.encode()).hexdigest()
    assert tool.DEFAULT_LIMITS['seconds']==2700 and tool.DEFAULT_LIMITS['output_bytes']==768*1024**2
    assert "RESUME = None" in code and 'shutil.copytree' not in code
    for cell in notebook['cells']:
        if cell['cell_type']=='code':ast.parse(''.join(cell['source']))


def test_notebook_bootstrap_execution_and_small_review_zip_on_synthetic_input(tmp_path):
    source=archive(tmp_path);work=tmp_path/'notebook_audit';script_path=tmp_path/'embedded_audit.py'
    review=tmp_path/'synthetic_review.zip'
    notebook=json.loads((ROOT/'notebooks/PortoFlow_Coverage_Audit.ipynb').read_bytes())
    setup=''.join(notebook['cells'][1]['source'])
    setup=setup.replace('SOURCE = None  #',f'SOURCE = Path({str(source)!r})  #')
    setup=setup.replace("Path('/kaggle/working/portoflow_coverage_audit')",f'Path({str(work)!r})')
    setup=setup.replace("Path('/kaggle/working/portoflow_parent_qc_audit.py')",f'Path({str(script_path)!r})')
    namespace={};exec(compile(setup,'SYNTHETIC_notebook_setup','exec'),namespace)
    # Only the test runner substitutes its invented archive identity. The actual
    # generated notebook pins the real SHA and graph and offers no override flag.
    embedded=namespace['audit_tool']
    embedded.audit.__kwdefaults__.update(expected_sha=tool.sha_file(source),expected_graph='SYNTHETIC_GRAPH')
    code=''.join(notebook['cells'][2]['source']).replace("Path('/kaggle/working/portoflow_coverage_audit_review.zip')",f'Path({str(review)!r})')
    exec(compile(code,'SYNTHETIC_notebook_execute','exec'),namespace)
    assert namespace['result']['status']=='PARENT_QC_AUDIT_COMPLETE'
    assert namespace['result']['data_kind']=='SYNTHETIC'
    with zipfile.ZipFile(review) as z:
        assert set(z.namelist())=={'portoflow_coverage_audit/'+name for name in ('summary.json','examples.json','budget.json')}
        assert not any(name.endswith('.sqlite') for name in z.namelist())
    assert review.stat().st_size < 16*1024
