"""Read-only diagnosis of fixed-graph unknown profiles; never fill their colors.

This audits exported support counts, not raw GPS independence or matching QC.
Additional trips/taxis/dates must be genuine train evidence before the cutoff.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path

import pyarrow.parquet as pq

from portoflow.graph import RoadNetwork
from portoflow.storage import sha256_file, verify_checkpoint


def audit_profiles(rows, config, expected_edges, graph_version):
    rules = config['profile_rules']
    dimensions = ('distinct_trips', 'distinct_taxis', 'distinct_dates')
    thresholds = {key: rules['min_'+key] for key in dimensions}
    groups = defaultdict(dict)
    for row in rows:
        if row['graph_version'] != graph_version or row['edge_id'] not in expected_edges:
            raise ValueError('Profile graph mismatch')
        group = groups[(row['day_group'], row['time_bucket'])]
        if row['edge_id'] in group:
            raise ValueError('Duplicate edge/bucket')
        group[row['edge_id']] = row
    hours = config['time']['bucket_boundaries_hour']
    keys = {(day, f'{a:02d}-{b:02d}') for day in ('weekday', 'weekend') for a,b in zip(hours,hours[1:])}
    if set(groups) != keys or any(set(group) != set(expected_edges) for group in groups.values()):
        raise ValueError('Every bucket must retain the entire fixed graph denominator')
    buckets, candidates = {}, []
    for key, group in sorted(groups.items()):
        reasons = Counter(); failures = Counter(); known = near = 0
        for row in group.values():
            missing = [name for name in dimensions if row[name] < thresholds[name]]
            speed_ok = row['median_speed_kmh'] is not None and math.isfinite(row['median_speed_kmh']) and row['median_speed_kmh'] > 0
            ref_ok = row['reference_speed_kmh'] is not None and math.isfinite(row['reference_speed_kmh']) and row['reference_speed_kmh'] > 0
            if row['status'] != 'unknown':
                if missing or not speed_ok or not ref_ok:
                    raise ValueError('Classified profile lacks the configured support/speed/reference')
                known += 1
                continue
            for reason in missing:
                failures[reason] += 1
            if row['distinct_trips'] == 0:
                reasons['no_accepted_visits'] += 1
            elif missing:
                reasons['insufficient_support'] += 1
            elif not speed_ok:
                reasons['missing_valid_speed'] += 1
            elif not ref_ok:
                reasons['missing_valid_reference'] += 1
            else:
                reasons['other_requires_checkpoint_review'] += 1
            deficits = {name: max(0, thresholds[name]-row[name]) for name in dimensions}
            if missing and row['distinct_trips'] > 0 and max(deficits.values()) <= 1 and speed_ok and ref_ok:
                near += 1
                candidates.append({'bucket': '/'.join(key), 'edge_id': row['edge_id'],
                    'highway': expected_edges[row['edge_id']].highway,
                    'length_m': expected_edges[row['edge_id']].length_m,
                    **{name: row[name] for name in dimensions}, 'deficits': deficits})
        total = len(group)
        buckets['/'.join(key)] = {'edges': total, 'known': known, 'unknown': total-known,
            'known_fraction': known/total, 'needed_for_80pct': max(0, math.ceil(.8*total)-known),
            'exclusive_unknown_reasons': dict(reasons), 'overlapping_support_failures': dict(failures),
            'near_support_edges': near,
            'optimistic_fraction_if_all_near_support_received_valid_new_evidence': (known+near)/total}
    never = [eid for eid in expected_edges if all(group[eid]['distinct_trips'] == 0 for group in groups.values())]
    return {'status': 'DIAGNOSIS_ONLY_NO_NEW_COVERAGE', 'fixed_directed_edges': len(expected_edges),
        'graph_version': graph_version, 'thresholds': thresholds, 'buckets': buckets,
        'never_visited_in_any_bucket_edges': len(never),
        'never_visited_road_classes': dict(Counter(expected_edges[eid].highway for eid in never)),
        'near_support_examples': sorted(candidates, key=lambda r: (-r['length_m'], r['bucket'], r['edge_id']))[:100],
        'limits': ['Counts taken from verified exported profiles; raw identity independence not re-audited.',
            'Near-support counts are optimistic targeting diagnostics, not available extra observations.',
            'No labels, thresholds, graph, train cutoff or serving files were changed.',
            'Holdout observations must never be merged into train profiles.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    metadata = verify_checkpoint(args.export)
    config = json.loads((args.export/'pipeline_config.json').read_text(encoding='utf-8'))
    network = RoadNetwork.load(args.export/'graph')
    if metadata['graph_version'] != network.graph_version:
        raise ValueError('Export graph mismatch')
    columns = ['edge_id','day_group','time_bucket','status','distinct_trips','distinct_taxis',
               'distinct_dates','median_speed_kmh','reference_speed_kmh','graph_version']
    table = pq.read_table(args.export/'congestion_profiles.parquet')
    cutoff = datetime.fromisoformat(config['split']['train_cutoff_utc'].replace('Z','+00:00'))
    if set(table.column('train_cutoff').unique().to_pylist()) != {cutoff}:
        raise ValueError('Profile train cutoff mismatch')
    report = audit_profiles(table.select(columns).to_pylist(), config, network.edges, network.graph_version)
    report['source_manifest_sha256'] = sha256_file(args.export/'run_metadata.json')
    report['profile_sha256'] = sha256_file(args.export/'congestion_profiles.parquet')
    report['data_kind'] = metadata['data_kind']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status','fixed_directed_edges','never_visited_in_any_bucket_edges')}, indent=2))


if __name__ == '__main__':
    main()
