"""Synthetic count audit: never turn a support deficit into a measured color."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_coverage_gaps import audit_profiles
from test_journey_endpoints import fixture_network


def fixture():
    network, rows, point, config = fixture_network()
    config['profile_rules'].update(min_distinct_trips=3,min_distinct_taxis=2,min_distinct_dates=2)
    for row in rows:
        if row['edge_id']=='1:2:0':
            row.update(status='unknown',distinct_trips=0,distinct_taxis=0,distinct_dates=0,median_speed_kmh=None)
        elif row['edge_id']=='2:3:0':
            row.update(status='unknown',distinct_trips=2,distinct_taxis=1,distinct_dates=1)
        elif row['edge_id']=='3:2:0':
            row.update(status='unknown',reference_speed_kmh=None)
    return network,rows,config


def test_disjoint_reasons_overlap_and_optimistic_counts_without_mutation():
    network,rows,config=fixture();original=copy.deepcopy(rows)
    report=audit_profiles(rows,config,network.edges,network.graph_version)
    assert rows==original and report['status']=='DIAGNOSIS_ONLY_NO_NEW_COVERAGE'
    assert report['never_visited_in_any_bucket_edges']==1
    for bucket in report['buckets'].values():
        assert bucket['unknown']==3
        assert bucket['exclusive_unknown_reasons']==dict(no_accepted_visits=1,insufficient_support=1,missing_valid_reference=1)
        assert bucket['near_support_edges']==1
        assert bucket['overlapping_support_failures']['distinct_trips']==2
        assert sum(bucket['exclusive_unknown_reasons'].values())==bucket['unknown']


@pytest.mark.parametrize('change',['duplicate','missing','graph'])
def test_reject_changed_denominator_duplicates_or_graph(change):
    network,rows,config=fixture()
    if change=='duplicate': rows.append(dict(rows[0]))
    elif change=='missing': rows.pop()
    else: rows[0]['graph_version']='wrong'
    with pytest.raises(ValueError): audit_profiles(rows,config,network.edges,network.graph_version)
