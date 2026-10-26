"""Synthetic endpoint, one-way, reverse-color and app regression checks."""
import json
import math
import sys
from datetime import datetime,timezone
from pathlib import Path

import networkx as nx
import pytest
from pyproj import Transformer
from shapely.geometry import LineString,Point,mapping

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from journey_routing import recommend_coordinate_routes,snap_candidates
from road_display import separate_direction_geometries
from ui_logic import route_features,index_views
from portoflow.config import load_config
from portoflow.graph import RoadNetwork
from portoflow.export import COLORS,serve_geojson,write_json,write_profiles
from portoflow.storage import sha256_file


def fixture_network(reverse=True,cycle=True):
    to_metric=Transformer.from_crs('EPSG:4326','EPSG:32629',always_xy=True)
    inverse=Transformer.from_crs('EPSG:32629','EPSG:4326',always_xy=True)
    x,y=to_metric.transform(-8.63,41.16)
    point=lambda dx,dy:inverse.transform(x+dx,y+dy)
    graph=nx.MultiDiGraph(crs='EPSG:4326')
    for n,(dx,dy) in {1:(0,0),2:(100,0),3:(200,0),4:(200,100),5:(100,100)}.items():
        lon,lat=point(dx,dy);graph.add_node(n,x=lon,y=lat)
    pairs=[(1,2),(2,3)]+([(3,2)] if reverse else [])+([(3,4),(4,5),(5,2)] if cycle else [])
    for u,v in pairs:
        graph.add_edge(u,v,key=0,geometry=LineString([(graph.nodes[n]['x'],graph.nodes[n]['y']) for n in (u,v)]),highway='residential')
    network=RoadNetwork(graph,provenance={'kind':'SYNTHETIC'})
    rows=[]
    for edge in network.edges.values():
        status='high_slowdown' if edge.edge_id=='2:3:0' else 'normal'
        for day in ('weekday','weekend'):
            for bucket in ('00-06','06-09','09-12','12-16','16-19','19-24'):
                rows.append({'edge_id':edge.edge_id,'day_group':day,'time_bucket':bucket,
                    'median_speed_kmh':10. if status=='high_slowdown' else 50.,'reference_speed_kmh':50.,
                    'static_speed_kmh':40.,'slowdown_ratio':.8 if status=='high_slowdown' else 0.,
                    'reference_source':'edge_p85','distinct_trips':5,'distinct_taxis':3,'distinct_dates':3,
                    'confidence':'supported_uncalibrated','status':status,'graph_version':network.graph_version,
                    'train_cutoff':datetime(2014,5,1,tzinfo=timezone.utc)})
    return network,rows,point,load_config(ROOT/'configs/default.yaml')


def calculate(network,rows,point,config,a,b):
    return recommend_coordinate_routes(network,rows,point(*a),point(*b),'weekday','00-06',config)


def test_destination_between_junctions_is_reached_and_final_red_segment_retained():
    network,rows,point,config=fixture_network()
    result=calculate(network,rows,point,config,(20,0),(140,0))
    features=serve_geojson(network,[r for r in rows if r['day_group']=='weekday' and r['time_bucket']=='00-06'])['features']
    for route in result['routes'].values():
        assert route['edge_ids']==['1:2:0','2:3:0']
        assert route['distance_m']==pytest.approx(120,abs=1e-5)
        assert route['estimated_eta_s']==pytest.approx(80/(50/3.6)+40/(10/3.6),abs=1e-5)
        assert route['snapped_coordinates']['B']==pytest.approx(point(140,0),abs=1e-10)
        assert route['endpoint_gaps_m']['B']<1e-5
        drawn=route_features(features,route['edge_ids'],route['segments'])['features']
        assert drawn[-1]['properties']['color']=='#de2d26'
        assert drawn[-1]['properties']['status']=='high_slowdown'
        assert drawn[-1]['geometry']['coordinates'][-1]==pytest.approx(point(140,0),abs=1e-10)
        assert route['segments'][-1]['distance_m']==pytest.approx(40,abs=1e-5)


@pytest.mark.parametrize('a,b,eid,color',[(120,170,'2:3:0','#de2d26'),(170,120,'3:2:0','#2ca25f')])
def test_same_road_opposite_directions_use_their_own_profile(a,b,eid,color):
    network,rows,point,config=fixture_network()
    result=calculate(network,rows,point,config,(a,0),(b,0))
    features=serve_geojson(network,[r for r in rows if r['day_group']=='weekday' and r['time_bucket']=='00-06'])['features']
    route=result['routes']['bucket']
    assert route['edge_ids']==[eid] and route['distance_m']==pytest.approx(50,abs=1e-5)
    assert route_features(features,route['edge_ids'],route['segments'])['features'][0]['properties']['color']==color


def test_one_way_backwards_requires_a_directed_loop_not_a_shortcut():
    network,rows,point,config=fixture_network(reverse=False)
    route=calculate(network,rows,point,config,(170,0),(120,0))['routes']['bucket']
    assert route['edge_ids']==['2:3:0','3:4:0','4:5:0','5:2:0','2:3:0']
    assert route['distance_m']==pytest.approx(350,abs=1e-5)
    for first,last in zip(route['segments'],route['segments'][1:]):
        assert first['geometry']['coordinates'][-1]==pytest.approx(last['geometry']['coordinates'][0],abs=1e-10)


def test_one_way_without_return_path_is_reported_unreachable():
    network,rows,point,config=fixture_network(reverse=False,cycle=False)
    with pytest.raises(ValueError,match='đúng chiều'):
        calculate(network,rows,point,config,(170,0),(120,0))


def test_off_road_destination_keeps_gap_separate_from_car_distance_and_eta():
    network,rows,point,config=fixture_network()
    result=calculate(network,rows,point,config,(20,0),(140,12))
    route=result['routes']['bucket']
    assert route['distance_m']==pytest.approx(120,abs=1e-4)
    assert route['endpoint_gaps_m']['B']==pytest.approx(12,abs=1e-4)
    assert route['snapped_coordinates']['B']==pytest.approx(point(140,0),abs=1e-9)
    assert result['requested_coordinates']['B']==list(point(140,12))
    with pytest.raises(ValueError,match='vượt giới hạn'):
        snap_candidates(network,*point(5000,5000))


def test_parallel_display_shows_both_colors_without_mutating_source_geometry():
    network,rows,point,config=fixture_network()
    profiles=[r for r in rows if r['day_group']=='weekday' and r['time_bucket']=='00-06']
    geojson=serve_geojson(network,profiles)
    original=json.dumps(geojson)
    views=index_views(profiles,geojson)
    view=views[('weekday','00-06')]
    base={f['properties']['edge_id']:f for f in view['map_features']}
    route={f['properties']['edge_id']:f for f in view['features']}
    assert base['2:3:0']['properties']['color']=='#de2d26'
    assert base['3:2:0']['properties']['color']=='#2ca25f'
    assert base['2:3:0']['geometry']!=base['3:2:0']['geometry']
    assert base['2:3:0']['geometry']!=route['2:3:0']['geometry']
    assert json.dumps(geojson)==original
    assert route['2:3:0']['geometry']==geojson['features'][next(i for i,f in enumerate(geojson['features']) if f['properties']['edge_id']=='2:3:0')]['geometry']


def test_app_renders_partial_final_edge_and_centered_markers(monkeypatch,tmp_path):
    from streamlit.testing.v1 import AppTest
    network,rows,point,config=fixture_network()
    network.save(tmp_path/'graph')
    write_profiles(tmp_path/'congestion_profiles.parquet',rows)
    write_json(tmp_path/'traffic.geojson',serve_geojson(network,rows))
    write_json(tmp_path/'pipeline_config.json',config);write_json(tmp_path/'coverage.json',{})
    import base64
    (tmp_path/'diagnostics.png').write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9XkAAAAASUVORK5CYII='))
    manifest={'run_id':'SYNTHETIC_EDGE_ENDPOINT_REGRESSION','graph_version':network.graph_version,
        'data_kind':'SYNTHETIC','status':'CANDIDATE_SYNTHETIC_TEST','cutoff_utc':'2014-05-01T00:00:00Z',
        'outputs_sha256':{p.relative_to(tmp_path).as_posix():sha256_file(p) for p in tmp_path.rglob('*') if p.is_file()}}
    write_json(tmp_path/'run_metadata.json',manifest)
    monkeypatch.setenv('PORTOFLOW_ARTIFACTS',str(tmp_path))
    app=AppTest.from_file(str(ROOT/'app/streamlit_app.py')).run(timeout=45)
    assert not app.exception
    app.radio[0].set_value('Chọn hành trình').run(timeout=45)
    a,b=point(20,0),point(140,12)
    for role,coordinates in (('a',a),('b',b)):
        app.session_state['route_'+role+'_lon']=coordinates[0]
        app.session_state['route_'+role+'_lat']=coordinates[1]
    app.run(timeout=45)
    assert not app.exception
    assert app.session_state['route_result']['routes']['bucket']['distance_m']==pytest.approx(120,abs=1e-4)
    assert any('B cách đường' in caption.value for caption in app.caption)
    assert any(metric.value=='0.12 km' for metric in app.metric)
