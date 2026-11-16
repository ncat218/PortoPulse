"""Traffic map and A/B journey controls over precomputed historical profiles."""
from html import escape

import pandas as pd
import streamlit as st

from portoflow.graph import RoadNetwork
from portoflow.export import COLORS
from journey_routing import recommend_coordinate_routes,PreparedRouting
from persistent_map import render_map, journey_overlay
from ui_logic import (ROUTE_LABELS, clear_journey, clear_point, consume_map_event,
                      points_ready, reset_route, route_comparison, route_signature,
                      route_speed_details, select_point)


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


def update_coordinate(key):
    state = st.session_state
    state[key] = state['_'+key]
    reset_route(state)
    mode_changed()


def update_priority():
    state = st.session_state
    state['route_time_priority'] = state['_route_time_priority']


def request_route():
    state = st.session_state
    reset_route(state)
    state.update(route_requested=True, route_pick_mode='Xem bản đồ')


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
    state['route_pick_mode'] = 'Xem bản đồ'


def coordinate_label(state,point):
    lat,lon=state['route_'+point+'_lat'],state['route_'+point+'_lon']
    return None if lat is None or lon is None else f'{lat:.5f}, {lon:.5f}'


def render_route_analysis(chosen,selected,config,root,metadata):
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


def render_journey_controls(state):
    st.subheader('Lập hành trình')
    for role, label in (('A', 'Điểm đi'), ('B', 'Điểm đến')):
        active = state['route_pick_mode'] == f'Chọn điểm {role}'
        coordinate = coordinate_label(state, role.lower())
        caption = coordinate or ('Nhấn bản đồ để chọn' if active else 'Chọn trên bản đồ')
        with st.container(key=f'point-{role.lower()}-{"active" if active else "idle"}'):
            label_slot, clear_slot = st.columns([2, 1], gap='small', vertical_alignment='center')
            label_slot.button(f'{role} · {label}', key=f'pick_{role}', on_click=pick_point, args=(role,))
            if coordinate:
                clear_slot.button(f'Xóa {role}', key=f'clear_{role}', on_click=clear_point,
                                  args=(state, role), type='tertiary', help=f'Xóa điểm {role}')
            st.caption(caption)
    swap, clear = st.columns(2)
    swap.button('Đổi A ↔ B', on_click=swap_points, disabled=not points_ready(state), width='stretch')
    clear.button('Chọn lại', on_click=clear_journey, args=(state,), width='stretch')
    st.button('Tìm tuyến đường', key='find_route', type='primary', width='stretch',
              disabled=not points_ready(state), on_click=request_route)


def render_journey_options(state):
    with st.expander('Tùy chọn hành trình'):
        for role in ('A', 'B'):
            st.markdown(f'**Điểm {role}**')
            for axis, label, limit in (('lon', 'Kinh độ', 180.), ('lat', 'Vĩ độ', 90.)):
                key = f'route_{role.lower()}_{axis}'
                state['_'+key] = state[key]
                st.number_input(f'{label} {role}', key='_'+key, min_value=-limit,
                                max_value=limit, format='%.6f', on_change=update_coordinate, args=(key,))
        state['_route_time_priority'] = state.get('route_time_priority', 80)
        st.slider('Ưu tiên thời gian', min_value=0, max_value=100, step=5, format='%d%%',
                  key='_route_time_priority', on_change=update_priority)
        st.caption('Mức cao hơn ưu tiên ETA lịch sử. Mức thấp hơn hạn chế đi vòng.')


def find_journey(state, metadata, profiles, config, root, day, bucket, request):
    if state.get('route_requested') and points_ready(state) and state.get('route_attempt_signature') != request:
        state.update(route_attempt_signature=request, route_result=None, route_error=None)
        try:
            with st.spinner('Đang tìm tuyến…'):
                context = load_route_context(str(root.resolve()), metadata['graph_version'],
                                             metadata['outputs_sha256']['congestion_profiles.parquet'], profiles)
                route = recommend_coordinate_routes(
                    context.network, context.profiles,
                    (state['route_a_lon'], state['route_a_lat']), (state['route_b_lon'], state['route_b_lat']),
                    day, bucket, config, time_priority=state.get('route_time_priority', 80)/100, prepared=context)
            state.update(route_result=route, route_signature=request)
        except ValueError as exc:
            state.update(route_signature=None, route_error=str(exc))
    if state.get('route_signature') == request:
        return state['route_result']
    if state.get('route_error') and state.get('route_attempt_signature') == request:
        st.error(state['route_error'])
    return None


def update_route_choice():
    st.session_state['route_choice'] = st.session_state['_route_choice']


def update_comparison_route(name):
    state = st.session_state
    state['comparison_routes'] = {
        **state.get('comparison_routes', {}), name: state[f'_compare_{name}'],
    }


def render_route_comparison(result, state):
    state['_route_choice'] = state['route_choice']
    with st.expander('So sánh tuyến'):
        choice = st.selectbox('Tuyến trên bản đồ', ['balanced', 'bucket', 'distance', 'static'],
                              key='_route_choice', format_func=ROUTE_LABELS.get, on_change=update_route_choice)
        comparisons, groups = route_comparison(result, choice)
        widths = [2.8, .65, .8, .8, .8, .9, .8, .7]
        headers = ('Phương án', 'Đường đi', 'Quãng đường (km)', 'ETA (phút)',
                   'Đi vòng (%)', 'ETA giảm (giây)', 'Thiếu dữ liệu (%)', 'Hiển thị')
        for column, label in zip(st.columns(widths, gap='small'), headers):
            column.caption(label)
        for name, row in zip(result['routes'], comparisons):
            columns = st.columns(widths, gap='small', vertical_alignment='center')
            values = (
                row['route'], row['Đường đi'], f"{row['Quãng đường (km)']:.2f}",
                f"{row['ETA ước lượng (phút)']:.2f}", f"{row['Đi vòng so với ngắn nhất (%)']:.2f}",
                f"{row['ETA giảm so với ngắn nhất (giây)']:.2f}", f"{row['Quãng đường chưa xác định (%)']:.2f}",
            )
            for column, value in zip(columns, values):
                column.caption(value)
            label = f"Hiển thị {ROUTE_LABELS[name]}"
            if name == choice:
                columns[-1].checkbox(label, value=True, disabled=True, label_visibility='collapsed',
                                     key=f'current_route_{name}')
            else:
                key = f'_compare_{name}'
                state[key] = state.get('comparison_routes', {}).get(name, False)
                columns[-1].checkbox(label, key=key, label_visibility='collapsed',
                                     on_change=update_comparison_route, args=(name,))
        st.caption('Viền đứt nâu đánh dấu phần tách nhánh của tuyến so sánh. '
                   'Màu bên trong theo trạng thái giao thông của từng đoạn.')
        st.caption(f'{len(groups)} đường đi khác nhau từ bốn tiêu chí. ETA dùng cùng khung giờ lịch sử.')
        priority = result['recommendation']['policy']['time_priority']
        st.caption(f'Ưu tiên thời gian {priority:.0%} · Quãng đường {1-priority:.0%}.')


@st.fragment
def render_view(metadata,profiles,features,config,root,day,bucket,selected,background_features=None,show_details=False):
    state = st.session_state
    if state.get('route_export') != metadata['run_id']:
        clear_journey(state)
        state.update(route_export=metadata['run_id'], map_previous_events={})

    with st.container(key='map-navigation'):
        st.radio('Chế độ', ['Bản đồ giao thông', 'Chọn hành trình'], key='app_mode',
                 horizontal=True, on_change=mode_changed, label_visibility='collapsed')
    journey = state['app_mode'] == 'Chọn hành trình'
    result = chosen = None
    controls, map_column = st.columns([0.29, 0.71], gap='medium')
    with controls, st.container(key='map-panel', border=True):
        if journey:
            render_journey_controls(state)
            request = route_signature(metadata['run_id'], day, bucket, state)
            result = find_journey(state, metadata, profiles, config, root, day, bucket, request)
            if result:
                choice = state['route_choice']
                chosen = result['routes'][choice]
                st.divider()
                st.markdown(f"**{ROUTE_LABELS[choice]}**")
                st.metric('ETA ước lượng', f"{chosen['estimated_eta_s']/60:.1f} phút")
                distance, unknown = st.columns(2)
                distance.metric('Quãng đường', f"{chosen['distance_m']/1000:.2f} km")
                unknown.metric('Thiếu dữ liệu', f"{chosen['unknown_distance_fraction']:.1%}")
                if choice == 'balanced':
                    rec = result['recommendation']
                    extra = max(0, rec['extra_distance_vs_shortest_m'])
                    gain = rec['eta_gain_vs_shortest_s']
                    if extra < .5:
                        st.caption('Tuyến đề xuất trùng đường ngắn nhất.')
                    else:
                        st.caption(f"Đi thêm {extra:.0f} m · ETA {'giảm' if gain >= 0 else 'tăng'} {abs(gain):.1f} giây so với tuyến ngắn nhất.")
            render_journey_options(state)
        else:
            st.subheader('Tình trạng giao thông')
            st.caption('Chọn một đoạn đường trên bản đồ để xem tốc độ và số lượt quan sát.')
            with st.expander('Độ phủ dữ liệu trong khung giờ'):
                known = sum(row['status'] != 'unknown' for row in selected)
                st.metric('Cạnh đã phân loại', f'{known:,}/{len(selected):,}')
                st.metric('Chưa xác định', f'{len(selected)-known:,}')
                st.metric('Chậm tương đối', f"{sum(row['status'] in {'slow','high_slowdown'} for row in selected):,}")

    with map_column, st.container(key='porto-map-frame'):
        center = ([features[0]['geometry']['coordinates'][0][1], features[0]['geometry']['coordinates'][0][0]]
                  if metadata['data_kind'] == 'SYNTHETIC' else [41.16, -8.63])
        dataset_id = '|'.join(('persistent_v1', metadata['run_id'], metadata['graph_version'],
            metadata.get('outputs_sha256', {}).get('traffic.geojson', ''), day, bucket))
        overlay = journey_overlay(features, state, result, repr((request, state['route_choice'])) if result else None)
        if not journey:
            overlay['markers'] = []
        render_map(dataset_id, background_features or features, overlay, center,
                   state['route_pick_mode'] if journey else 'Xem bản đồ', map_point_selected)
        legend = {'normal': 'Gần mức tham chiếu', 'slow': 'Giảm tốc',
                  'high_slowdown': 'Giảm tốc mạnh', 'unknown': 'Thiếu dữ liệu'}
        items = ''.join(f'<span><i style="background:{COLORS[key]}"></i>{escape(label)}</span>'
                        for key, label in legend.items())
        st.html(f'<div class="traffic-legend" aria-label="Chú giải giao thông">{items}</div>')
        if chosen:
            st.caption('Viền xanh dương đánh dấu tuyến đang xem.')
            gaps = chosen['endpoint_gaps_m']
            if max(gaps.values()) > .5:
                st.caption(f"A cách đường {gaps['A']:.1f} m · B cách đường {gaps['B']:.1f} m. Nét đứt xám nối tới đường không tính vào ETA ô tô.")
            render_route_comparison(result, state)
    if show_details and result:
        render_route_analysis(chosen, selected, config, root, metadata)
