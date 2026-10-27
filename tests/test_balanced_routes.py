"""Synthetic checks that traffic-aware recommendations weigh time and detours."""
import math
import sys
from pathlib import Path

import networkx as nx
import pytest
from pyproj import Transformer
from shapely.geometry import LineString

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from journey_routing import recommend_coordinate_routes
from ui_logic import route_table,ROUTE_LABELS
from portoflow.config import load_config
from portoflow.graph import RoadNetwork


def corridors(short_length,short_seconds,alternatives):
    forward=Transformer.from_crs('EPSG:4326','EPSG:32629',always_xy=True)
    inverse=Transformer.from_crs('EPSG:32629','EPSG:4326',always_xy=True)
    x,y=forward.transform(-8.63,41.16)
    point=lambda dx,dy:inverse.transform(x+dx,y+dy)
    graph=nx.MultiDiGraph(crs='EPSG:4326')
    for node,coord in ((1,point(0,0)),(2,point(short_length,0))):
        graph.add_node(node,x=coord[0],y=coord[1])
    graph.add_edge(1,2,key=0,highway='residential',geometry=LineString([point(0,0),point(short_length,0)]))
    durations={(1,2):short_seconds};paths=[['1:2:0']]
    for index,(length,seconds) in enumerate(alternatives):
        node=index+3
        height=math.sqrt((length/2)**2-(short_length/2)**2)*(1 if index%2==0 else -1)
        middle=point(short_length/2,height);graph.add_node(node,x=middle[0],y=middle[1])
        for u,v in ((1,node),(node,2)):
            graph.add_edge(u,v,key=0,highway='residential',geometry=LineString([
                (graph.nodes[n]['x'],graph.nodes[n]['y']) for n in (u,v)]))
            durations[(u,v)]=seconds/2
        paths.append([f'1:{node}:0',f'{node}:2:0'])
    network=RoadNetwork(graph,provenance={'kind':'SYNTHETIC'})
    rows=[]
    for edge in network.edges.values():
        speed=edge.length_m/durations[(edge.u,edge.v)]*3.6;ratio=speed/60
        status='high_slowdown' if ratio<.4 else 'slow' if ratio<.7 else 'normal'
        rows.append({'edge_id':edge.edge_id,'day_group':'weekday','time_bucket':'09-12',
            'graph_version':network.graph_version,'median_speed_kmh':speed,'static_speed_kmh':40.,
            'reference_speed_kmh':60.,'status':status})
    return network,rows,point(0,0),point(short_length,0),paths,load_config(ROOT/'configs/default.yaml')


def solve(fixture,priority=.8):
    network,rows,a,b,paths,config=fixture
    return recommend_coordinate_routes(network,rows,a,b,'weekday','09-12',config,time_priority=priority)


def test_screenshot_tradeoff_does_not_recommend_230m_detour_for_8seconds_by_default():
    fixture=corridors(1039.5,3.5194*60,[(1269.9,3.3832*60)])
    result=solve(fixture);routes=result['routes']
    assert routes['distance']['distance_m']==pytest.approx(1039.5,abs=1e-4)
    assert routes['bucket']['distance_m']==pytest.approx(1269.9,abs=1e-4)
    assert routes['distance']['estimated_eta_s']-routes['bucket']['estimated_eta_s']==pytest.approx(8.172,abs=1e-4)
    assert routes['balanced']['edge_ids']==fixture[4][0]
    assert result['recommendation']['extra_distance_vs_shortest_fraction']==pytest.approx(0,abs=1e-8)
    assert routes['balanced']['balanced_score']<routes['bucket']['balanced_score']
    assert result['recommendation']['policy']['time_priority']==.8
    displayed=next(row for row in route_table(result) if row['route']==ROUTE_LABELS['bucket'])
    assert displayed['Đi vòng so với ngắn nhất (%)']==pytest.approx((1269.9/1039.5-1)*100,abs=1e-5)
    assert displayed['ETA giảm so với ngắn nhất (giây)']==pytest.approx(8.172,abs=1e-4)


def test_preference_changes_the_tradeoff_transparently():
    fixture=corridors(1039.5,3.5194*60,[(1269.9,3.3832*60)])
    assert solve(fixture,.95)['routes']['balanced']['edge_ids']==fixture[4][1]
    assert solve(fixture,0)['routes']['balanced']['edge_ids']==fixture[4][0]
    assert solve(fixture,1)['routes']['balanced']['edge_ids']==solve(fixture,1)['routes']['bucket']['edge_ids']


def test_changing_historical_slowdown_changes_recommendation_on_same_geometry():
    fixture=corridors(1000,120,[(1200,140)])
    network,rows,a,b,paths,config=fixture
    before=solve(fixture)
    assert before['routes']['balanced']['edge_ids']==paths[0]
    direct=next(r for r in rows if r['edge_id']=='1:2:0')
    direct.update(median_speed_kmh=5.,status='high_slowdown')
    after=solve(fixture)
    assert after['routes']['balanced']['edge_ids']==paths[1]
    assert after['recommendation']['eta_gain_vs_shortest_s']>500
    assert after['routes']['balanced']['relative_slowdown_delay_s']<after['routes']['distance']['relative_slowdown_delay_s']


def test_balanced_search_finds_middle_route_absent_from_the_three_baselines():
    fixture=corridors(1000,300,[(2500,100),(1250,160)])
    routes=solve(fixture)['routes'];paths=fixture[4]
    assert routes['distance']['edge_ids']==routes['static']['edge_ids']==paths[0]
    assert routes['bucket']['edge_ids']==paths[1]
    assert routes['balanced']['edge_ids']==paths[2]
    assert routes['balanced']['balanced_score']<min(routes[key]['balanced_score'] for key in ('distance','static','bucket'))


def test_unknown_proxy_is_exposed_and_receives_existing_risk_penalty():
    fixture=corridors(1000,180,[(1250,90)])
    for row in fixture[1]:
        if row['edge_id']!='1:2:0':
            row.update(status='unknown',median_speed_kmh=None,static_speed_kmh=50.)
    result=solve(fixture)
    for route in result['routes'].values():
        assert route['risk_adjusted_eta_s']==pytest.approx(route['estimated_eta_s']+route['unknown_eta_s'])
    assert result['routes']['balanced']['edge_ids']==fixture[4][0]
    assert result['routes']['balanced']['unknown_distance_fraction']==0


@pytest.mark.parametrize('priority',[-.1,1.1,float('nan'),float('inf'),True])
def test_invalid_preference_cannot_create_invalid_dijkstra_costs(priority):
    with pytest.raises(ValueError,match='Time priority'):
        solve(corridors(1000,120,[(1200,100)]),priority)
