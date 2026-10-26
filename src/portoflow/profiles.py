"""Exact per-trip statistics on a disk-backed evidence ledger, without all-GPS lists."""
import sqlite3
from collections import defaultdict
from statistics import median

from .congestion import parse_maxspeed, quantile, validate_rules


def open_evidence(path):
    db=sqlite3.connect(path)
    db.execute('PRAGMA temp_store=FILE')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS applied(batch_id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS evidence(trip_id TEXT,taxi_id INTEGER,edge_id TEXT,local_date TEXT,
            day_group TEXT,bucket TEXT,distance REAL,duration REAL,complete INTEGER,highway TEXT,
            PRIMARY KEY(trip_id,edge_id,local_date,day_group,bucket));
        CREATE INDEX IF NOT EXISTS evidence_edge ON evidence(edge_id);
        CREATE INDEX IF NOT EXISTS evidence_night ON evidence(highway,bucket);
    ''')
    return db


def apply_observations(db,batch_id,rows,network,cutoff):
    """Exactly-once committed batch ingestion; holdout is NEVER a profile input."""
    if db.execute('SELECT 1 FROM applied WHERE batch_id=?',(batch_id,)).fetchone():
        return False
    grouped=defaultdict(lambda:[0.,0.])
    for r in rows:
        if r['split']!='train':
            continue
        if r['estimated_exit_utc']>=cutoff or r['graph_version']!=network.graph_version:
            raise ValueError('Temporal leakage or graph mismatch in evidence')
        if r['quality_flag']!='accepted_inferred':
            continue
        key=(r['trip_id'],r['taxi_id'],r['edge_id'],str(r['local_date']),r['day_group'],r['time_bucket'],
             int(r['complete_trip_evidence']),network.edges[r['edge_id']].highway)
        grouped[key][0]+=r['traveled_distance_m']
        grouped[key][1]+=r['observed_or_inferred_duration_s']
    with db:
        for key,(distance,duration) in grouped.items():
            tid,taxi,eid,day,group,bucket,complete,highway=key
            # A trip occurs in one matching batch. Conflicting duplicate evidence
            # is an error, never another independent observation.
            db.execute('INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?,?,?)',
                (tid,taxi,eid,day,group,bucket,distance,duration,complete,highway))
        db.execute('INSERT INTO applied VALUES (?)',(batch_id,))
    return True


def _stats(rows):
    by_trip=defaultdict(lambda:[0.,0.]); taxis=set(); dates=set()
    for tid,taxi,day,group,bucket,distance,duration in rows:
        by_trip[tid][0]+=distance; by_trip[tid][1]+=duration
        taxis.add(taxi); dates.add(day)
    return ([d/t*3.6 for d,t in by_trip.values() if t>0],
        {'distinct_trips':len(by_trip),'distinct_taxis':len(taxis),'distinct_dates':len(dates)})


def disk_profiles(db,network,config,cutoff,*,complete_only=False,check=None):
    """Reproduce congestion.build_profiles median/P85/support semantics exactly.

    Only compact accepted per-trip sums are held for ONE edge or road class.
    Partial-block observations retain original independent trip IDs.
    """
    rules=config['profile_rules']; validate_rules(rules)
    condition=' AND complete=1' if complete_only else ''
    adequate=lambda counts:all(counts[k]>=rules['min_'+k] for k in counts)
    night={}
    for highway in sorted({e.highway for e in network.edges.values()}):
        cursor=db.execute('SELECT trip_id,taxi_id,local_date,day_group,bucket,distance,duration FROM evidence '
            "WHERE highway=? AND bucket='00-06'"+condition,(highway,))
        speeds,counts=_stats(cursor)
        night[highway]=quantile(speeds,.85) if speeds and adequate(counts) else None
    profiles=[]
    for index,edge in enumerate(network.edges.values()):
        if check is not None and index%100==0:
            check()
        rows=db.execute('SELECT trip_id,taxi_id,local_date,day_group,bucket,distance,duration FROM evidence '
            'WHERE edge_id=?'+condition,(edge.edge_id,)).fetchall()
        speeds,counts=_stats(rows)
        static=median(speeds) if speeds and adequate(counts) else None
        if speeds and adequate(counts):
            reference,source=quantile(speeds,.85),'edge_p85'
        elif night[edge.highway] is not None:
            reference,source=night[edge.highway],'class_night_p85'
        else:
            reference=parse_maxspeed(edge.maxspeed_raw)
            source='maxspeed_weak_proxy' if reference else None
        groups=defaultdict(list)
        for row in rows:
            groups[(row[3],row[4])].append(row)
        for group in ('weekday','weekend'):
            for start,end in zip(config['time']['bucket_boundaries_hour'],config['time']['bucket_boundaries_hour'][1:]):
                bucket=f'{start:02d}-{end:02d}'
                values,support=_stats(groups[(group,bucket)])
                speed=median(values) if values else None
                status,confidence,slowdown='unknown','insufficient',None
                if speed is not None and reference is not None and reference>0 and adequate(support):
                    ratio=speed/reference
                    status=('high_slowdown' if ratio<rules['high_slowdown_ratio_threshold'] else
                            'slow' if ratio<rules['slow_ratio_threshold'] else 'normal')
                    confidence='weak_reference' if source=='maxspeed_weak_proxy' else 'supported_uncalibrated'
                    slowdown=max(0.,1-ratio)
                profiles.append({'edge_id':edge.edge_id,'day_group':group,'time_bucket':bucket,
                    'median_speed_kmh':speed,'reference_speed_kmh':reference,'reference_source':source,
                    'static_speed_kmh':static,'slowdown_ratio':slowdown,**support,'confidence':confidence,
                    'status':status,'graph_version':network.graph_version,'train_cutoff':cutoff})
    return profiles


def coverage_report(network,profiles,target=.8):
    groups=defaultdict(list)
    expected=set(network.edges)
    for row in profiles:
        if row['graph_version']!=network.graph_version:
            raise ValueError('Coverage graph mismatch')
        groups[(row['day_group'],row['time_bucket'])].append(row)
    if len(groups)!=12:
        raise ValueError('Coverage must include all 12 groups; missing groups cannot be hidden')
    total_length=sum(e.length_m for e in network.edges.values())
    result={}
    for (day,bucket),rows in sorted(groups.items()):
        if len(rows)!=len(expected) or {r['edge_id'] for r in rows}!=expected:
            raise ValueError('Coverage denominator changed or duplicate edges')
        known=[r for r in rows if r['status']!='unknown']
        count=len(known)
        result[f'{day}/{bucket}']={'edges':len(rows),'known':count,'unknown':len(rows)-count,
            'known_edge_fraction':count/len(rows),
            'edges_without_accepted_visits':sum(r['distinct_trips']==0 for r in rows),
            'observed_but_unknown_edges':sum(r['distinct_trips']>0 and r['status']=='unknown' for r in rows),
            'known_length_fraction':sum(network.edges[r['edge_id']].length_m for r in known)/total_length,
            'target_met':count/len(rows)>=target}
    return {'target':target,'denominator':'all fixed directed graph edges in EACH of 12 buckets',
        'all_buckets_target_met':all(r['target_met'] for r in result.values()),'buckets':result}
