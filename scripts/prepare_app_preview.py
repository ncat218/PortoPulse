"""Assemble a local serving preview from verified profiles and the exact graph.

No matching or profile statistics are computed. The complete Kaggle checkpoint
remains separate; this preview records the original manifest and absent CSV.
"""
import argparse
import hashlib
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from shapely import from_wkb
from shapely.geometry import mapping

ROOT=Path(__file__).resolve().parents[1]
COLORS={'normal':'#2ca25f','slow':'#fec44f','high_slowdown':'#de2d26','unknown':'#969696'}
PROFILE_ORDER=('edge_id','day_group','time_bucket','median_speed_kmh','reference_speed_kmh',
    'reference_source','static_speed_kmh','slowdown_ratio','distinct_trips','distinct_taxis',
    'distinct_dates','confidence','status','graph_version')


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024**2),b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path,value):
    Path(path).write_bytes(json.dumps(value,indent=2,allow_nan=False).encode('utf-8'))


def prepare(archive_path,output):
    archive_path=Path(archive_path).resolve();output=Path(output).resolve()
    if output.exists():
        raise ValueError('Use a new preview folder; existing exports are preserved')
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free<2*1024**3:
        raise OSError('Local preview needs at least2GiB free space')
    output.mkdir()
    deadline=time.monotonic()+180
    with zipfile.ZipFile(archive_path) as archive:
        if len(archive.namelist())!=len(set(archive.namelist())) or archive.testzip() is not None:
            raise ValueError('Invalid review archive')
        manifest=json.loads(archive.read('candidate_manifest.json'))
        result=json.loads(archive.read('result_summary.json'))
        if not result['postprocessing_complete'] or manifest['data_kind']=='SYNTHETIC':
            raise ValueError('Expected completed real-input candidate profiles')
        (output/'graph').mkdir()
        for name in ('road_graph.graphml','road_edges.parquet','graph_metadata.json'):
            source=ROOT/'data/graph'/name
            if sha(source)!=manifest['outputs_sha256']['graph/'+name]:
                raise ValueError('Local graph differs from Kaggle candidate: '+name)
            shutil.copyfile(source,output/'graph'/name)
        for name in ('congestion_profiles.parquet','pipeline_config.json','diagnostics.png'):
            data=archive.read('candidate_export/'+name)
            if hashlib.sha256(data).hexdigest()!=manifest['outputs_sha256'][name]:
                raise ValueError('Candidate member checksum differs: '+name)
            (output/name).write_bytes(data)
        for name in ('coverage_report.json','evaluation.json'):
            write_json(output/name,json.loads(archive.read(name)))
            if sha(output/name)!=manifest['outputs_sha256'][name]:
                raise ValueError('Canonical candidate JSON differs: '+name)
        write_json(output/'coverage.json',result['coverage']['buckets'])
        if sha(output/'coverage.json')!=manifest['outputs_sha256']['coverage.json']:
            raise ValueError('Candidate coverage JSON differs')
    edges=pq.read_table(output/'graph/road_edges.parquet',columns=['edge_id','geometry','highway','graph_version']).to_pylist()
    if len(edges)!=22860 or any(row['graph_version']!=manifest['graph_version'] for row in edges):
        raise ValueError('Unexpected fixed graph')
    geometries={row['edge_id']:(mapping(from_wkb(row['geometry'])),row['highway']) for row in edges}
    parquet=pq.ParquetFile(output/'congestion_profiles.parquet')
    seen=set(); buckets={}; count=0
    geo=output/'traffic.geojson';temporary=geo.with_suffix('.tmp')
    with temporary.open('w',encoding='utf-8',newline='\n') as stream:
        stream.write('{"type":"FeatureCollection","features":[')
        columns=[name for name in parquet.schema_arrow.names if name!='train_cutoff']
        for batch in parquet.iter_batches(batch_size=4096,columns=columns):
            if time.monotonic()>deadline or stream.tell()>1024**3:
                raise TimeoutError('Finite preview formatting budget reached; source artifacts preserved')
            for row in batch.to_pylist():
                eid=row['edge_id'];key=(row['day_group'],row['time_bucket'],eid)
                if eid not in geometries or key in seen or row['graph_version']!=manifest['graph_version']:
                    raise ValueError('Profile identity/uniqueness mismatch')
                seen.add(key);bucket=key[:2]
                buckets.setdefault(bucket,[0,0]);buckets[bucket][0]+=1;buckets[bucket][1]+=row['status']!='unknown'
                geometry,highway=geometries[eid]
                properties={name:row[name] for name in PROFILE_ORDER}
                properties.update(color=COLORS[row['status']],highway=highway)
                if count:
                    stream.write(',')
                stream.write(json.dumps({'type':'Feature','geometry':geometry,'properties':properties},allow_nan=False,separators=(',',':')))
                count+=1
            print('Formatted',count,'/',parquet.metadata.num_rows,'profiles',flush=True)
        stream.write(']}')
    os.replace(temporary,geo)
    if count!=22860*12 or len(buckets)!=12:
        raise ValueError('Need all12buckets for22860fixed edges')
    for (day,hour),(n,known) in buckets.items():
        expected=result['coverage']['buckets'][day+'/'+hour]
        if n!=expected['edges'] or known!=expected['known']:
            raise ValueError('Preview coverage differs from verified profiles')
    # Preserve full source metadata beside, not inside the serving snapshot's file set.
    source_manifest=output.parent/(output.name+'_source_candidate_manifest.json')
    write_json(source_manifest,manifest)
    traffic_sha=sha(geo)
    preview={k:v for k,v in manifest.items() if k!='outputs_sha256'}
    preview.update(run_id=manifest['run_id']+'_local_preview',
        status='CANDIDATE_LOCAL_PREVIEW_PENDING_MANUAL_QC_AND_HOLDOUT_REVIEW',
        preview_only=True,source_candidate_run_id=manifest['run_id'],source_review_zip_sha256=sha(archive_path),
        source_candidate_manifest_sha256=sha(source_manifest),
        source_missing_in_preview=['holdout_components.csv'],
        traffic_reconstructed_from_verified_profiles=True,
        traffic_bytes_match_kaggle_candidate=(traffic_sha==manifest['outputs_sha256']['traffic.geojson']),
        outputs_sha256={p.relative_to(output).as_posix():sha(p) for p in output.rglob('*') if p.is_file()})
    write_json(output/'run_metadata.json',preview)
    print(json.dumps({'preview':str(output),'profile_rows':count,'geojson_bytes':geo.stat().st_size,
        'traffic_bytes_match_kaggle_candidate':preview['traffic_bytes_match_kaggle_candidate'],
        'matching_complete':preview['matching_complete'],'preview_only':True},indent=2),flush=True)
    return preview


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();prepare(args.review,args.output)
