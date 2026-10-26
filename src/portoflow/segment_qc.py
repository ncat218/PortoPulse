"""Conservative, auditable partial-block policy; never relabel a partial trip success."""
from collections import defaultdict
from datetime import timedelta
import math


def usable_traversals(trip, result, network, config, plan):
    """Validate complete 15s gaps, directed offsets, residuals and block boundaries.

    Complete-trip baseline and segment-policy evidence are both returned. A gap
    cannot cross an uncovered interval. Partial blocks lose one gap at each end;
    after trimming they must contain >=3 consecutive gaps. Support keeps the
    ORIGINAL trip/taxi identity. These are QC checks, not ground-truth validation.
    """
    gaps = defaultdict(list)
    errors = defaultdict(int)
    residuals = result.get('residuals_m', [])
    if (result['status'] not in {'success', 'partial'} or not residuals or
            any(not math.isfinite(v) or v < 0 for v in residuals) or
            sorted(residuals)[len(residuals)//2] > config['matching']['max_median_residual_m'] or
            max(residuals) > config['matching']['candidate_radius_m'] + 1e-5):
        return [], [], {'rejection': 'status_or_candidate_residual', 'accepted_gaps': 0}
    for row in result['traversals']:
        gaps[row['gap_index']].append(row)
    valid = {}
    for index, rows in sorted(gaps.items()):
        try:
            if type(index) is not int or not 0 <= index < len(trip.coordinates)-1:
                raise ValueError('gap_index')
            cursor = trip.start_utc + timedelta(seconds=15*index)
            start = cursor
            previous = None
            distance = 0.0
            for row in rows:
                edge = network.edges[row['edge_id']]
                a, b = row['start_offset_m'], row['end_offset_m']
                if (row['trip_id'] != trip.trip_id or row['taxi_id'] != trip.taxi_id or
                        row['graph_version'] != network.graph_version or
                        not all(math.isfinite(v) for v in (a,b,row['traveled_distance_m'])) or
                        not -1e-5 <= a <= b <= edge.length_m+1e-5 or
                        abs(row['traveled_distance_m']-(b-a)) > 1e-4 or
                        abs((row['estimated_entry_utc']-cursor).total_seconds()) > 1e-5 or
                        row['estimated_exit_utc'] < cursor):
                    raise ValueError('identity_geometry_time')
                if previous is not None:
                    old, old_b = previous
                    if old.edge_id == edge.edge_id:
                        if abs(old_b-a)>1e-4:
                            raise ValueError('disconnected_offsets')
                    elif old.v != edge.u or abs(old_b-old.length_m)>1e-4 or abs(a)>1e-4:
                        raise ValueError('disconnected_edges')
                cursor = row['estimated_exit_utc']
                previous = edge,b
                distance += row['traveled_distance_m']
            if abs((cursor-start).total_seconds()-15)>1e-5:
                raise ValueError('gap_conservation')
            if distance/15*3.6 > config['matching']['max_gap_speed_kmh']:
                raise ValueError('gap_speed')
            valid[index] = rows
        except (ValueError, KeyError, TypeError) as exc:
            errors[str(exc)] += 1
    # Split at missing gaps AND at discontinuous matched positions between gaps.
    blocks = []
    for index, rows in sorted(valid.items()):
        connected = False
        if blocks and blocks[-1][-1]+1 == index:
            last = valid[blocks[-1][-1]][-1]
            first = rows[0]
            old, new = network.edges[last['edge_id']], network.edges[first['edge_id']]
            connected = ((old.edge_id == new.edge_id and abs(last['end_offset_m']-first['start_offset_m'])<1e-4)
                or (old.v == new.u and abs(last['end_offset_m']-old.length_m)<1e-4 and abs(first['start_offset_m'])<1e-4))
        if connected:
            blocks[-1].append(index)
        else:
            blocks.append([index])
    complete = (result['status']=='success' and len(valid)==len(trip.coordinates)-1 and len(blocks)==1)
    full_rows = [r for block in blocks for i in block for r in valid[i]] if complete else []
    accepted = []
    if complete:
        accepted = blocks
    elif (result['status']=='partial' and plan['partial_policy']=='validated_blocks_v1' and
            len(valid)/(len(trip.coordinates)-1) >= plan['partial_minimum_gap_fraction']):
        trim = plan['partial_boundary_trim_gaps']
        accepted = [b[trim:-trim] for b in blocks if len(b)-2*trim >= plan['partial_minimum_block_gaps']]
    selected = []
    for block_index, block in enumerate(accepted):
        for index in block:
            for row in valid[index]:
                selected.append(dict(row, matched_subtrajectory_id=f'{trip.trip_id}:qc:{block_index}',
                    match_quality='success' if complete else 'partial_validated_block'))
    return full_rows, selected, {'complete_trip_qc': complete, 'valid_gaps': len(valid),
        'accepted_gaps': sum(map(len,accepted)), 'block_count':len(accepted), 'rejected_gaps':dict(errors),
        'policy':plan['partial_policy'], 'original_match_status':result['status']}
