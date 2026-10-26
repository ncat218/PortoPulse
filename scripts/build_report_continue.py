"""Deliver read-only continuation from the saved disk-capped V1 ledger."""
import ast
import hashlib
import json
import zipfile
from pathlib import Path

import build_report_recovery as previous

ROOT = Path(__file__).resolve().parents[1]

SMALL_RESTORE = r'''
def restore_cache(path):
    # Optional SMALL cache from this continuation notebook only; never the V1 ledger.
    if path is None:
        return
    path=Path(path)
    allowed={'profile_cache','evaluation_cache'}
    if path.is_dir():
        if not (path/'continuation_receipt.json').is_file():
            roots=[p.parent for p in path.rglob('continuation_receipt.json') if p.parent.name=='portoflow_report_final']
            if len(roots)!=1:
                raise ValueError('RESUME must be a SMALL report-final Output; the failed large recovery belongs in CACHE')
            path=roots[0]
        files=[p for p in path.rglob('*') if p.is_file() and p.relative_to(path).parts[0] in allowed]
        if sum(p.stat().st_size for p in files)>1024**3:
            raise ValueError('Small resume cache exceeds1GiB')
        for item in files:
            target=WORK/item.relative_to(path);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(item,target)
    else:
        with zipfile.ZipFile(path) as archive:
            roots=[n[:-len('continuation_receipt.json')] for n in archive.namelist()
                   if n.endswith('portoflow_report_final/continuation_receipt.json')]
            if len(roots)!=1:
                raise ValueError('RESUME must be a saved report-final Output ZIP')
            prefix=roots[0];members=[]
            for item in archive.infolist():
                if not item.filename.startswith(prefix) or item.is_dir():
                    continue
                raw=item.filename[len(prefix):];relative=Path(raw)
                if relative.is_absolute() or '..' in relative.parts or ':' in raw or '\\' in raw:
                    raise ValueError('Unsafe small cache path')
                if relative.parts[0] in allowed:
                    members.append((item,relative))
            if sum(item.file_size for item,_ in members)>1024**3:
                raise ValueError('Small resume cache exceeds1GiB')
            for item,relative in members:
                target=WORK/relative;target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(item) as source,target.open('wb') as dest:
                    shutil.copyfileobj(source,dest,length=8*1024**2)

'''


def build():
    names=['scripts/report_recovery.py','scripts/report_continue.py','scripts/run_pipeline.py',
           'tests/test_report_recovery.py','tests/test_report_continue.py',
           'configs/default.yaml','configs/study_area.yaml','requirements/constraints.txt']
    names += [p.relative_to(ROOT).as_posix() for p in (ROOT/'src/portoflow').iterdir() if p.suffix in {'.py','.json'}]
    sources={name:ROOT/name for name in sorted(names)}
    revisions={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in sources.items()}
    boot=previous.BOOT.replace('/kaggle/working/portoflow_report_code','/kaggle/working/portoflow_continue_code')
    boot=boot.replace('/kaggle/working/portoflow_recovery','/kaggle/working/portoflow_report_final')
    boot=boot.replace('portoflow_report_recovery.zip','portoflow_report_continue.zip')
    boot=boot.replace("'portoflow_report_recovery/'+name","'portoflow_report_continue/'+name")
    boot=boot.replace('RESUME=None  # Optional previous recovery Output directory/archive, only if recovery returned PARTIAL.',
        "CACHE=INPUT  # Auto-find the SAVED FAILED RECOVERY Output, in addition to original matching Output.\n"
        "RESUME=None  # Optional SMALL Output from a previous Report_Continue run.\n"
        "SCRATCH=Path('/tmp/portoflow_sealed_ledger')  # Finite24GiB; large ledger never in saved Output.")
    start=boot.index('def restore_cache(');end=boot.index('def bundle():',start)
    boot=boot[:start]+SMALL_RESTORE+boot[end:]
    boot=boot.replace('portoflow_recovered_review.zip','portoflow_final_review.zip')
    boot=boot.replace("print('ORIGINAL SAVED OUTPUT:',SOURCE,flush=True)",
        "print('ORIGINAL SAVED OUTPUT:',SOURCE,flush=True)\nprint('FAILED RECOVERY INPUT:',CACHE,flush=True)")
    boot=boot.replace('__REVISIONS__',repr(revisions))
    execute=previous.EXECUTE.replace('tests/test_report_recovery.py','tests/test_report_continue.py')
    execute=execute.replace("'tests/test_report_continue.py','-q',", "'tests/test_report_continue.py','-q','-k','not delivery and not small_resume',")
    execute=execute.replace('/kaggle/working/report_recovery_synthetic_tests','/tmp/report_continue_synthetic_tests')
    execute=execute.replace("PROJECT/'scripts/report_recovery.py','--source',SOURCE,'--work',WORK,",
        "PROJECT/'scripts/report_continue.py','--source',SOURCE,'--cache',CACHE,'--work',WORK,'--scratch',SCRATCH,")
    execute=execute.replace("result['status']=='REPORT_RECOVERY_PARTIAL'", "result['status']!='REPORT_CONTINUE_COMPLETE'")
    execute=execute.replace('Keep recovery Output; next report-only run can resume its cache.',
        'Read reason in result_summary.json; keep both original Inputs plus this small report Output.')
    text='''# PortoFlow — tiếp tục sau lỗi dung lượng report

Chỉ dùng khi lần Report_Recovery đã nhập đủ batch và dừng vì **Output disk ceiling**.
Không dùng lại notebook Report_Recovery cho lỗi này.

**Ba Inputs bắt buộc:**
1. Code Dataset mới từ **portoflow_report_continue.zip**.
2. **Notebook Output matching ban đầu**: anhthu128/porto-flow, đúng version có ZIP5,48GB.
3. **Notebook Output của lần recovery vừa lỗi dung lượng**: có portoflow_recovery và ledger_checkpoint.json.

CPU/None, InternetOn. Để SOURCE=None và CACHE=INPUT để tự chọn.
SaveVersion → Save&RunAll. Không cần raw Porto hay code Dataset cũ.

Notebook xác minh SHA/code/runtime và ledger seal; mở cơ sở dữ liệu ở chế độ chỉ đọc.
Ledger đã nhập xong được dùng ngay: **0 import batch, 0 tạo lại chỉ mục, 0 matching**.
Nếu Kaggle lưu ZIP thì chỉ giải nén member SQLite vào /tmp, tối đa24GiB, kiểm đủ
dung lượng trống trước khi bắt đầu. Nếu mount dạng folder thì đọc trực tiếp, không chép DB.
Output mới giới hạn2GiB; report tối đa90phút, RAM mềm12.000MiB. Thiếu chỗ thì báo sớm,
không bỏ giới hạn hoặc hứa chắc hoàn tất trong một phiên. Temp ledger không được lưu lại;
Saved Input recovery vẫn giữ bản gốc. Nếu cần tiếp tục, attach cả hai Input gốc và
Output nhỏ của Report_Continue, đặt RESUME tới Output nhỏ đó để lấy profile/evaluation cache.

Gửi **portoflow_final_review.zip**, giữ Output **portoflow_report_final**.
matching_complete=false vẫn được công bố đúng; báo cáo xong không phải matching toàn nguồn xong.
Support3/2/2, cutoff, QC, công thức median/P85/màu/ETA và gray unknown giữ nguyên.
Candidate chờ review; không tự cập nhật app.
'''
    cells=[{'cell_type':'markdown','id':'report-continue-intro','metadata':{},'source':text.splitlines(True)}]
    for label,body in [('report-continue-bootstrap',boot),('report-continue-execute',execute)]:
        ast.parse(body)
        cells.append({'cell_type':'code','id':label,'metadata':{},'source':body.splitlines(True),'outputs':[],'execution_count':None})
    notebook={'cells':cells,'nbformat':4,'nbformat_minor':5,
        'metadata':{'kernelspec':{'display_name':'Python3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.12'}}}
    notebook_path=ROOT/'notebooks/PortoFlow_Report_Continue.ipynb'
    notebook_path.write_bytes((json.dumps(notebook,ensure_ascii=False,indent=1)+'\n').encode('utf-8'))
    archive_path=ROOT/'deliverables/portoflow_report_continue.zip'
    with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,path in sources.items():
            archive.writestr('portoflow_report_continue/'+name,path.read_bytes())
        archive.writestr('portoflow_report_continue/code_revisions.json',json.dumps(revisions,indent=2))
    checksum=hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix('.sha256.txt').write_text(checksum+'  '+archive_path.name+'\n')
    print(json.dumps({'notebook':str(notebook_path),'code_zip':str(archive_path),'bytes':archive_path.stat().st_size,
                      'sha256':checksum,'files':len(sources)},indent=2))


if __name__=='__main__':
    build()
