"""Two map modes and automatic A/B routing on precomputed historical profiles."""
import pandas as pd
import streamlit as st

from portoflow.graph import RoadNetwork
from journey_routing import recommend_coordinate_routes,PreparedRouting
from persistent_map import render_map, journey_overlay
from ui_logic import (ROUTE_LABELS,select_point,route_signature,
                      consume_map_event,points_ready,clear_journey,route_comparison,minimum_eta_routes,route_speed_details)


@st.cache_resource(max_entries=2,show_spinner=False)
def load_route_network(folder,graph_version):
    from pathlib import Path
    network=RoadNetwork.load(Path(folder)/'graph')
    if network.graph_version!=graph_version:
        raise ValueError('Graph và profile không cùng phiên bản')
    return network


@st.cache_resource(max_entries=2,show_spinner=False)
def load_route_context(folder,graph_version,profile_sha,_profiles):
    return PreparedRouting(load_route_network(folder,graph_version),_profiles)


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


def render_route_analysis(result,chosen,selected,config,root,metadata):
    comparisons,groups=route_comparison(result,st.session_state['route_choice'])
    with st.expander('So sánh tiêu chí chọn tuyến'):
        st.dataframe(pd.DataFrame(comparisons).round(2),hide_index=True)
        st.caption(f'{len(groups)} đường đi khác nhau từ bốn tiêu chí. ETA được ước lượng cùng khung giờ; '
                   'chưa đo thời gian tiết kiệm thực tế.')
        priority=result['recommendation']['policy']['time_priority']
        st.caption(f'Mức ưu tiên hiện tại: thời gian {priority:.0%}, quãng đường {1-priority:.0%}. '
                   'Đây là sở thích đánh đổi, không phải độ chính xác của ETA.')
    with st.expander('Tốc độ và ETA từng đoạn'):
        network=load_route_network(str(root.resolve()),metadata['graph_version'])
        rows=route_speed_details(network,selected,chosen,config)
        speed_labels={'supported_bucket_estimate':'Lịch sử theo khung giờ',
            'training_static_proxy':'Dự phòng từ tốc độ gộp', 'maxspeed_weak_proxy':'Tham chiếu từ bản đồ',
            'configured_unknown_fallback':'Tốc độ dự phòng cấu hình'}
        reference_labels={'edge_p85':'P85 của đoạn đường','class_night_p85':'P85 ban đêm của nhóm đường',
            'maxspeed_weak_proxy':'Tham chiếu từ bản đồ'}
        for row in rows:
            row['Nguồn tốc độ']=speed_labels.get(row['Nguồn tốc độ'],row['Nguồn tốc độ'])
            row['Nguồn tham chiếu']=reference_labels.get(row['Nguồn tham chiếu'],row['Nguồn tham chiếu'])
        st.dataframe(pd.DataFrame(rows).round(2),hide_index=True)
        st.caption('ETA cộng thời gian từng đoạn, chưa cộng phạt thiếu dữ liệu. '
                   'Màu so với mức tham chiếu, là proxy cần kiểm chứng khi có giá trị bất thường.')


@st.fragment
def render_view(metadata,profiles,features,config,root,day,bucket,selected,background_features=None,show_details=False):
    state=st.session_state
    if state.get('route_export')!=metadata['run_id']:
        clear_journey(state);state['route_export']=metadata['run_id'];state['map_previous_events']={}
    result=None;chosen=None
    # Fixed container paths keep the map mounted while controls/results change.
    with st.container():
        st.radio('Chế độ',['Bản đồ giao thông','Chọn hành trình'],key='app_mode',horizontal=True,on_change=mode_changed)
        journey=state['app_mode']=='Chọn hành trình'
        if journey:
            a,b,actions=st.columns([2,2,1])
            for role,column in (('A',a),('B',b)):
                with column:
                    st.button(role+' · '+('Điểm đi' if role=='A' else 'Điểm đến'),on_click=pick_point,args=(role,),
                        use_container_width=True,type='primary' if state['route_pick_mode']=='Chọn điểm '+role else 'secondary')
                    st.caption(coordinate_label(state,role.lower()))
            with actions:
                st.button('Đổi A ↔ B',on_click=swap_points,disabled=not points_ready(state),use_container_width=True)
                st.button('Chọn lại',on_click=clear_journey,args=(state,),use_container_width=True)
            with st.expander('Tùy chọn hành trình'):
                a,b=st.columns(2)
                for role,column in (('A',a),('B',b)):
                    with column:
                        st.number_input('Kinh độ '+role,key='route_'+role.lower()+'_lon',value=None,
                            min_value=-180.,max_value=180.,format='%.6f',on_change=invalidate_route)
                        st.number_input('Vĩ độ '+role,key='route_'+role.lower()+'_lat',value=None,
                            min_value=-90.,max_value=90.,format='%.6f',on_change=invalidate_route)
                st.slider('Ưu tiên thời gian',min_value=0,max_value=100,value=80,step=5,format='%d%%',
                    key='route_time_priority',on_change=invalidate_route)
                st.caption('Mức cao hơn ưu tiên ETA lịch sử; mức thấp hơn hạn chế đi vòng. Đây là mức ưu tiên, không phải độ chính xác của ETA.')
            status=st.empty()
            request=route_signature(metadata['run_id'],day,bucket,state)
            if points_ready(state) and state.get('route_attempt_signature')!=request:
                state.update(route_attempt_signature=request,route_result=None,route_error=None)
                try:
                    with status.container():
                        with st.spinner('Đang tìm tuyến…'):
                            context=load_route_context(str(root.resolve()),metadata['graph_version'],
                                metadata['outputs_sha256']['congestion_profiles.parquet'],profiles)
                            route=recommend_coordinate_routes(context.network,context.profiles,
                                (state['route_a_lon'],state['route_a_lat']),(state['route_b_lon'],state['route_b_lat']),
                                day,bucket,config,time_priority=state.get('route_time_priority',80)/100,prepared=context)
                    state.update(route_result=route,route_signature=request,route_choice='balanced')
                except ValueError as exc:
                    state.update(route_signature=None,route_error=str(exc))
            result=(state.get('route_result') if points_ready(state) and state.get('route_signature')==request else None)
            if result:
                choice=st.selectbox('Tuyến trên bản đồ',['balanced','bucket','distance','static'],key='route_choice',
                                    format_func=lambda name:ROUTE_LABELS[name])
                chosen=result['routes'][choice]
                rec=result['recommendation'];extra=max(0,rec['extra_distance_vs_shortest_m']);gain=rec['eta_gain_vs_shortest_s']
                summary=('Tuyến đề xuất trùng đường ngắn nhất.' if extra<.5 else
                         f'Đề xuất đi thêm {extra:.0f} m; ETA giảm {gain:.1f} giây.' if gain>=0 else
                         f'Đề xuất đi thêm {extra:.0f} m; ETA tăng {-gain:.1f} giây khi cân nhắc phần thiếu dữ liệu.')
                status.caption(summary+' Ước lượng theo dữ liệu lịch sử.')
            elif state.get('route_error') and state.get('route_attempt_signature')==request:
                status.error(state['route_error'])
            else:
                role='A' if state['route_pick_mode']=='Chọn điểm A' else 'B'
                status.caption(f'Click một lần trên bản đồ để chọn {role}.')
            left,middle,right=st.columns(3)
            left.metric('Quãng đường',f"{chosen['distance_m']/1000:.2f} km" if chosen else '—')
            middle.metric('ETA ước lượng',f"{chosen['estimated_eta_s']/60:.1f} phút" if chosen else '—')
            right.metric('Thiếu dữ liệu trên tuyến',f"{chosen['unknown_distance_fraction']:.1%}" if chosen else '—')
        else:
            with st.expander('Độ phủ dữ liệu trong khung giờ'):
                known=sum(row['status']!='unknown' for row in selected)
                left,middle,right=st.columns(3)
                left.metric('Cạnh đã phân loại',f'{known}/{len(selected)}')
                middle.metric('Chưa xác định',len(selected)-known)
                right.metric('Chậm tương đối',sum(row['status'] in {'slow','high_slowdown'} for row in selected))
    with st.container():
        center=([features[0]['geometry']['coordinates'][0][1],features[0]['geometry']['coordinates'][0][0]]
                if metadata['data_kind']=='SYNTHETIC' else [41.16,-8.63])
        dataset_id='|'.join(('persistent_v1',metadata['run_id'],metadata['graph_version'],
            metadata.get('outputs_sha256',{}).get('traffic.geojson',''),day,bucket))
        overlay=(journey_overlay(features,state,result,repr((request,state['route_choice'])) if result else None)
                 if journey else {'markers':[],'route':[],'connectors':[],'bounds':[],'fit_id':None})
        render_map(dataset_id,background_features or features,overlay,center,
                   state['route_pick_mode'] if journey else 'Xem bản đồ',map_point_selected)
        st.caption('Xanh: gần mức tham chiếu · Vàng: giảm tốc · Đỏ: giảm tốc mạnh · Xám: thiếu dữ liệu. Viền xanh dương: tuyến đang xem.')
        if chosen and max(chosen['endpoint_gaps_m'].values())>.5:
            gaps=chosen['endpoint_gaps_m']
            st.caption(f"A cách đường {gaps['A']:.1f} m · B cách đường {gaps['B']:.1f} m. Nét đứt nối tới đường không tính vào ETA ô tô.")
    if show_details and result:
        with st.container():render_route_analysis(result,chosen,selected,config,root,metadata)
