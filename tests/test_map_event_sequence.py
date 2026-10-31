"""Click identity, replay protection and same-position selection regressions."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from ui_logic import clear_journey,consume_map_event


def event(sequence,kind='click'):
    return dict(instance='SYNTHETIC_IFRAME',sequence=sequence,kind=kind,
                last_clicked=dict(lng=-8.63,lat=41.16) if kind=='click' else None)


def test_click_consumed_once_and_new_same_position_click_can_select_b():
    state={};clear_journey(state)
    assert consume_map_event(state,event(1))
    assert state['route_pick_mode']=='Chọn điểm B' and state['route_a_lon']==-8.63
    assert not consume_map_event(state,event(1)) and state['route_b_lon'] is None
    assert consume_map_event(state,event(2))
    assert state['route_b_lon']==-8.63 and state['route_pick_mode']=='Xem bản đồ'


def test_ready_and_view_only_events_never_replay_as_new_point():
    state={};clear_journey(state)
    assert not consume_map_event(state,event(1,'ready'))
    assert state['route_a_lon'] is None
    state['route_pick_mode']='Xem bản đồ'
    assert not consume_map_event(state,event(2))
    state['route_pick_mode']='Chọn điểm A'
    assert not consume_map_event(state,event(2))
    assert consume_map_event(state,event(3))


def test_clearing_points_allows_a_new_click_at_previous_location():
    state={};clear_journey(state)
    assert consume_map_event(state,event(1))
    clear_journey(state)
    assert consume_map_event(state,event(2))
    assert state['route_a_lat']==41.16 and state['route_pick_mode']=='Chọn điểm B'
