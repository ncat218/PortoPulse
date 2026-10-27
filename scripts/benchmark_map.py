"""Compare previous full Folium rebuild with acknowledged overlay transport.

This measures Python work and JSON/HTML sizes, not end-user latency. Optional
fixture is consumed by the isolated headless Leaflet component test.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

import folium
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from persistent_map import component_arguments, journey_overlay
from ui_logic import index_views
from journey_routing import recommend_coordinate_routes
from portoflow.graph import RoadNetwork
from portoflow.storage import verify_checkpoint


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--export',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--fixture',type=Path)
    a=p.parse_args()
    metadata=verify_checkpoint(a.export)
    profiles=pq.read_table(a.export/'congestion_profiles.parquet').drop(['train_cutoff']).to_pylist()
    geojson=json.loads((a.export/'traffic.geojson').read_text(encoding='utf-8'))
    config=json.loads((a.export/'pipeline_config.json').read_text(encoding='utf-8'))
    started=time.perf_counter();view=index_views(profiles,geojson)[('weekday','09-12')]
    index_seconds=time.perf_counter()-started
    network=RoadNetwork.load(a.export/'graph')
    started=time.perf_counter()
    result=recommend_coordinate_routes(network,profiles,(-8.632,41.162),(-8.629,41.1584),'weekday','09-12',config)
    route_seconds=time.perf_counter()-started
    state={'route_a_lon':-8.632,'route_a_lat':41.162,'route_b_lon':-8.629,'route_b_lat':41.1584,'route_choice':'balanced'}
    overlay=journey_overlay(view['features'],state,result,'benchmark_route')
    dataset='benchmark-'+metadata['outputs_sha256']['traffic.geojson']+'-weekday-09-12'
    args=lambda event:component_arguments(dataset,event,view['map_features'],overlay,[41.16,-8.63],'Chọn điểm A')
    initial=args({});initial_bytes=len(json.dumps(initial,ensure_ascii=False).encode())
    samples=[]
    for _ in range(7):
        started=time.perf_counter();warm=args({'dataset_id':dataset})
        warm_encoded=json.dumps(warm,ensure_ascii=False).encode()
        samples.append(time.perf_counter()-started)
    old_samples=[]
    for _ in range(3):
        started=time.perf_counter();m=folium.Map([41.16,-8.63],zoom_start=14,prefer_canvas=True)
        folium.GeoJson({'type':'FeatureCollection','features':sorted(view['map_features'],key=lambda f:f['properties']['status']!='unknown')},
            style_function=lambda f:{'color':f['properties']['color'],'weight':4,'opacity':.85},
            tooltip=folium.GeoJsonTooltip(fields=['edge_id','status_label']),
            popup=folium.GeoJsonPopup(fields=['edge_id','status_label','median_speed_kmh','reference_speed_kmh','distinct_trips','distinct_taxis','distinct_dates'])).add_to(m)
        old_html=m.get_root().render().encode();old_samples.append(time.perf_counter()-started)
    report={'scope':'Python assembly/serialization, not measured end-user or websocket latency',
        'data_kind':metadata['data_kind'],'directed_edges':len(view['map_features']),
        'day_group':'weekday','time_bucket':'09-12','display_index_cold_s':index_seconds,
        'routing_s_unchanged_algorithm':route_seconds,
        'previous_folium_rebuild_median_s':statistics.median(old_samples),
        'previous_full_html_bytes':len(old_html),'new_initial_arguments_json_bytes':initial_bytes,
        'new_acknowledged_overlay_arguments_json_bytes':len(warm_encoded),
        'new_warm_arguments_serialize_median_s':statistics.median(samples),
        'warm_payload_reduction_fraction':1-len(warm_encoded)/len(old_html),
        'notes':['Old baseline is full Folium base HTML; new measurement is component JSON arguments.',
            'Initial artifact verification/profile loading and routing are separate costs.',
            'Browser component integration is tested separately; no real user FPS measured.']}
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if a.fixture:
        a.fixture.parent.mkdir(parents=True,exist_ok=True)
        a.fixture.write_text(json.dumps({'initial':initial,'warm':warm},ensure_ascii=False),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
