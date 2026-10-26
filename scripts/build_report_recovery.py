"""Build report-only recovery without altering the frozen matching package."""
import ast
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

BOOT=r'''
from pathlib import Path
import hashlib,json,os,shutil,signal,subprocess,sys,time,traceback,zipfile

INPUT=Path('/kaggle/input')
PROJECT=Path('/kaggle/working/portoflow_report_code')
WORK=Path('/kaggle/working/portoflow_recovery')
WORK.mkdir(parents=True,exist_ok=True)
EXPECTED=__REVISIONS__
SOURCE=None  # Optional explicit Path to the ORIGINAL saved Output directory or _output_.zip.
RESUME=None  # Optional previous recovery Output directory/archive, only if recovery returned PARTIAL.
PROCESSING_SECONDS=5400  # 90-minute report-only cap; no scan or native matching.
environment=dict(os.environ,PYTHONPATH=str(PROJECT/'src'),PYTHONUNBUFFERED='1',
    MPLBACKEND='Agg',MPLCONFIGDIR=str(WORK/'matplotlib_cache'),
    UV_PYTHON_INSTALL_DIR='/tmp/portoflow_recovery_python',UV_CACHE_DIR='/tmp/portoflow_recovery_uv',
    OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')

def restore_code():
    roots=[p.parent.parent for p in INPUT.rglob('report_recovery.py') if p.parent.name=='scripts']
    for root in roots:
        if all((root/n).is_file() and hashlib.sha256((root/n).read_bytes()).hexdigest()==h for n,h in EXPECTED.items()):
            for name in EXPECTED:
                target=PROJECT/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,target)
            return
    archives=list(INPUT.rglob('portoflow_report_recovery.zip'))
    if len(archives)!=1:
        raise ValueError('Attach the NEW portoflow_report_recovery code Dataset')
    with zipfile.ZipFile(archives[0]) as archive:
        for name,checksum in EXPECTED.items():
            data=archive.read('portoflow_report_recovery/'+name)
            if hashlib.sha256(data).hexdigest()!=checksum:
                raise ValueError('Recovery code checksum differs: '+name)
            target=PROJECT/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)

def select_source():
    excluded={'test_tmp','native_probe','report_recovery_synthetic_tests'}
    candidates=[p for p in INPUT.rglob('matching_summary.json') if p.parent.name=='portoflow_run' and not any(s in excluded for s in p.relative_to(INPUT).parts)]
    if len(candidates)==1:
        return candidates[0].parent
    archives=[]
    for path in INPUT.rglob('*.zip'):
        if path.name=='portoflow_report_recovery.zip':
            continue
        if any(s in excluded for s in path.relative_to(INPUT).parts):
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                if any(n.endswith('portoflow_run/matching_summary.json') and not any(s in excluded for s in Path(n).parts) for n in archive.namelist()):
                    archives.append(path)
        except zipfile.BadZipFile:
            continue
    if len(archives)!=1:
        raise ValueError('Attach the ORIGINAL Porto_flow saved Notebook Output; select SOURCE explicitly if ambiguous')
    return archives[0]

def restore_cache(path):
    if path is None or (WORK/'recovery_evidence.sqlite').exists():
        return
    path=Path(path)
    skipped={'candidate_export','evaluation_scratch','matplotlib_cache'}
    if path.is_dir():
        if not (path/'recovery_evidence.sqlite').is_file():
            roots=[p.parent for p in path.rglob('recovery_evidence.sqlite') if p.parent.name=='portoflow_recovery']
            if len(roots)!=1:
                raise ValueError('Select the previous RECOVERY cache, not the original matching database')
            path=roots[0]
        files=[p for p in path.rglob('*') if p.is_file() and p.relative_to(path).parts[0] not in skipped]
        if sum(p.stat().st_size for p in files)>12*1024**3:
            raise ValueError('Recovery cache exceeds12GiB')
        for item in files:
            target=WORK/item.relative_to(path);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(item,target)
    else:
        with zipfile.ZipFile(path) as archive:
            roots=[n[:-len('recovery_evidence.sqlite')] for n in archive.namelist()
                   if n.endswith('portoflow_recovery/recovery_evidence.sqlite')]
            if len(roots)!=1:
                raise ValueError('Select the previous RECOVERY Output archive')
            prefix=roots[0]
            members=[i for i in archive.infolist() if i.filename.startswith(prefix) and not i.is_dir()]
            if sum(i.file_size for i in members)>12*1024**3:
                raise ValueError('Recovery cache exceeds12GiB')
            for item in members:
                raw_relative=item.filename[len(prefix):]
                relative=Path(raw_relative)
                if relative.is_absolute() or '..' in relative.parts or ':' in raw_relative or '\\' in raw_relative:
                    raise ValueError('Unsafe recovery cache path')
                if relative.parts[0] in skipped:
                    continue
                target=WORK/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(item))

def bundle():
    destination=Path('/kaggle/working/portoflow_recovered_review.zip')
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
        for path in WORK.rglob('*'):
            if not path.is_file() or path.stat().st_size>16*1024**2:
                continue
            relative=path.relative_to(WORK)
            if relative.parts[0]=='candidate_export':
                if path.name in {'congestion_profiles.parquet','pipeline_config.json','diagnostics.png','run_metadata.json'}:
                    archive.write(path,relative.as_posix())
                continue
            if relative.parts[0] not in {'logs','review_cases'} and len(relative.parts)>1:
                continue
            if path.suffix in {'.json','.txt','.png'}:
                archive.write(path,relative.as_posix())
    print('SEND:',destination,flush=True)
    print('KEEP FULL recovery Output:',WORK,flush=True)
    print('Original matching Output is read-only; no scan/matching launched.',flush=True)

def run(command,name,seconds):
    logs=WORK/'logs';logs.mkdir(exist_ok=True)
    print('START',name,'| cap',seconds,'s',flush=True)
    with (logs/name).open('w') as stream:
        process=subprocess.Popen(list(map(str,command)),cwd=PROJECT,env=environment,
            stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        start=time.monotonic();offset=0
        try:
            while process.poll() is None:
                time.sleep(5)
                with (logs/name).open(errors='replace') as reader:
                    reader.seek(offset);text=reader.read();offset=reader.tell()
                print(text[-12000:] if text else name+' | running '+str(round(time.monotonic()-start))+'s',flush=True)
                if time.monotonic()-start>seconds:
                    raise TimeoutError(name+' budget; retain committed recovery cache')
            with (logs/name).open(errors='replace') as reader:
                reader.seek(offset);print(reader.read()[-12000:],flush=True)
            if process.returncode:
                raise RuntimeError(name+' failed; send recovery review ZIP and retain Output')
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGKILL);process.wait()

restore_code()
(WORK/'recovery_code_revisions.json').write_text(json.dumps(EXPECTED,indent=2))
if SOURCE is None:
    SOURCE=select_source()
restore_cache(RESUME)
print('ORIGINAL SAVED OUTPUT:',SOURCE,flush=True)
print('REPORT ONLY | 0 raw scan | 0 native matching | checkpointed report progress',flush=True)
'''

EXECUTE=r'''
try:
    run([sys.executable,'-m','pip','install','uv>=0.8,<1'],'setup_uv.txt',180)
    uv=shutil.which('uv')
    if not uv:
        raise RuntimeError('uv unavailable')
    run([uv,'python','install','3.12'],'setup_python.txt',600)
    venv=Path('/tmp/portoflow_report_venv')
    if not (venv/'bin/python').is_file():
        run([uv,'venv','--python','3.12',venv],'setup_venv.txt',120)
    python=venv/'bin/python'
    run([uv,'pip','install','--python',python,'-c',PROJECT/'requirements/constraints.txt',
         'PyYAML','pyarrow','networkx','shapely','pyproj','numpy','matplotlib','tzdata','pytest'],
        'setup_report_dependencies.txt',900)
    run([python,'-m','pytest','tests/test_report_recovery.py','-q',
         '--basetemp','/kaggle/working/report_recovery_synthetic_tests'], 'synthetic_recovery_tests.txt',240)
    run([python,PROJECT/'scripts/report_recovery.py','--source',SOURCE,'--work',WORK,
         '--budget-seconds',PROCESSING_SECONDS],'recover_report.txt',PROCESSING_SECONDS+120)
    result=json.loads((WORK/'result_summary.json').read_text())
    print('RECOVERY RESULT:',result['status'],flush=True)
    if result['status']=='REPORT_RECOVERY_PARTIAL':
        print('Keep recovery Output; next report-only run can resume its cache.',flush=True)
except Exception:
    (WORK/'BLOCKER.txt').write_text(traceback.format_exc())
    raise
finally:
    bundle()
'''


def build():
    names=['scripts/report_recovery.py','scripts/run_pipeline.py','tests/test_report_recovery.py',
           'configs/default.yaml','configs/study_area.yaml','requirements/constraints.txt']
    names += [p.relative_to(ROOT).as_posix() for p in (ROOT/'src/portoflow').iterdir()
              if p.suffix in {'.py','.json'}]
    sources={name:ROOT/name for name in sorted(names)}
    revisions={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in sources.items()}
    text='''# PortoFlow — khôi phục báo cáo từ Output đã lưu

Chạy notebook này để tiếp tục hậu xử lý. **Không chạy lại matching6giờ.**

Hai Inputs: **code Dataset từ portoflow_report_recovery.zip** và **Notebook Output
Porto_flow vừa lỗi** (anhthu128/porto-flow, chọn đúng saved version). Output có thể
là thư mục hoặc `_output_.zip`5,48GB. Không cần tải file lớn về laptop, raw Porto,
code Dataset cũ, GPU hoặc API credentials. CPU/None, InternetOn.

Gói đọc trực tiếp các member cần thiết trong Output ZIP và kiểm SHA từng batch.
Mã matching/scientific package gốc giữ nguyên; công cụ recovery nằm riêng trong scripts.
Không dùng lại SQLite tổng hợp cũ thiếu receipt; tạo ledger mới có checkpoint,
Arrow-filter trước khi decode và bulk insert; cache từng chunk profile và batch holdout.
Giữ support3/2/2, cutoff, QC và công thức màu/ETA. Unknown giữ nguyên.

Cap report-only90phút, RAM mềm12.000MiB/output12GiB; setup/probes có cap riêng
trong code. Đây là trần, không phải lời hứa thời gian toàn bộ. Nếu PARTIAL, giữ
Output recovery và tiếp tục bằng RESUME trong lần report-only tiếp theo.

Output nhỏ để gửi: **portoflow_recovered_review.zip**. Giữ toàn bộ thư mục
**portoflow_recovery** để bảo toàn ledger/cache/candidate. Công cụ công bố riêng
`matching_complete`: report xong không có nghĩa matching đã xử lý hết parent.
Candidate vẫn chờ review source/QC/holdout; không tự cập nhật app.
'''
    cells=[{'cell_type':'markdown','id':'report-recovery-intro','metadata':{},'source':text.splitlines(True)}]
    for name,body in [('report-recovery-bootstrap',BOOT.replace('__REVISIONS__',repr(revisions))),
                      ('report-recovery-execute',EXECUTE)]:
        ast.parse(body)
        cells.append({'cell_type':'code','id':name,'metadata':{},'source':body.splitlines(True),'outputs':[],'execution_count':None})
    notebook={'cells':cells,'nbformat':4,'nbformat_minor':5,
        'metadata':{'kernelspec':{'display_name':'Python3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.12'}}}
    path=ROOT/'notebooks/PortoFlow_Report_Recovery.ipynb'
    path.write_bytes((json.dumps(notebook,ensure_ascii=False,indent=1)+'\n').encode('utf-8'))
    archive_path=ROOT/'deliverables/portoflow_report_recovery.zip'
    with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,path in sources.items():
            archive.writestr('portoflow_report_recovery/'+name,path.read_bytes())
        archive.writestr('portoflow_report_recovery/code_revisions.json',json.dumps(revisions,indent=2))
    checksum=hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix('.sha256.txt').write_text(checksum+'  '+archive_path.name+'\n')
    print(json.dumps({'notebook':str(ROOT/'notebooks/PortoFlow_Report_Recovery.ipynb'),
        'code_zip':str(archive_path),'bytes':archive_path.stat().st_size,'sha256':checksum,'files':len(sources)},indent=2))


if __name__=='__main__':
    build()
