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


def test_details_are_opt_in_and_unknown_edge_has_no_empty_chart(monkeypatch,tmp_path):
    import json
    from create_browser_fixture import create
    from portoflow.export import write_profiles,write_json,serve_geojson
    from portoflow.graph import RoadNetwork
    from portoflow.storage import sha256_file
    import pyarrow.parquet as pq

    create(tmp_path)
    profile=tmp_path/'congestion_profiles.parquet'
    rows=pq.read_table(profile).to_pylist()
    for row in rows:
        row.update(median_speed_kmh=None,static_speed_kmh=None,slowdown_ratio=None,
                   status='unknown',confidence='insufficient',distinct_trips=0,distinct_taxis=0,distinct_dates=0)
    write_profiles(profile,rows)
    write_json(tmp_path/'traffic.geojson',serve_geojson(RoadNetwork.load(tmp_path/'graph'),rows))
    manifest_path=tmp_path/'run_metadata.json'
    manifest=json.loads(manifest_path.read_text())
    manifest['run_id']='SYNTHETIC_UNKNOWN_DETAILS'
    manifest['outputs_sha256']['congestion_profiles.parquet']=sha256_file(profile)
    manifest['outputs_sha256']['traffic.geojson']=sha256_file(tmp_path/'traffic.geojson')
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.syspath_prepend(str(ROOT/'app'))
    monkeypatch.setenv('PORTOFLOW_ARTIFACTS',str(tmp_path))
    app=AppTest.from_file(str(ROOT/'app/streamlit_app.py')).run(timeout=45)
    assert not app.exception
    assert not any(item.label=='Xem chi tiết cạnh' for item in app.selectbox)
    assert len(app.dataframe)==0
    app.toggle(key='show_data_details').set_value(True).run(timeout=45)
    assert not app.exception
    assert any(item.label=='Xem chi tiết cạnh' for item in app.selectbox)
    assert any('Chưa có dữ liệu tốc độ lịch sử' in item.value for item in app.info)
    assert len(app.get('arrow_vega_lite_chart'))==0
    app.toggle(key='show_data_details').set_value(False).run(timeout=45)
    assert not app.exception
    assert len(app.dataframe)==0
