"""Verify that the delivered notebook actually restores its pinned code and graphs."""
import ast
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def delivery():
    notebook = json.loads((ROOT/'notebooks/PortoFlow_Kaggle.ipynb').read_text(encoding='utf-8'))
    code = {c['id']: ''.join(c['source']) for c in notebook['cells'] if c['cell_type']=='code'}
    for source in code.values():
        compile(source, '<region_notebook>', 'exec')
    with zipfile.ZipFile(ROOT/'deliverables/portoflow_kaggle.zip') as archive:
        assert archive.testzip() is None
        revisions = json.loads(archive.read('portoflow_project/code_revisions.json'))
        assert all(hashlib.sha256(archive.read('portoflow_project/'+n)).hexdigest()==h for n,h in revisions.items())
    return code, revisions


@pytest.mark.parametrize('extracted', [False, True])
def test_bootstrap_restores_exact_delivery(tmp_path, extracted):
    code, revisions = delivery()
    input_dir = tmp_path/'input'; input_dir.mkdir()
    if extracted:
        with zipfile.ZipFile(ROOT/'deliverables/portoflow_kaggle.zip') as archive:
            archive.extractall(input_dir)
    else:
        shutil.copyfile(ROOT/'deliverables/portoflow_kaggle.zip', input_dir/'portoflow_kaggle.zip')
    function = next(n for n in ast.parse(code['region-bootstrap']).body if isinstance(n, ast.FunctionDef) and n.name=='copy_code')
    namespace = {'INPUT':input_dir, 'PROJECT':tmp_path/'project', 'EXPECTED':revisions,
                 'hashlib':hashlib, 'shutil':shutil, 'zipfile':zipfile}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<bootstrap>','exec'), namespace)
    namespace['copy_code']()
    assert all(hashlib.sha256((tmp_path/'project'/n).read_bytes()).hexdigest()==h for n,h in revisions.items())


def test_notebook_has_full_source_phases_and_no_automatic_activation():
    code, revisions = delivery()
    assert "PHASES = ['graph', 'scan', 'match', 'report']" in code['region-bootstrap']
    assert "'-r',freeze" in code['region-execute']
    assert 'configs/study_area.yaml' in revisions
    assert 'LATEST_EXPORT.txt' not in code['region-execute']
