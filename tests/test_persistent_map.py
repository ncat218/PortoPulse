"""Transport/reload and directional overlay regressions on synthetic geometry."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'app'))
from persistent_map import compact_roads, component_arguments, journey_overlay
from test_journey_endpoints import fixture_network, calculate
from portoflow.export import serve_geojson
from ui_logic import display_feature


def test_ack_sends_only_overlay_and_reload_requests_roads_again():
    network, rows, point, config = fixture_network()
    features = [display_feature(f) for f in serve_geojson(network, rows[:1])['features']]
    overlay = {'markers': [], 'route': []}
    call = lambda event, identity='SYNTHETIC_TRANSPORT': component_arguments(identity,event,features,overlay,[41,-8],'Chọn điểm A')
    first = call({})
    assert first['roads'] == compact_roads(features)
    warm = call({'dataset_id':'SYNTHETIC_TRANSPORT'})
    assert warm['roads'] is None and warm['overlay'] is overlay
    assert len(json.dumps(warm)) < len(json.dumps(first))
    assert call({'dataset_id':None,'kind':'request_roads'})['roads'] == first['roads']
    assert call({'dataset_id':'old_bucket'})['roads'] == first['roads']


def test_overlay_preserves_partial_red_edge_offroad_gap_and_marker_positions():
    network, rows, point, config = fixture_network()
    result = calculate(network,rows,point,config,(20,0),(140,12))
    rows = [row for row in rows if row['day_group']=='weekday' and row['time_bucket']=='00-06']
    features = [display_feature(f) for f in serve_geojson(network,rows)['features']]
    a,b = point(20,0),point(140,12)
    state = {'route_a_lon':a[0],'route_a_lat':a[1],'route_b_lon':b[0],'route_b_lat':b[1],'route_choice':'balanced'}
    overlay = journey_overlay(features,state,result,'SYNTHETIC_FIT')
    assert overlay['route'][-1][2:4] == ['high_slowdown','#de2d26']
    assert overlay['route'][-1][0] == result['routes']['balanced']['segments'][-1]['geometry']['coordinates']
    assert overlay['markers'][1]['lon'] == b[0] and overlay['markers'][1]['lat'] == b[1]
    assert overlay['connectors'][0][0] == [b[1],b[0]]
    assert [b[1],b[0]] in overlay['bounds']
    assert overlay['fit_id'] == 'SYNTHETIC_FIT'
