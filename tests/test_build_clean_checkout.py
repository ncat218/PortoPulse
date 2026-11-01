"""Packaging must work without an ignored output directory from earlier runs."""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('script,archive_name,prefix',[
    ('build_kaggle.py','portoflow_kaggle.zip','portoflow_project'),
    ('build_report_recovery.py','portoflow_report_recovery.zip','portoflow_report_recovery'),
    ('build_report_continue.py','portoflow_report_continue.zip','portoflow_report_continue'),
])
def test_builder_creates_missing_output_directory(tmp_path,monkeypatch,script,archive_name,prefix):
    # A source-only checkout: tracked input directories exist, ignored ZIPs do not.
    # No raw GPS, real graph, export, existing deliverables or credentials are copied.
    for directory in ('app','configs','docs','requirements','scripts','src','tests'):
        shutil.copytree(ROOT/directory,tmp_path/directory,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('pyproject.toml','README.md'):
        shutil.copyfile(ROOT/name,tmp_path/name)
    (tmp_path/'notebooks').mkdir()
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    builder=runpy.run_path(str(ROOT/'scripts'/script))['build']
    monkeypatch.setitem(builder.__globals__,'ROOT',tmp_path)
    assert not (tmp_path/'deliverables').exists()
    for _ in range(2):  # Also safe when the previous output directory exists.
        builder()
        archive_path=tmp_path/'deliverables'/archive_name
        with zipfile.ZipFile(archive_path) as archive:
            assert archive.testzip() is None
            revisions=json.loads(archive.read(prefix+'/code_revisions.json'))
            assert revisions
            for relative,digest in revisions.items():
                assert hashlib.sha256(archive.read(prefix+'/'+relative)).hexdigest()==digest
                assert (tmp_path/relative).read_bytes()==archive.read(prefix+'/'+relative)
        digest=hashlib.sha256(archive_path.read_bytes()).hexdigest()
        assert archive_path.with_suffix('.sha256.txt').read_text().split()[0]==digest
