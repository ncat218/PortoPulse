"""Build a self-contained stdlib-only Kaggle notebook, no code Dataset needed."""
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def build():
    script=(ROOT/'scripts/audit_saved_parents.py').read_text(encoding='utf-8')
    checksum=hashlib.sha256(script.encode()).hexdigest()
    intro='''# PortoFlow — kiểm toán khoảng trống độ phủ

Notebook này **chỉ chẩn đoán metadata/QC**. Không matching, không đọc ledger13GB,
không nhập holdout vào train, không đổi profile hoặc màu bản đồ. Báo cáo xong
chưa có nghĩa độ phủ tăng hoặc tìm được parent có thể khôi phục.

**Input duy nhất:** Add Input → Notebook Outputs → `anhthu128/porto-flow`,
đúng Saved Version matching ban đầu có `_output_.zip` khoảng5,48GB.
Không chọn `porto-flow-v2` hoặc Output recovery/report. Không cần raw Porto,
code Dataset hay pip install. CPU/None, Internet **Off**, giữ notebook **Private**.

Ngân sách:45phút gồm kiểm SHA toàn ZIP, RAM mềm1,5GiB, Output audit mềm768MiB,
reserve256MiB, tối đa100.000batch mới, không giải nén hoặc tạo scratch ledger.
Giới hạn được kiểm trước mỗi batch; tối đa một batch metadata có thể vượt soft cap.
Một job mỗi lần. Đây là trần, không phải lời hứa thời gian hoàn tất.

Lượt này kiểm parent IDs/source rows trùng, checksum `parents.json`, native status,
block-QC và đối chiếu tổng parent với summary. Không kiểm lại Parquet/GPS độc lập.
Chỉ lấy tối đa100ví dụ train chưa có quan sát hợp lệ; holdout chỉ đếm đối chiếu.

**Chạy:** Save Version → Save & Run All. Gửi `portoflow_coverage_audit_review.zip`;
giữ cả thư mục Output `portoflow_coverage_audit` để có state tiếp tục khi hết giờ.
Nếu PARTIAL: attach Output nhỏ lần này và cùng Input matching gốc, đặt RESUME tới
thư mục audit ở Input trước khi chạy tiếp. Không chạy lại pipeline6giờ.
'''
    bootstrap='''from pathlib import Path
import hashlib, importlib.util, json, shutil, zipfile

SOURCE = None  # Optional explicit original _output_.zip path when auto-detection is ambiguous.
RESUME = None  # Optional attached prior SMALL audit directory, not a recovery ledger.
WORK = Path('/kaggle/working/portoflow_coverage_audit')
SCRIPT_PATH = Path('/kaggle/working/portoflow_parent_qc_audit.py')
'''
    bootstrap+='SCRIPT = '+repr(script)+'\nEXPECTED_SCRIPT_SHA = '+repr(checksum)+'\n'
    bootstrap+='''assert hashlib.sha256(SCRIPT.encode()).hexdigest() == EXPECTED_SCRIPT_SHA
SCRIPT_PATH.write_bytes(SCRIPT.encode())
spec = importlib.util.spec_from_file_location('portoflow_parent_qc_audit', SCRIPT_PATH)
audit_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_tool)

if SOURCE is None:
    preferred = Path('/kaggle/input/notebooks/anhthu128/porto-flow/_output_.zip')
    if preferred.is_file():
        SOURCE = preferred
    else:
        candidates = list(Path('/kaggle/input').rglob('_output_.zip'))
        if len(candidates) != 1:
            raise ValueError('Attach ONLY the original matching Output, or set SOURCE to its _output_.zip. Candidates: '+str(candidates))
        SOURCE = candidates[0]
SOURCE = Path(SOURCE)

if RESUME is not None:
    resume = Path(RESUME).resolve()
    if WORK.exists() and any(WORK.iterdir()):
        raise ValueError('WORK already contains files; do not merge resume states')
    receipt = json.loads((resume/'summary.json').read_text())
    state = resume/'audit_state.sqlite'
    if receipt.get('source_zip_sha256') != audit_tool.SOURCE_SHA:
        raise ValueError('Resume belongs to another original Output')
    if state.stat().st_size > audit_tool.DEFAULT_LIMITS['output_bytes']:
        raise ValueError('Resume exceeds finite Output cap')
    if audit_tool.sha_file(state) != receipt.get('audit_state_sha256'):
        raise ValueError('Resume state checksum differs')
    WORK.mkdir(parents=True, exist_ok=True)
    required = state.stat().st_size+audit_tool.DEFAULT_LIMITS['reserve_bytes']
    if shutil.disk_usage(WORK).free < required:
        raise OSError('Insufficient free space for the small audit resume state')
    # Only this audit's bounded state/receipt are copied. No directory merge.
    shutil.copyfile(state,WORK/'audit_state.sqlite')
    shutil.copyfile(resume/'summary.json',WORK/'summary.json')

print('Original matching Input:', SOURCE, flush=True)
print('Finite budget:', audit_tool.DEFAULT_LIMITS, flush=True)
'''
    execute='''result = audit_tool.audit(SOURCE, WORK)
print('STATUS:', result['status'], '| phase:', result['phase'], flush=True)
print('Batches:', result['committed_batches'], '/', result['available_batches'], flush=True)
print('Metrics:', json.dumps(result['metrics'], ensure_ascii=False, indent=2), flush=True)
if result.get('error'):
    print('STOP REASON:', result['error'], flush=True)
print('Coverage changed:', result['coverage_changed'], flush=True)

review = Path('/kaggle/working/portoflow_coverage_audit_review.zip')
with zipfile.ZipFile(review, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in ('summary.json','examples.json','budget.json','last_attempt.json'):
        path = WORK/name
        if path.is_file():
            if path.stat().st_size > 8*1024**2:
                raise ValueError('Small review member exceeds8MiB')
            archive.write(path,'portoflow_coverage_audit/'+name)
print('SEND FOR REVIEW:', review, '| bytes:', review.stat().st_size, flush=True)
print('RETAIN FULL Output:', WORK, '| contains bounded resumable audit_state.sqlite', flush=True)
if result['status'] == 'PARENT_QC_AUDIT_PARTIAL':
    print('PARTIAL: keep Output, attach it plus original matching Input, set RESUME to the small audit directory.', flush=True)
elif result['status'] == 'PARENT_QC_AUDIT_FAILED':
    raise RuntimeError('Audit failed validation; inspect STOP REASON and review ZIP. No matching or profile changes occurred.')
'''
    cells=[dict(cell_type='markdown',id='coverage-audit-intro',metadata={},source=intro.splitlines(True))]
    for label,code in [('coverage-audit-setup',bootstrap),('coverage-audit-execute',execute)]:
        ast.parse(code)
        cells.append(dict(cell_type='code',id=label,metadata={},source=code.splitlines(True),outputs=[],execution_count=None))
    notebook=dict(cells=cells,nbformat=4,nbformat_minor=5,metadata={
        'kernelspec':{'display_name':'Python3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.12'}})
    path=ROOT/'notebooks/PortoFlow_Coverage_Audit.ipynb'
    path.write_bytes((json.dumps(notebook,ensure_ascii=False,indent=1)+'\n').encode())
    print(json.dumps({'notebook':str(path),'bytes':path.stat().st_size,'embedded_script_sha256':checksum},indent=2))
    return path


if __name__=='__main__': build()
