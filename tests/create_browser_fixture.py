"""Small, explicitly synthetic export for the real Streamlit/browser click loop."""
import base64
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from test_journey_endpoints import fixture_network
from portoflow.export import serve_geojson,write_json,write_profiles
from portoflow.storage import sha256_file


def create(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    network,rows,point,config=fixture_network()
    network.save(destination/'graph')
    write_profiles(destination/'congestion_profiles.parquet',rows)
    write_json(destination/'traffic.geojson',serve_geojson(network,rows))
    write_json(destination/'pipeline_config.json',config);write_json(destination/'coverage.json',{})
    (destination/'diagnostics.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9XkAAAAASUVORK5CYII='))
    manifest={'run_id':'SYNTHETIC_BROWSER_CLICK_LOOP','graph_version':network.graph_version,
        'data_kind':'SYNTHETIC','status':'CANDIDATE_SYNTHETIC_TEST','cutoff_utc':'2014-05-01T00:00:00Z',
        'outputs_sha256':{p.relative_to(destination).as_posix():sha256_file(p) for p in destination.rglob('*') if p.is_file() and p.name!='run_metadata.json'}}
    write_json(destination/'run_metadata.json',manifest)
    return destination


if __name__=='__main__':print(create(sys.argv[1]))
