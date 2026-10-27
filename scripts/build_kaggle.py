"""Create the isolated full-source region notebook and source-only delivery."""
import ast
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BOOT = r'''
from pathlib import Path, PurePosixPath
import hashlib, json, os, shutil, stat, subprocess, sys, time, traceback, zipfile

INPUT = Path('/kaggle/input')
PROJECT = Path('/kaggle/working/portoflow_project')
WORK = Path('/kaggle/working/portoflow_run')
WORK.mkdir(parents=True, exist_ok=True)
EXPECTED = __REVISIONS__
SOURCE = None  # Set an explicit Path here only when more than one train source is attached.
RESUME = None  # Optional path to an attached portoflow checkpoint DIRECTORY.
PHASES = ['graph', 'scan', 'match', 'report']
TOKEN = 'PORTOFLOW_FULL_SOURCE_V1'

def copy_code():
    roots = [p.parent.parent for p in INPUT.rglob('run_pipeline.py')
             if p.parent.name == 'scripts' and (p.parent.parent/'pyproject.toml').is_file()]
    for root in roots:
        if all((root/n).is_file() and hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in EXPECTED.items()):
            for relative in EXPECTED:
                dest = PROJECT/relative; dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root/relative, dest)
            return
    archives = list(INPUT.rglob('portoflow_kaggle.zip'))
    if len(archives)!=1:
        raise ValueError('Attach the matching portoflow_code Dataset')
    with zipfile.ZipFile(archives[0]) as archive:
        for relative, checksum in EXPECTED.items():
            data = archive.read('portoflow_project/'+relative)
            if hashlib.sha256(data).hexdigest()!=checksum:
                raise ValueError('Code checksum differs: '+relative)
            dest = PROJECT/relative; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)

def restore():
    if RESUME is None:
        return
    root = Path(RESUME).resolve()
    if not (root/'source_index.sqlite').is_file() or not (root/'region.json').is_file():
        raise ValueError('RESUME must point to the saved run directory, not an old07 checkpoint')
    if (WORK/'region.json').exists():
        raise ValueError('Do not merge two run directories; use the current WORK or a fresh kernel')
    shutil.copytree(root, WORK, dirs_exist_ok=True)

def run(command, name, seconds):
    logs = WORK/'logs'; logs.mkdir(exist_ok=True)
    print('START', name, '| cap seconds:', seconds, flush=True)
    with (logs/name).open('w') as stream:
        process = subprocess.Popen(list(map(str, command)), cwd=PROJECT, env=environment,
            stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        start = time.monotonic(); offset = 0
        try:
            while process.poll() is None:
                time.sleep(5)
                with (logs/name).open(errors='replace') as reader:
                    reader.seek(offset); text = reader.read(); offset = reader.tell()
                if text:
                    print(text[-12000:], end='', flush=True)
                else:
                    print(name, '| still running |', round(time.monotonic()-start), 's', flush=True)
                if time.monotonic()-start>seconds:
                    raise TimeoutError(name+' deadline; committed checkpoints retained')
            with (logs/name).open(errors='replace') as reader:
                reader.seek(offset); print(reader.read()[-12000:], flush=True)
            if process.returncode:
                raise RuntimeError(name+' failed; inspect its log and retained Output')
        finally:
            if process.poll() is None:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

def review_bundle():
    # Full checkpoints remain as ordinary run-directory files in saved Kaggle Output.
    destination = Path('/kaggle/working/portoflow_review.zip')
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for path in WORK.rglob('*'):
            relative = path.relative_to(WORK)
            if not path.is_file() or path.stat().st_size>16*1024**2:
                continue
            if relative.parts[0]=='portoflow_recovery':
                if len(relative.parts)>1 and relative.parts[1] in {'profile_cache','evaluation_cache','evaluation_scratch','graph','matplotlib_cache'}:
                    continue
                if len(relative.parts)>1 and relative.parts[1]=='candidate_export':
                    if path.name in {'congestion_profiles.parquet','pipeline_config.json','diagnostics.png','run_metadata.json'}:
                        archive.write(path,relative.as_posix())
                elif path.suffix in {'.json','.txt'}:
                    archive.write(path,relative.as_posix())
                continue
            if relative.parts[0]=='region_batches':
                if path.name=='review_cases.json' and path.stat().st_size>2:
                    archive.write(path, relative.as_posix())
                continue
            if relative.parts[0] in {'native_cache','osm_cache','region_evidence.sqlite','source_index.sqlite','review_export','test_tmp'}:
                continue
            if path.suffix in {'.json','.txt','.yaml'}:
                archive.write(path, relative.as_posix())
    print('SEND FOR REVIEW:', destination, flush=True)
    print('RETAIN FULL Output directory:', WORK, '| includes checkpoints and candidate export', flush=True)

environment = dict(os.environ, PYTHONPATH=str(PROJECT/'src'), PYTHONUNBUFFERED='1',
    PYTHONFAULTHANDLER='1', MPLBACKEND='Agg', MPLCONFIGDIR=str(WORK/'matplotlib_cache'),
    UV_PYTHON_INSTALL_DIR='/tmp/portoflow_python', UV_CACHE_DIR='/tmp/portoflow_uv',
    OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
try:
    copy_code(); restore()
    resource = PROJECT/'resources'
    if not (WORK/'region.json').exists() and (resource/'region.json').is_file():
        for name in ('graph','context_graph'):
            shutil.copytree(resource/name,WORK/name,dirs_exist_ok=True)
        shutil.copyfile(resource/'region.json',WORK/'region.json')
    (WORK/'code_revisions.json').write_text(json.dumps(EXPECTED, indent=2))
    if SOURCE is None:
        candidates = list(INPUT.rglob('train.csv.zip'))
        if not candidates:
            candidates = list(INPUT.rglob('train.csv'))
        if len(candidates)!=1:
            raise ValueError('Attach full Porto train.csv.zip/train.csv; select SOURCE explicitly if ambiguous')
        SOURCE = candidates[0]
    print('Full source:', SOURCE, '| 10 km metric square | all eligible train/holdout | unknown retained', flush=True)
except Exception:
    (WORK/'BLOCKER.txt').write_text(traceback.format_exc()); review_bundle(); raise
'''

EXECUTE = r'''
try:
    run([sys.executable,'-m','pip','install','uv>=0.8,<1'], 'setup_uv.txt', 180)
    uv = shutil.which('uv')
    if not uv:
        raise RuntimeError('uv executable unavailable')
    run([uv,'python','install','3.12'], 'setup_python.txt', 600)
    venv = Path('/tmp/portoflow_venv')
    if not (venv/'bin/python').is_file():
        run([uv,'venv','--python','3.12',venv], 'setup_venv.txt', 120)
    python = venv/'bin/python'
    freeze = WORK/'logs/environment_freeze.txt'
    install = [uv,'pip','install','--python',python,'--only-binary','fastmm']
    if RESUME is not None and freeze.is_file():
        install += ['-r',freeze]
    else:
        install += ['-c',PROJECT/'requirements/constraints.txt','-e',str(PROJECT)+'[test]','fastmm==0.3.2']
    run(install, 'setup_dependencies.txt', 900)
    run([uv,'pip','freeze','--python',python], 'environment_freeze.txt', 60)
    run([python,'-m','pytest','tests/test_pipeline.py','-q','--basetemp',WORK/'test_tmp'], 'synthetic_tests.txt', 180)
    run([python,PROJECT/'scripts/probe_fastmm_native.py','--output',WORK/'native_probe'], 'native_probe.txt', 120)
    caps = {'graph':600, 'scan':5460, 'match':21660, 'report':1860}
    for phase in PHASES:
        command = [python,PROJECT/'scripts/run_pipeline.py','--phase',phase,'--work',WORK,
                   '--plan',PROJECT/'configs/study_area.yaml','--config',PROJECT/'configs/default.yaml',
                   '--authorize-run',TOKEN]
        if phase=='scan':
            command += ['--source',SOURCE]
        run(command,phase+'.txt',caps[phase])
    print(json.loads((WORK/'result_summary.json').read_text())['status'], flush=True)
finally:
    review_bundle()
'''


def build():
    names = ['pyproject.toml', 'README.md', 'configs/default.yaml', 'configs/study_area.yaml',
             'scripts/run_pipeline.py', 'scripts/report_recovery.py', 'scripts/probe_fastmm_native.py', 'scripts/launch_app.py',
             'app/streamlit_app.py', 'app/journey_view.py', 'app/ui_logic.py',
             'app/journey_routing.py', 'app/road_display.py', 'app/persistent_map.py',
             'app/map_frontend/index.html', 'app/map_frontend/map.js',
             'tests/test_pipeline.py', 'docs/PIPELINE.md', 'requirements/constraints.txt']
    names += [p.relative_to(ROOT).as_posix() for p in (ROOT/'src/portoflow').iterdir() if p.suffix in {'.py','.json'}]
    names = sorted(set(names))
    sources = {name: ROOT/name for name in names}
    graph_root = ROOT/'data'
    if (graph_root/'region.json').is_file():
        from portoflow.graph import RoadNetwork
        RoadNetwork.load(graph_root/'graph'); RoadNetwork.load(graph_root/'context_graph')
        for directory in ('graph','context_graph'):
            for path in (graph_root/directory).iterdir():
                if path.is_file():
                    sources['resources/'+directory+'/'+path.name] = path
        sources['resources/region.json'] = graph_root/'region.json'
    revisions = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name,path in sources.items()}
    intro = '''# PortoFlow — 10×10 km, toàn nguồn dữ liệu

Hai Inputs: **code Dataset từ portoflow_kaggle.zip** và **Porto train.csv.zip/train.csv đầy đủ**.
CPU/None, Internet On. Save Version → Save & Run All. Gói độc lập có sẵn graph đã kiểm.

Tâm Porto: [-8.63, 41.16]; vuông 10.000×10.000m trong EPSG:32629, đệm matching500m.
Graph drive tải mới; cap60.000cạnh context, không phải số cạnh được hứa trước.
Quét đến EOF (cap2triệu dòng); split toàn chuyến trước cutoff2014-05-01UTC.
Giữ mọi block liên tục≥6GPS trong context chạm vùng nghiên cứu; không cần90%GPS trong vùng.
Giữ gapQC, trim đầu/cuối block và support3chuyến/2taxi/2ngày, ratio0.7/0.4.
Evidence chỉ lấy phần cạnh bên trong100km². Tất cả train/holdout đủ điều kiện được matching;
holdout không vào profile. Không dừng ở80%; unknown giữ nguyên.

Trần mỗi phiên: graph10phút; scan90phút; matching6giờ; report30phút; RAM12.000MiB/output12GiB.
Setup/probes có cap riêng trong code. Đây là trần, chưa là dự báo thời gian toàn nguồn.
Checkpoint sau20parent. Hết phiên giữ toàn bộ Output; attach lại và đặt RESUME tới thư mục
portoflow_run để tiếp tục. Mã và dependency versions phải khớp; khác identity sẽ dừng.

Output nhỏ: portoflow_review.zip. **Giữ toàn bộ Output**, nhất là source_index.sqlite,
graph/, context_graph/, region_batches/ và code_revisions.json. Không cần nén lại toàn checkpoint.
review_export chỉ là candidate; metric ETA trên các component holdout và overlays cần review trước khi dùng trong app.
Notebook tạo candidate riêng, không tự kích hoạt app. Chưa có kết quả Porto thật cho lượt này.
'''
    cells = [{'cell_type':'markdown','id':'region-intro','metadata':{},'source':intro.splitlines(True)}]
    for identifier, code in [('region-bootstrap', BOOT.replace('__REVISIONS__', repr(revisions))), ('region-execute', EXECUTE)]:
        ast.parse(code)
        cells.append({'cell_type':'code','id':identifier,'metadata':{},'source':code.splitlines(True),'outputs':[],'execution_count':None})
    notebook = {'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
        'language_info':{'name':'python','version':'3.12'}},'nbformat':4,'nbformat_minor':5}
    path = ROOT/'notebooks/PortoFlow_Kaggle.ipynb'
    path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1)+'\n', encoding='utf-8')
    archive_path = ROOT/'deliverables/portoflow_kaggle.zip'
    with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,path in sorted(sources.items()):
            archive.writestr('portoflow_project/'+name,path.read_bytes())
        archive.writestr('portoflow_project/code_revisions.json',json.dumps(revisions,indent=2))
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix('.sha256.txt').write_text(checksum+'  '+archive_path.name+'\n',encoding='utf-8')
    print(json.dumps({'notebook':str(ROOT/'notebooks/PortoFlow_Kaggle.ipynb'),
        'code_zip':str(archive_path),'sha256':checksum,'files':len(sources),
        'bundled_verified_graph': 'resources/region.json' in sources,'bytes':archive_path.stat().st_size},indent=2))


if __name__ == '__main__':
    build()
