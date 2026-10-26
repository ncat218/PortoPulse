"""Two map modes and automatic A/B routing on precomputed historical profiles."""
import folium
import pandas as pd
import streamlit as st

from portoflow.graph import RoadNetwork
from journey_routing import recommend_coordinate_routes
from streamlit_folium import st_folium
from ui_logic import (ROUTE_LABELS,select_point,route_signature,
                      consume_map_event,points_ready,clear_journey,route_features,route_comparison,minimum_eta_routes)


@st.cache_resource(max_entries=2)
def load_route_network(folder,graph_version):
    from pathlib import Path
    network=RoadNetwork.load(Path(folder)/'graph')
    if network.graph_version!=graph_version:
        raise ValueError('Graph và profile không cùng phiên bản')
    return network


def mode_changed():
    state=st.session_state
    if state['app_mode']=='Bản đồ giao thông':
        state['route_pick_mode']='Xem bản đồ'
    elif state.get('route_a_lon') is None or state.get('route_a_lat') is None:
        state['route_pick_mode']='Chọn điểm A'
    elif state.get('route_b_lon') is None or state.get('route_b_lat') is None:
        state['route_pick_mode']='Chọn điểm B'
    else:
        state['route_pick_mode']='Xem bản đồ'


def invalidate_route():
    st.session_state.update(route_result=None,route_signature=None,route_attempt_signature=None,route_error=None)
    mode_changed()


def map_point_selected():
    # Observe view-only clicks too, so a later A/B click cannot replay an old
    # object event from the other mode. View-only mode never selects a point.
    if st.session_state.get('app_mode')!='Chọn hành trình':
        st.session_state['route_pick_mode']='Xem bản đồ'
    consume_map_event(st.session_state,st.session_state.get('porto_map',{}))


def pick_point(role):
    st.session_state['route_pick_mode']='Chọn điểm '+role


def swap_points():
    state=st.session_state
    a=(state['route_a_lon'],state['route_a_lat'])
    b=(state['route_b_lon'],state['route_b_lat'])
    select_point(state,'A',*b)
    select_point(state,'B',*a)


def coordinate_label(state,point):
    lat,lon=state['route_'+point+'_lat'],state['route_'+point+'_lon']
    return 'Chưa chọn' if lat is None or lon is None else f'{lat:.6f}, {lon:.6f}'


def render_view(metadata,profiles,features,config,root,day,bucket,selected,background_features=None):
    state=st.session_state
    if state.get('route_export')!=metadata['run_id']:
        clear_journey(state)
        state['route_export']=metadata['run_id']
        state['map_previous_events']={}
    st.radio('Chế độ',['Bản đồ giao thông','Chọn hành trình'],key='app_mode',
             horizontal=True,on_change=mode_changed)
    journey=state['app_mode']=='Chọn hành trình'
    if not journey:
        known=sum(row['status']!='unknown' for row in selected)
        slow=sum(row['status'] in {'slow','high_slowdown'} for row in selected)
        left,middle,right=st.columns(3)
        left.metric('Cạnh đã phân loại',f'{known}/{len(selected)}')
        middle.metric('Chưa xác định',len(selected)-known)
        right.metric('Chậm tương đối',slow)
        if known:
            st.caption(f'Trong {known:,} cạnh đã phân loại, {slow:,} cạnh chậm tương đối ({slow/known:.1%}). '
                       f'{len(selected)-known:,} cạnh có trạng thái chưa xác định.')
        else:
            st.caption('Tình trạng các cạnh trong khung giờ này chưa xác định.')
    else:
        a,b,actions=st.columns([2,2,1])
        with a:
            st.button('A · Điểm đi',on_click=pick_point,args=('A',),use_container_width=True,
                      type='primary' if state['route_pick_mode']=='Chọn điểm A' else 'secondary')
            st.caption(coordinate_label(state,'a'))
        with b:
            st.button('B · Điểm đến',on_click=pick_point,args=('B',),use_container_width=True,
                      type='primary' if state['route_pick_mode']=='Chọn điểm B' else 'secondary')
            st.caption(coordinate_label(state,'b'))
        with actions:
            st.button('Đổi A ↔ B',on_click=swap_points,disabled=not points_ready(state),use_container_width=True)
            st.button('Chọn lại',on_click=clear_journey,args=(state,),use_container_width=True)
        with st.expander('Nhập tọa độ A/B'):
            a,b=st.columns(2)
            for role,column in (('A',a),('B',b)):
                with column:
                    st.number_input('Kinh độ '+role,key='route_'+role.lower()+'_lon',value=None,
                        min_value=-180.,max_value=180.,format='%.6f',on_change=invalidate_route)
                    st.number_input('Vĩ độ '+role,key='route_'+role.lower()+'_lat',value=None,
                        min_value=-90.,max_value=90.,format='%.6f',on_change=invalidate_route)
        if state['route_pick_mode']!='Xem bản đồ':
            role='A' if state['route_pick_mode']=='Chọn điểm A' else 'B'
            st.info(f'Bấm lên bản đồ để chọn điểm {role}. Có đủ A và B, tuyến sẽ tự hiển thị.')

    request=route_signature(metadata['run_id'],day,bucket,state)
    if journey and points_ready(state) and state.get('route_attempt_signature')!=request:
        state.update(route_attempt_signature=request,route_result=None,route_error=None)
        try:
            with st.spinner('Đang gợi ý tuyến…'):
                network=load_route_network(str(root.resolve()),metadata['graph_version'])
                result=recommend_coordinate_routes(network,profiles,
                    (state['route_a_lon'],state['route_a_lat']),(state['route_b_lon'],state['route_b_lat']),
                    day,bucket,config)
                state.update(route_result=result,route_signature=request)
        except ValueError as exc:
            state.update(route_signature=None,route_error=str(exc))
    result=(state.get('route_result') if journey and points_ready(state)
            and state.get('route_signature')==request else None)
    if journey and state.get('route_attempt_signature')==request and state.get('route_error'):
        st.error(state['route_error'])
    if result:
        choice=st.selectbox('Tuyến hiển thị trên bản đồ',['bucket','distance','static'],key='route_choice',
                           format_func=lambda name:ROUTE_LABELS[name])
        chosen=result['routes'][choice]
        left,middle,right=st.columns(3)
        left.metric('Quãng đường',f"{chosen['distance_m']/1000:.2f} km")
        middle.metric('ETA ước lượng',f"{chosen['estimated_eta_s']/60:.1f} phút")
        right.metric('Quãng đường chưa xác định',f"{chosen['unknown_distance_fraction']:.1%}")
        comparisons,groups=route_comparison(result,choice)
        best_eta,leaders=minimum_eta_routes(result)
        multiplier=config['route_rules']['unknown_cost_multiplier']
        if choice=='bucket' and chosen['estimated_eta_s']>best_eta+1e-6:
            labels=' / '.join(ROUTE_LABELS[name] for name in leaders)
            st.info(f'ETA thấp nhất trong các phương án: {labels} ({best_eta/60:.4f} phút). '
                    f'Tuyến đang chọn còn xét độ phủ: thời gian trên đoạn chưa xác định chịu hệ số '
                    f'{multiplier:g} trong chi phí chọn tuyến, nên có thể có ETA cao hơn.')
        with st.expander('So sánh các phương án'):
            st.dataframe(pd.DataFrame(comparisons),hide_index=True,
                         column_order=['Hiển thị','route','Đường đi','Quãng đường (km)',
                                       'ETA ước lượng (phút)','Quãng đường chưa xác định (%)'],
                         column_config={
                             'Hiển thị':st.column_config.TextColumn('Bản đồ',width='small'),
                             'route':st.column_config.TextColumn('Phương án',width='medium'),
                             'Đường đi':st.column_config.TextColumn('Đường đi',width='small'),
                             'Quãng đường (km)':st.column_config.NumberColumn('km',format='%.4f',width='small'),
                             'ETA ước lượng (phút)':st.column_config.NumberColumn('ETA (phút)',format='%.4f',width='small'),
                             'Quãng đường chưa xác định (%)':st.column_config.NumberColumn('Chưa xác định (%)',format='%.2f',width='small')})
            for group,names in groups.items():
                if len(names)>1:
                    labels=' và '.join(ROUTE_LABELS[name] for name in names)
                    st.info(f'{labels} cùng đi trên {group}, nên số liệu trùng nhau.')
            st.info('Chênh lệch ETA là ước lượng từ dữ liệu lịch sử; chưa đo thời gian tiết kiệm thực tế.')
            st.caption('Tên phương án cho biết cách chọn đường; ETA của mọi phương án đều được ước lượng '
                       'bằng khung giờ đang xem. Cùng một đường đi sẽ có cùng số liệu so sánh.')
            st.caption(f'Tuyến theo khung giờ tối ưu chi phí có xét độ phủ: thời gian ước lượng trên đoạn chưa xác định '
                       f'được nhân {multiplier:g} khi chọn tuyến. ETA trong bảng là thời gian ước lượng chưa cộng phần phạt. '
                       'Giữ khung giờ khởi hành cho toàn tuyến.')
            st.caption('Tuyến được tính đến vị trí A/B trên đoạn đường gần nhất, có xét chiều xe chạy. '
                       'Các đường nhìn thấy trên bản đồ nền có thể không có cạnh đi được theo hướng đó trong graph.')
        st.markdown(f"**Đang hiển thị: {ROUTE_LABELS[choice]}** · "
                    f"{chosen['distance_m']/1000:.4f} km · ETA ước lượng {chosen['estimated_eta_s']/60:.4f} phút")
        st.caption('Định tuyến ô tô theo chiều cạnh đường trong mạng hiện có.')
        st.caption('Viền xanh dương là tuyến đang chọn; màu bên trong giữ tình trạng từng đoạn đường.')
        gaps=chosen['endpoint_gaps_m']
        if max(gaps.values())>.5:
            st.caption(f"A cách đường {gaps['A']:.1f} m · B cách đường {gaps['B']:.1f} m. "
                       'Nét đứt nối vị trí đã chọn tới đường; khoảng nối này không tính vào quãng đường ô tô hoặc ETA.')
    st.caption('Xanh: di chuyển tương đối bình thường · Vàng: chậm · Đỏ: chậm nhiều · Xám: Chưa xác định')
    st.caption('Hai chiều xe có thể khác màu; các nét song song thể hiện từng chiều. Tuyến dùng màu của đúng chiều đang đi.')
    center=([features[0]['geometry']['coordinates'][0][1],features[0]['geometry']['coordinates'][0][0]]
            if metadata['data_kind']=='SYNTHETIC' else [41.16,-8.63])
    map_view=folium.Map(center,zoom_start=14,prefer_canvas=True)
    fields=['edge_id','status_label','median_speed_kmh','reference_speed_kmh','distinct_trips','distinct_taxis','distinct_dates']
    aliases=['Mã cạnh','Tình trạng','Tốc độ ước lượng (km/h)','Tốc độ tham chiếu (km/h)','Số chuyến','Số taxi','Số ngày']
    ordered=sorted(background_features or features,key=lambda f:f['properties']['status']!='unknown')
    folium.GeoJson({'type':'FeatureCollection','features':ordered},name='Tình trạng đường',
        style_function=lambda f:{'color':f['properties']['color'],'weight':4,'opacity':0.85},
        tooltip=folium.GeoJsonTooltip(fields=['edge_id','status_label'],aliases=aliases[:2]),
        popup=folium.GeoJsonPopup(fields=fields,aliases=aliases)).add_to(map_view)
    if journey:
        for role,color in (('a','#2563eb'),('b','#7c3aed')):
            lon,lat=state['route_'+role+'_lon'],state['route_'+role+'_lat']
            if lon is not None and lat is not None:
                folium.Marker([lat,lon],tooltip='Điểm '+role.upper(),icon=folium.DivIcon(icon_size=(28,28),icon_anchor=(14,14),html=
                    '<div style="border-radius:50%;background:'+color+';color:white;width:28px;height:28px;'
                    'text-align:center;line-height:28px;font-weight:bold">'+role.upper()+'</div>')).add_to(map_view)
    if result:
        chosen=result['routes'][state['route_choice']]
        route=route_features(features,chosen['edge_ids'],chosen['segments'])
        folium.GeoJson(route,name='Viền tuyến',interactive=False,
            style_function=lambda f:{'color':'#2563eb','weight':11,'opacity':.95,'interactive':False}).add_to(map_view)
        folium.GeoJson(route,name='Tình trạng trên tuyến',
            style_function=lambda f:{'color':f['properties']['color'],'weight':5,'opacity':1},
            tooltip=folium.GeoJsonTooltip(fields=['edge_id','status_label'],aliases=aliases[:2]),
            popup=folium.GeoJsonPopup(fields=fields,aliases=aliases)).add_to(map_view)
        for role in ('A','B'):
            if chosen['endpoint_gaps_m'][role]>.5:
                requested=result['requested_coordinates'][role];snapped=chosen['snapped_coordinates'][role]
                folium.PolyLine([[requested[1],requested[0]],[snapped[1],snapped[0]]],color='#64748b',
                    weight=2,dash_array='5 5',tooltip='Khoảng nối tới đường · không tính vào ETA').add_to(map_view)
                folium.CircleMarker([snapped[1],snapped[0]],radius=3,color='#64748b',fill=True).add_to(map_view)
        bounds=[[lat,lon] for feature in route['features'] for lon,lat in feature['geometry']['coordinates']]
        bounds.extend([[lat,lon] for lon,lat in result['requested_coordinates'].values()])
        if bounds:
            map_view.fit_bounds(bounds,padding=[35,35])
    st_folium(map_view,key='porto_map',height=560,use_container_width=True,
        returned_objects=['last_clicked','last_object_clicked'],on_change=map_point_selected)
