"""Two map modes and automatic A/B routing on precomputed historical profiles."""
import pandas as pd
import streamlit as st

from portoflow.graph import RoadNetwork
from journey_routing import recommend_coordinate_routes
from persistent_map import render_map, journey_overlay
from ui_logic import (ROUTE_LABELS,select_point,route_signature,
                      consume_map_event,points_ready,clear_journey,route_comparison,minimum_eta_routes,route_speed_details)


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


@st.fragment
def render_view(metadata,profiles,features,config,root,day,bucket,selected,background_features=None):
    # Keep the map at a fixed fragment/container path when controls change.
    with st.container():
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
            with st.expander('Độ phủ dữ liệu trong khung giờ'):
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
            with st.expander('Ưu tiên thời gian hay quãng đường'):
                st.slider('Ưu tiên thời gian',min_value=0,max_value=100,value=80,step=5,format='%d%%',
                          key='route_time_priority',on_change=invalidate_route)
                st.caption('Giá trị cao hơn ưu tiên ETA lịch sử; thấp hơn hạn chế đi vòng. '
                           'Đây là mức đánh đổi bạn chọn, không phải độ chính xác hoặc độ tin cậy của ETA.')
            if state['route_pick_mode']!='Xem bản đồ':
                role='A' if state['route_pick_mode']=='Chọn điểm A' else 'B'
                st.info(f'Click một lần lên bản đồ để chọn điểm {role}. '
                        'Sau A, click tiếp để chọn B; có đủ hai điểm, tuyến sẽ tự hiển thị.')

        request=route_signature(metadata['run_id'],day,bucket,state)
        if journey and points_ready(state) and state.get('route_attempt_signature')!=request:
            state.update(route_attempt_signature=request,route_result=None,route_error=None)
            try:
                with st.spinner('Đang gợi ý tuyến…'):
                    network=load_route_network(str(root.resolve()),metadata['graph_version'])
                    result=recommend_coordinate_routes(network,profiles,
                        (state['route_a_lon'],state['route_a_lat']),(state['route_b_lon'],state['route_b_lat']),
                        day,bucket,config,time_priority=state.get('route_time_priority',80)/100)
                    state.update(route_result=result,route_signature=request,route_choice='balanced')
            except ValueError as exc:
                state.update(route_signature=None,route_error=str(exc))
        result=(state.get('route_result') if journey and points_ready(state)
                and state.get('route_signature')==request else None)
        if journey and state.get('route_attempt_signature')==request and state.get('route_error'):
            st.error(state['route_error'])
        if result:
            proposal=result['routes']['balanced'];recommendation=result['recommendation']
            gain=recommendation['eta_gain_vs_shortest_s'];extra=max(0.,recommendation['extra_distance_vs_shortest_m'])
            extra_fraction=max(0.,recommendation['extra_distance_vs_shortest_fraction'])
            change=f'giảm {gain:.1f} giây' if gain>=.5 else f'tăng {-gain:.1f} giây' if gain<=-.5 else 'gần như không đổi'
            st.markdown('**Tuyến đề xuất · cân bằng thời gian và quãng đường**')
            if extra<.5:
                st.info('Đề xuất giữ tuyến ngắn nhất theo mức ưu tiên đang chọn. '
                        'ETA theo tốc độ lịch sử và độ phủ được công bố để bạn đánh giá.')
            else:
                st.info(f'Đề xuất đi thêm {extra:.0f} m (+{extra_fraction:.1%}) so với tuyến ngắn nhất; '
                        f'ETA ước lượng {change}. Kết quả cân bằng thời gian, quãng đường và phần chưa xác định.')
            alternate=result['routes']['bucket']
            if alternate['estimated_eta_s']<proposal['estimated_eta_s']-.5 and alternate['distance_m']>proposal['distance_m']+.5:
                st.caption(f"Tuyến ưu tiên ETA ước lượng nhanh hơn {proposal['estimated_eta_s']-alternate['estimated_eta_s']:.1f} giây, "
                           f"nhưng dài thêm {alternate['distance_m']-proposal['distance_m']:.0f} m "
                           f"(+{alternate['distance_m']/proposal['distance_m']-1:.1%}) so với đề xuất cân bằng.")
            choice=st.selectbox('Tuyến trên bản đồ',['balanced','bucket','distance','static'],key='route_choice',
                               format_func=lambda name:ROUTE_LABELS[name])
            chosen=result['routes'][choice]
            left,middle,right=st.columns(3)
            left.metric('Quãng đường',f"{chosen['distance_m']/1000:.2f} km")
            middle.metric('ETA ước lượng',f"{chosen['estimated_eta_s']/60:.1f} phút")
            right.metric('Quãng đường chưa xác định',f"{chosen['unknown_distance_fraction']:.1%}")
            st.caption(f"Vận tốc hiệu dụng ước lượng: {3.6*chosen['distance_m']/chosen['estimated_eta_s']:.1f} km/h. "
                       'Màu giảm tốc so với mức tham chiếu, không phải trạng thái đóng đường.')
            st.caption(f"Trên tuyến đang xem: {chosen['slow_distance_m']:.0f} m qua các đoạn chậm tương đối "
                       f"({chosen['slow_distance_fraction']:.1%} quãng đường). Tình trạng chậm đã được phản ánh bằng tốc độ lịch sử trong ETA.")
            comparisons,groups=route_comparison(result,choice)
            best_eta,leaders=minimum_eta_routes(result)
            multiplier=config['route_rules']['unknown_cost_multiplier']
            if choice=='bucket' and chosen['estimated_eta_s']>best_eta+1e-6:
                labels=' / '.join(ROUTE_LABELS[name] for name in leaders)
                st.info(f'ETA thấp nhất trong các phương án: {labels} ({best_eta/60:.4f} phút). '
                        f'Tuyến đang chọn còn xét độ phủ: thời gian trên đoạn chưa xác định chịu hệ số '
                        f'{multiplier:g} trong chi phí chọn tuyến, nên có thể có ETA cao hơn.')
            with st.expander('So sánh tiêu chí chọn tuyến'):
                st.dataframe(pd.DataFrame(comparisons),hide_index=True,
                             column_order=['Hiển thị','route','Đường đi','Quãng đường (km)',
                                           'Đi vòng so với ngắn nhất (%)','ETA ước lượng (phút)',
                                           'ETA giảm so với ngắn nhất (giây)','Quãng đường chưa xác định (%)'],
                             column_config={
                                 'Hiển thị':st.column_config.TextColumn('Bản đồ',width='small'),
                             'route':st.column_config.TextColumn('Tiêu chí',width='medium'),
                                 'Đường đi':st.column_config.TextColumn('Đường đi',width='small'),
                                 'Quãng đường (km)':st.column_config.NumberColumn('km',format='%.4f',width='small'),
                                 'ETA ước lượng (phút)':st.column_config.NumberColumn('ETA (phút)',format='%.4f',width='small'),
                                 'Đi vòng so với ngắn nhất (%)':st.column_config.NumberColumn('Đi vòng (%)',format='%.2f',width='small'),
                                 'ETA giảm so với ngắn nhất (giây)':st.column_config.NumberColumn('Giảm ETA (giây)',format='%.1f',width='small'),
                                 'Quãng đường chưa xác định (%)':st.column_config.NumberColumn('Chưa xác định (%)',format='%.2f',width='small')})
                if len(groups)==1:
                    st.info('Cả bốn tiêu chí đang chọn cùng một đường đi. '
                            'Bảng này so sánh cách chọn tuyến; không phải bốn đường khác nhau.')
                else:
                    st.caption(f'{len(groups)} đường đi khác nhau từ bốn tiêu chí chọn tuyến.')
                    for group,names in groups.items():
                        if len(names)>1:
                            labels=' và '.join(ROUTE_LABELS[name] for name in names)
                            st.info(f'{labels} cùng đi trên {group}, nên số liệu trùng nhau.')
                st.info('Chênh lệch ETA là ước lượng từ dữ liệu lịch sử; chưa đo thời gian tiết kiệm thực tế.')
                st.caption('Tên phương án cho biết cách chọn đường; ETA của mọi phương án đều được ước lượng '
                           'bằng khung giờ đang xem. Cùng một đường đi sẽ có cùng số liệu so sánh.')
                priority=result['recommendation']['policy']['time_priority']
                st.caption(f'Đề xuất cân bằng dùng trọng số thời gian {priority:.0%}, quãng đường {1-priority:.0%}, '
                           'chuẩn hóa theo tuyến ngắn nhất của chính A/B. Đây là sở thích đánh đổi, không phải bảo đảm độ chính xác; '
                           'không đặt trần cứng cho tỷ lệ đi vòng.')
                st.caption(f'Đề xuất cân bằng và tuyến ưu tiên ETA cùng xét độ phủ: thời gian ước lượng trên đoạn chưa xác định '
                           f'được nhân {multiplier:g} khi chọn tuyến. ETA trong bảng là thời gian ước lượng chưa cộng phần phạt. '
                           'Giữ khung giờ khởi hành cho toàn tuyến.')
                st.caption('Tuyến được tính đến vị trí A/B trên đoạn đường gần nhất, có xét chiều xe chạy. '
                           'Các đường nhìn thấy trên bản đồ nền có thể không có cạnh đi được theo hướng đó trong graph.')
            st.markdown(f"**Đang hiển thị: {ROUTE_LABELS[choice]}** · "
                        f"{chosen['distance_m']/1000:.4f} km · ETA ước lượng {chosen['estimated_eta_s']/60:.4f} phút")
            st.caption('Định tuyến ô tô theo chiều cạnh đường trong mạng hiện có.')
            with st.expander('Tốc độ và ETA từng đoạn'):
                route_network=load_route_network(str(root.resolve()),metadata['graph_version'])
                st.dataframe(pd.DataFrame(route_speed_details(route_network,selected,chosen,config)),hide_index=True)
                st.caption('ETA là tổng thời gian các đoạn, dùng đúng vận tốc trong bảng. '
                           'Màu so tốc độ lịch sử với mức tham chiếu; tham chiếu là proxy và có thể bất thường. '
                           'Không cộng phần phạt thiếu dữ liệu vào ETA hiển thị.')
            st.caption('Viền xanh dương là tuyến đang chọn; màu bên trong giữ tình trạng từng đoạn đường.')
            gaps=chosen['endpoint_gaps_m']
            if max(gaps.values())>.5:
                st.caption(f"A cách đường {gaps['A']:.1f} m · B cách đường {gaps['B']:.1f} m. "
                           'Nét đứt nối vị trí đã chọn tới đường; khoảng nối này không tính vào quãng đường ô tô hoặc ETA.')
        st.caption('Xanh: di chuyển tương đối bình thường · Vàng: chậm · Đỏ: chậm nhiều · Xám: Chưa xác định')
        st.caption('Hai chiều xe có thể khác màu; các nét song song thể hiện từng chiều. Tuyến dùng màu của đúng chiều đang đi.')
        center=([features[0]['geometry']['coordinates'][0][1],features[0]['geometry']['coordinates'][0][0]]
                if metadata['data_kind']=='SYNTHETIC' else [41.16,-8.63])
        dataset_id='|'.join(('persistent_v1',metadata['run_id'],metadata['graph_version'],
            metadata.get('outputs_sha256',{}).get('traffic.geojson',''),day,bucket))
        overlay=(journey_overlay(features,state,result,repr((request,state['route_choice'])) if result else None)
                 if journey else {'markers':[],'route':[],'connectors':[],'bounds':[],'fit_id':None})
    with st.container():
        render_map(dataset_id,background_features or features,overlay,center,
                   state['route_pick_mode'] if journey else 'Xem bản đồ',map_point_selected)
