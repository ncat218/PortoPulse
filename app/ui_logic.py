"""Presentation and point-selection helpers; no inference or map matching."""
import math

STATUS_LABELS = {'normal':'Di chuyển bình thường','slow':'Chậm',
    'high_slowdown':'Chậm nhiều','unknown':'Chưa xác định'}
ROUTE_LABELS = {'distance':'Ngắn nhất theo quãng đường','static':'Theo tốc độ trung bình',
    'bucket':'Theo khung giờ, có xét độ phủ'}


def display_feature(feature):
    properties = dict(feature['properties'])
    properties['status_label'] = STATUS_LABELS[properties['status']]
    return {**feature,'properties':properties}


MAP_PROPERTIES = ('edge_id','status','color','status_label','median_speed_kmh',
                  'reference_speed_kmh','distinct_trips','distinct_taxis','distinct_dates')


def index_views(profiles,geojson):
    """Index once; send only fields used by map popups. Coordinates stay exact.

    Callers treat the index and source rows as read-only cached resources.
    Full profile records remain available for road detail, charts and routing.
    """
    from road_display import separate_direction_geometries
    views={};geometries={};first_features={}
    for row in profiles:
        key=(row['day_group'],row['time_bucket'])
        views.setdefault(key,{'rows':[],'features':[]})['rows'].append(row)
    for original in geojson['features']:
        shown=display_feature(original)
        properties=shown['properties']
        key=(properties['day_group'],properties['time_bucket'])
        eid=properties['edge_id']
        geometry=geometries.setdefault(eid,shown['geometry'])
        if geometry!=shown['geometry']:
            raise ValueError('Road geometry changed between time buckets')
        first_features.setdefault(eid,original)
        views[key]['features'].append({'type':'Feature','geometry':geometry,
            'properties':{name:properties[name] for name in MAP_PROPERTIES}})
    display_geometries=separate_direction_geometries(list(first_features.values()))
    for view in views.values():
        view['map_features']=[{**f,'geometry':display_geometries[f['properties']['edge_id']]} for f in view['features']]
    return views


def select_point(state,role,lon,lat):
    if role not in {'A','B'} or not all(isinstance(x,(float,int)) and math.isfinite(x) for x in (lon,lat)):
        raise ValueError('Chọn điểm A hoặc B với tọa độ hợp lệ')
    if not (-180<=lon<=180 and -90<=lat<=90):
        raise ValueError('Tọa độ nằm ngoài phạm vi kinh độ/vĩ độ')
    state['route_'+role.lower()+'_lon'] = float(lon)
    state['route_'+role.lower()+'_lat'] = float(lat)
    state['route_result'] = None
    state['route_signature'] = None
    state['route_attempt_signature'] = None
    state['route_error'] = None


def points_ready(state):
    values=[state.get('route_'+point+'_'+axis) for point in ('a','b') for axis in ('lon','lat')]
    return (all(isinstance(x,(float,int)) and math.isfinite(x) for x in values)
            and all(-180<=values[i]<=180 and -90<=values[i+1]<=90 for i in (0,2)))


def clear_journey(state):
    for point in ('a','b'):
        for axis in ('lon','lat'):
            state['route_'+point+'_'+axis]=None
    state.update(route_result=None,route_signature=None,route_attempt_signature=None,
                 route_error=None,route_pick_mode='Chọn điểm A',route_choice='bucket')


def route_features(features,edge_ids,segments=None):
    """The route core keeps the exact exported color of each directed edge."""
    lookup={feature['properties']['edge_id']:feature for feature in features}
    if segments is None:
        return {'type':'FeatureCollection','features':[lookup[eid] for eid in edge_ids]}
    if edge_ids!=[segment['edge_id'] for segment in segments]:
        raise ValueError('Route segments differ from selected directed edge IDs')
    return {'type':'FeatureCollection','features':[
        {**lookup[segment['edge_id']],'geometry':segment['geometry']} for segment in segments]}


def route_signature(run_id,day,bucket,state):
    return ('edge_endpoints_v2',run_id,day,bucket,*(state['route_'+point+'_'+axis] for point in ('a','b') for axis in ('lon','lat')))


def consume_map_event(state,event):
    """Road layers emit object-click events; bare map emits last_clicked."""
    if not isinstance(event,dict):
        return False
    fields=('last_clicked','last_object_clicked')
    previous=state.get('map_previous_events',{})
    points=[event.get(field) for field in fields if event.get(field) and event.get(field)!=previous.get(field)]
    state['map_previous_events']={field:event.get(field) for field in fields}
    mode=state.get('route_pick_mode')
    if not points or mode not in {'Chọn điểm A','Chọn điểm B'}:
        return False
    point=points[-1]
    role='A' if mode=='Chọn điểm A' else 'B'
    select_point(state,role,point['lng'],point['lat'])
    if points_ready(state):
        state['route_pick_mode']='Xem bản đồ'
    else:
        state['route_pick_mode']='Chọn điểm B' if role=='A' else 'Chọn điểm A'
    return True


def route_table(result):
    return [{'route':ROUTE_LABELS[name],
        'Quãng đường (km)':row['distance_m']/1000,
        'ETA ước lượng (phút)':row['estimated_eta_s']/60,
        'Quãng đường chưa xác định (%)':100*row['unknown_distance_fraction']}
        for name,row in result['routes'].items()]


def route_comparison(result,selected):
    """Identify genuinely equal directed paths; never invent alternatives."""
    routes=result['routes']
    if selected not in routes:
        raise ValueError('Unknown selected route')
    path_ids={}
    groups={}
    rows=[]
    for (name,route),row in zip(routes.items(),route_table(result)):
        path=(tuple((s['edge_id'],round(s['start_offset_m'],6),round(s['end_offset_m'],6)) for s in route['segments'])
              if 'segments' in route else tuple(route['edge_ids']))
        number=path_ids.setdefault(path,len(path_ids)+1)
        group=f'Tuyến {number}'
        groups.setdefault(group,[]).append(name)
        rows.append({**row,'Đường đi':group,'Hiển thị':'Đang xem' if name==selected else ''})
    return rows,groups


def minimum_eta_routes(result):
    """Lowest displayed ETA among the computed candidates, not a global claim."""
    best=min(route['estimated_eta_s'] for route in result['routes'].values())
    names=[name for name,route in result['routes'].items()
           if math.isclose(route['estimated_eta_s'],best,rel_tol=0,abs_tol=1e-6)]
    return best,names
