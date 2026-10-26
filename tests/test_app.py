"""The independent app must start truthfully before real full-source results exist."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_graph_preview_without_export(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT/'app'))
    monkeypatch.setenv('PORTOFLOW_ARTIFACTS', str(tmp_path/'no_export'))
    app = AppTest.from_file(str(ROOT/'app/streamlit_app.py')).run(timeout=45)
    assert not app.exception
    assert any('Chưa có kết quả matching' in item.value for item in app.info)
    assert any('22,860' in item.value for item in app.markdown)
