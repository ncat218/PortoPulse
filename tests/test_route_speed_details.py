"""Displayed segment speeds must sum to the existing ETA, including unknowns."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from ui_logic import route_speed_details
from test_journey_endpoints import fixture_network,calculate


@pytest.mark.parametrize('unknown',[False,True])
def test_partial_segment_explanation_uses_actual_speed_fallback_and_eta(unknown):
    network,rows,point,config=fixture_network()
    if unknown:
        for row in rows:
            if row['edge_id']=='2:3:0':row['status']='unknown'
    route=calculate(network,rows,point,config,(20,0),(140,0))['routes']['balanced']
    selected=[row for row in rows if row['day_group']=='weekday' and row['time_bucket']=='00-06']
    details=route_speed_details(network,selected,route,config)
    assert sum(row['Mét đi qua'] for row in details)==pytest.approx(route['distance_m'])
    assert sum(row['Thời gian đoạn (giây)'] for row in details)==pytest.approx(route['estimated_eta_s'])
    assert details[-1]['Vận tốc tính ETA (km/h)']==(40 if unknown else 10)
    assert details[-1]['Dùng dự phòng']==unknown
