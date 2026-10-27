"""App-only directed routing to projected positions on edges, not nearby junctions.

Keep the frozen scientific package unchanged so saved Kaggle runs stay resumable.
Partial first/last edges use their own exact profile and proportional road length.
"""
import math

import networkx as nx
from shapely import transform
from shapely.geometry import Point, mapping
from shapely.ops import substring
from shapely.strtree import STRtree

from portoflow.route import edge_speed, profile_lookup

EPS=1e-6
DEFAULT_TIME_PRIORITY=.8


def snap_candidates(network,lon,lat,*,maximum_distance_m=300):
    if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in (lon,lat)) or not (-180<=lon<=180 and -90<=lat<=90):
        raise ValueError('Tọa độ A/B không hợp lệ')
    point=Point(*network.to_metric.transform(lon,lat))
    edges=list(network.edges.values()); geometries=[edge.metric_geometry for edge in edges]
    tree=STRtree(geometries)
    nearest=int(tree.nearest(point)); distance=point.distance(geometries[nearest])
    if distance>maximum_distance_m:
        raise ValueError(f'Điểm cách mạng đường {distance:.1f} m, vượt giới hạn {maximum_distance_m:g} m')
    # Include both coincident directions, never a substantially farther road.
    indices=tree.query(point.buffer(max(distance+.05,.05)))
    candidates=[]
    for index in indices:
        edge=edges[int(index)]; gap=point.distance(edge.metric_geometry)
        if gap<=distance+.05:
            offset=min(edge.length_m,max(0.,edge.metric_geometry.project(point)))
            projected=edge.metric_geometry.interpolate(offset)
            candidates.append({'edge_id':edge.edge_id,'offset_m':offset,'distance_m':gap,
                               'coordinate':list(network.to_wgs84.transform(projected.x,projected.y))})
    return sorted(candidates,key=lambda row:(row['distance_m'],row['edge_id']))


def _segment(edge,start,end):
    length=max(0.,end-start)
    if length<=EPS:
        return None
    return {'edge_id':edge.edge_id,'start_offset_m':start,'end_offset_m':end,'distance_m':length}


def _cost(network,segment,lookup,day,bucket,config,optimization,balance=None):
    if segment is None:
        return 0.
    edge=network.edges[segment['edge_id']]
    speed,unknown,_=edge_speed(edge,lookup.get((edge.edge_id,day,bucket)),
        'static' if optimization=='static' else 'bucket',config['route_rules']['fallback_speed_kmh'])
    seconds=segment['distance_m']/(speed/3.6)
    if optimization=='balanced':
        risk_seconds=seconds*(config['route_rules']['unknown_cost_multiplier'] if unknown else 1.)
        alpha=balance['time_priority']
        return alpha*risk_seconds/balance['reference_eta_s']+(1-alpha)*segment['distance_m']/balance['reference_distance_m']
    cost=segment['distance_m'] if optimization=='distance' else seconds
    return cost*config['route_rules']['unknown_cost_multiplier'] if optimization=='bucket' and unknown else cost


def _add(graph,u,v,segment,cost):
    tie=(segment['edge_id'],segment['start_offset_m'],segment['end_offset_m']) if segment else ('',0.,0.)
    old=graph.get_edge_data(u,v)
    if old is None or (cost,tie)<(old['weight'],old['tie']):
        graph.add_edge(u,v,weight=cost,tie=tie,segment=segment)


def _score(network,segments,lookup,day,bucket,config,model):
    distance=seconds=unknown=unknown_seconds=slow_distance=slow_delay=0.;unknown_edges=0
    for segment in segments:
        edge=network.edges[segment['edge_id']];length=segment['distance_m']
        speed,weak,_=edge_speed(edge,lookup.get((edge.edge_id,day,bucket)),model,
            config['route_rules']['fallback_speed_kmh'])
        duration=length/(speed/3.6)
        distance+=length;seconds+=duration
        if weak:
            unknown+=length;unknown_seconds+=duration;unknown_edges+=1
        profile=lookup.get((edge.edge_id,day,bucket))
        if profile and profile['status'] in {'slow','high_slowdown'}:
            slow_distance+=length
        if profile and profile['status']!='unknown' and profile.get('reference_speed_kmh'):
            slow_delay+=max(0.,duration-length/(profile['reference_speed_kmh']/3.6))
    return {'distance_m':distance,'estimated_eta_s':seconds,
        'unknown_eta_s':unknown_seconds,'slow_distance_m':slow_distance,
        'slow_distance_fraction':slow_distance/distance if distance else 0.,
        'relative_slowdown_delay_s':slow_delay,
        'unknown_distance_fraction':unknown/distance if distance else 0.,
        'unknown_edge_fraction':unknown_edges/len(segments) if segments else 0.}


def recommend_coordinate_routes(network,profiles,a,b,day,bucket,config,*,time_priority=DEFAULT_TIME_PRIORITY):
    if isinstance(time_priority,bool) or not isinstance(time_priority,(int,float)) or not math.isfinite(time_priority) or not 0<=time_priority<=1:
        raise ValueError('Time priority must be a finite preference between0and1')
    lookup=profile_lookup(profiles,network.graph_version)
    start=snap_candidates(network,*a);end=snap_candidates(network,*b)
    if not start or not end:
        raise ValueError('Không tìm thấy đoạn đường gần A/B')
    choices={};source='__PORTOFLOW_A__';target='__PORTOFLOW_B__';balance=None
    for optimization in ('distance','static','bucket','balanced'):
        graph=nx.DiGraph();graph.add_nodes_from(network.graph.nodes)
        def add(u,v,segment):
            _add(graph,u,v,segment,_cost(network,segment,lookup,day,bucket,config,optimization,balance))
        for edge in network.edges.values():
            add(edge.u,edge.v,_segment(edge,0.,edge.length_m))
        for candidate in start:
            edge=network.edges[candidate['edge_id']];offset=candidate['offset_m']
            if offset<=EPS:
                add(source,edge.u,None)
            if edge.length_m-offset<=EPS:
                add(source,edge.v,None)
            else:
                add(source,edge.v,_segment(edge,offset,edge.length_m))
        for candidate in end:
            edge=network.edges[candidate['edge_id']];offset=candidate['offset_m']
            if offset<=EPS:
                add(edge.u,target,None)
            else:
                add(edge.u,target,_segment(edge,0.,offset))
            if edge.length_m-offset<=EPS:
                add(edge.v,target,None)
        for first in start:
            for last in end:
                if first['edge_id']==last['edge_id'] and first['offset_m']<=last['offset_m']:
                    add(source,target,_segment(network.edges[first['edge_id']],first['offset_m'],last['offset_m']))
        try:
            nodes=nx.shortest_path(graph,source,target,weight='weight')
        except (nx.NetworkXNoPath,nx.NodeNotFound):
            raise ValueError('Không có tuyến ô tô đúng chiều giữa A và B trong mạng đường này') from None
        segments=[dict(graph[u][v]['segment']) for u,v in zip(nodes,nodes[1:]) if graph[u][v]['segment'] is not None]
        if not segments:
            raise ValueError('A và B trùng vị trí trên mạng đường. Hãy chọn hai điểm cách nhau hơn.')
        for segment in segments:
            edge=network.edges[segment['edge_id']]
            metric=substring(edge.metric_geometry,segment['start_offset_m'],segment['end_offset_m'])
            geometry=transform(metric,network.to_wgs84.transform,interleaved=False)
            segment['geometry']=mapping(geometry)
        snapped={'A':list(segments[0]['geometry']['coordinates'][0]),
                 'B':list(segments[-1]['geometry']['coordinates'][-1])}
        gaps={role:math.dist(network.to_metric.transform(*requested),network.to_metric.transform(*snapped[role]))
              for role,requested in (('A',a),('B',b))}
        choices[optimization]={'nodes':nodes[1:-1],'edge_ids':[s['edge_id'] for s in segments],
            'segments':segments,'snapped_coordinates':snapped,'endpoint_gaps_m':gaps,
            **_score(network,segments,lookup,day,bucket,config,'bucket'),
            'static_model_eta_s':_score(network,segments,lookup,day,bucket,config,'static')['estimated_eta_s']}
        if optimization=='distance':
            baseline=choices['distance']
            balance={'time_priority':float(time_priority),'reference_distance_m':baseline['distance_m'],
                     'reference_eta_s':baseline['estimated_eta_s'],
                     'unknown_cost_multiplier':config['route_rules']['unknown_cost_multiplier'],
                     'meaning':'User preference weights, not an accuracy/confidence claim or hard detour cap'}
    for route in choices.values():
        route['risk_adjusted_eta_s']=route['estimated_eta_s']+(balance['unknown_cost_multiplier']-1)*route['unknown_eta_s']
        route['balanced_score']=(time_priority*route['risk_adjusted_eta_s']/balance['reference_eta_s']+
                                 (1-time_priority)*route['distance_m']/balance['reference_distance_m'])
    proposed=choices['balanced'];baseline=choices['distance']
    recommendation={'route':'balanced','policy':balance,
        'eta_gain_vs_shortest_s':baseline['estimated_eta_s']-proposed['estimated_eta_s'],
        'extra_distance_vs_shortest_m':proposed['distance_m']-baseline['distance_m'],
        'extra_distance_vs_shortest_fraction':proposed['distance_m']/baseline['distance_m']-1,
        'source':'Historical bucket speeds encode slowdown; no extra penalty merely for red/yellow labels',
        'optimality':'Minimum weighted time-distance-risk cost on the directed snapshot graph, not verified real-world fastest travel'}
    return {'graph_version':network.graph_version,'day_group':day,'time_bucket':bucket,
        'requested_coordinates':{'A':list(a),'B':list(b)},'routes':choices,
        'recommendation':recommendation,
        'eta_comparison_model':'same_bucket_estimator_for_all_routes',
        'bucket_policy':'fixed_departure_bucket_for_whole_route',
        'endpoint_policy':'projected_position_on_nearest_directed_road_geometry',
        'connector_policy':'off-road gaps shown dashed and excluded from car distance/ETA',
        'interpretation':'Estimated ETA difference only; no realized travel-time savings measured'}
