"""Recovery notebook restores pinned baseline code and selects the saved Output."""
import ast
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]


def notebook():
    data=json.loads((ROOT/'notebooks/PortoFlow_Report_Recovery.ipynb').read_text(encoding='utf-8'))
    code={c['id']:''.join(c['source']) for c in data['cells'] if c['cell_type']=='code'}
    for body in code.values():
        compile(body,'<report_recovery_notebook>','exec')
    return code


def helper(code,name,namespace):
    node=next(n for n in ast.parse(code).body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<bootstrap_helper>','exec'),namespace)
    return namespace[name]


def test_frozen_matching_source_is_byte_identical_and_bootstrap_works(tmp_path):
    code=notebook()['report-recovery-bootstrap']
    source_archive=ROOT/'deliverables/portoflow_kaggle.zip'
    recovery_archive=ROOT/'deliverables/portoflow_report_recovery.zip'
    with zipfile.ZipFile(source_archive) as old,zipfile.ZipFile(recovery_archive) as new:
        assert new.testzip() is None
        revisions=json.loads(new.read('portoflow_report_recovery/code_revisions.json'))
        for relative in revisions:
            if relative.startswith('src/portoflow/'):
                assert new.read('portoflow_report_recovery/'+relative)==old.read('portoflow_project/'+relative)
    input_root=tmp_path/'input';input_root.mkdir()
    shutil.copyfile(recovery_archive,input_root/recovery_archive.name)
    namespace={'INPUT':input_root,'PROJECT':tmp_path/'project','EXPECTED':revisions,
               'hashlib':hashlib,'shutil':shutil,'zipfile':zipfile}
    helper(code,'restore_code',namespace)()
    assert all(hashlib.sha256((tmp_path/'project'/n).read_bytes()).hexdigest()==h for n,h in revisions.items())


def test_selects_original_output_zip_and_no_raw_required(tmp_path):
    code=notebook()['report-recovery-bootstrap']
    input_root=tmp_path/'input';input_root.mkdir()
    with zipfile.ZipFile(input_root/'_output_.zip','w') as archive:
        archive.writestr('./portoflow_run/matching_summary.json','{}')
    with zipfile.ZipFile(input_root/'prior_recovery_output.zip','w') as archive:
        archive.writestr('report_recovery_synthetic_tests/case/portoflow_run/matching_summary.json','{}')
    shutil.copyfile(ROOT/'deliverables/portoflow_report_recovery.zip',input_root/'portoflow_report_recovery.zip')
    selected=helper(code,'select_source',{'INPUT':input_root,'zipfile':zipfile,'Path':Path})()
    assert selected.name=='_output_.zip'
    execute=notebook()['report-recovery-execute']
    assert 'run_pipeline.py' not in execute and "'match'" not in execute
    assert 'train.csv' not in code and 'train.csv' not in execute


@pytest.mark.parametrize('archive_mode',[False,True])
def test_recovery_cache_restore_supports_directory_and_zip(tmp_path,archive_mode):
    code=notebook()['report-recovery-bootstrap']
    original=tmp_path/'old/portoflow_recovery';original.mkdir(parents=True)
    (original/'recovery_evidence.sqlite').write_bytes(b'SYNTHETIC_RECOVERY_DB')
    (original/'profile_cache/a').mkdir(parents=True)
    (original/'profile_cache/a/part.json').write_text('{}')
    (original/'candidate_export').mkdir();(original/'candidate_export/large.geojson').write_text('{}')
    if archive_mode:
        path=tmp_path/'recovery_output.zip'
        with zipfile.ZipFile(path,'w') as archive:
            for item in original.rglob('*'):
                if item.is_file():
                    archive.write(item,'portoflow_recovery/'+item.relative_to(original).as_posix())
    else:
        path=original
    destination=tmp_path/'work';destination.mkdir()
    namespace={'WORK':destination,'Path':Path,'shutil':shutil,'zipfile':zipfile}
    helper(code,'restore_cache',namespace)(path)
    assert (destination/'recovery_evidence.sqlite').read_bytes()==b'SYNTHETIC_RECOVERY_DB'
    assert (destination/'profile_cache/a/part.json').is_file()
    assert not (destination/'candidate_export').exists()
