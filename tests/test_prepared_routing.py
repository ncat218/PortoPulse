"""Prepared resource reuse must preserve routing policy/outputs exactly."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import journey_routing as routing
from test_journey_endpoints import fixture_network


@pytest.mark.parametrize('reverse,cycle,priority',[(True,True,.8),(False,True,.95),(True,False,0.)])
def test_prepared_and_original_paths_scores_endpoints_are_identical(reverse,cycle,priority):
    network,rows,point,config=fixture_network(reverse=reverse,cycle=cycle)
    context=routing.PreparedRouting(network,rows)
    a,b=point(20,0),point(140,12)
    expected=routing.recommend_coordinate_routes(network,rows,a,b,'weekday','00-06',config,time_priority=priority)
    actual=routing.recommend_coordinate_routes(network,rows,a,b,'weekday','00-06',config,time_priority=priority,prepared=context)
    assert actual==expected
    assert routing.snap_candidates(network,*a,prepared=context)==routing.snap_candidates(network,*a)


def test_request_reuses_profile_lookup_and_spatial_index(monkeypatch):
    network,rows,point,config=fixture_network();context=routing.PreparedRouting(network,rows)
    def forbidden(*args,**kwargs):raise AssertionError('must reuse prepared resources')
    monkeypatch.setattr(routing,'profile_lookup',forbidden);monkeypatch.setattr(routing,'STRtree',forbidden)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda _:routing.recommend_coordinate_routes(network,rows,point(20,0),point(140,0),
            'weekday','00-06',config,prepared=context),range(2)))
    assert results[0]==results[1]


def test_mismatched_prepared_profile_source_rejected():
    network,rows,point,config=fixture_network();context=routing.PreparedRouting(network,rows)
    with pytest.raises(ValueError,match='mismatch'):
        routing.recommend_coordinate_routes(network,list(rows),point(20,0),point(140,0),'weekday','00-06',config,prepared=context)
