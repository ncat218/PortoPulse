# Kiểm toán parent/QC từ Saved Output gốc

Ngày2026-10-28. Công cụ đã kiểm thử bằng fixture tổng hợp, **chưa chạy trên
Saved Output thật**. Không có lần matching mới, quan sát mới hay độ phủ mới.

## Chạy trên Kaggle

1. Tạo notebook riêng, import **notebooks/PortoFlow_Coverage_Audit.ipynb**.
2. Add Input → Notebook Outputs → **anhthu128/porto-flow**, chọn Saved Version
   matching ban đầu có **_output_.zip khoảng5,48GB**. Đây là Input duy nhất.
   Không dùng Output porto-flow-v2/recovery/report; các ZIP này có SHA khác.
3. Accelerator **None/CPU**, Internet **Off**, notebook **Private**. Không cài
   package hoặc tạo code Dataset. Save Version → Save & Run All, một job mỗi lần.
4. Gửi **portoflow_coverage_audit_review.zip**. Giữ toàn bộ thư mục Saved Output
   **portoflow_coverage_audit**, gồm audit_state.sqlite để tiếp tục nếu hết giờ.

Code nằm sẵn trong notebook, có checksum. Nếu có nhiều _output_.zip được attach
và đường dẫn mặc định không tồn tại, đặt SOURCE tới đúng ZIP gốc trong cell đầu.
SHA bắt buộc của ZIP gốc:

`71e0a5ee45f1a241835b32254068e9009983d4c5067ef8f4edc821840803a93b`

Không sửa SHA để chạy nhầm phiên bản. Công cụ dừng sớm nếu nguồn không khớp.

## Ngân sách và resume

| Tài nguyên | Giới hạn mỗi lượt |
|---|---:|
| Thời gian audit, gồm kiểm SHA toàn ZIP | 2.700giây/45phút |
| RAM mềm trên Kaggle Linux | 1.536MiB |
| Output audit mềm | 768MiB |
| Dung lượng trống dự phòng | 256MiB |
| Batch mới tối đa | 100.000 |
| Member metadata đọc một lần | 16MiB |
| Ví dụ parent train | Tối đa100, không quá25mỗi nhóm lý do |
| Member trong ZIP review | Tối đa8MiB |

Không giải nén archive; scratch ledger0byte; không đọc ledger13GB. Các soft cap
được kiểm mỗi batch, tối đa một batch metadata có thể vượt cap trước lần kiểm
tiếp. SQLite giao dịch theo batch; phần đã commit giữ được khi dừng có kiểm soát.
RAM guard Linux dùng /proc/self/status; Windows fixture không đo RAM bằng guard đó.
Thiết lập/import/resume copy là bước nhỏ riêng; ngân sách45phút áp dụng hàm audit.

Nếu status **PARENT_QC_AUDIT_PARTIAL**, thêm Output audit vừa lưu vào Input cùng
ZIP matching gốc. Đặt RESUME tới thư mục audit ở Input, ví dụ đường dẫn tìm được
chứa summary.json và audit_state.sqlite. Không đặt RESUME tới recovery/report.
Notebook chỉ copy DB audit nhỏ và receipt, kiểm SHA state và dung lượng trước;
không copy cả directory hoặc merge hai state. WORK cần trống khi dùng RESUME.

Mỗi lượt vẫn kiểm lại SHA toàn ZIP và mã auditor. State đã commit được kiểm seal
trước khi dùng; parent trong batch cũ không bị đếm thêm. Khi có state sai/hash
khác, giữ Output cũ để kiểm tra và chạy directory audit mới. Nếu attempt mới
dừng trước khi mở state, last_attempt.json ghi lý do, summary/seal cũ được giữ.

## Báo cáo trả lời được gì?

- Đếm lại parent train/holdout và parent có quan sát core được chấp nhận, đối
  chiếu matching_summary. Parent IDs và source rows phải duy nhất qua mọi batch.
- Đếm native status, rejection của block QC và rejected-gap reasons cho train.
- Phân nhóm parent train có0quan sát core: native blocks không thành công;
  không có gap qua block QC; hoặc có accepted_gaps ở block QC nhưng cuối cùng
  không có quan sát core được chấp nhận. Ví dụ là các bản ghi gặp đầu tiên trong
  thứ tự archive, không phải mẫu ngẫu nhiên hoặc mẫu đại diện.
- Đọc inventory scan đã lưu để biết các lý do loại trước matching; đây là số
  được báo trong checkpoint, không phải scan lại CSV hoặc kiểm độc lập raw GPS.

Accepted_gaps ở block QC được ghi **trước** trimming/clipping/lọc tốc độ về sau.
Nhóm cuối không tự chứng minh có lỗi: có thể hợp lệ ở context nhưng ở ngoài core,
bị trim biên hoặc không còn displacement hợp lệ. parents.json không chứa cạnh
của tất cả đoạn bị loại, nên báo cáo này không gắn được từng parent loại vào
đúng cạnh xám và không ước lượng được bao nhiêu cạnh sẽ phục hồi.

**PARENT_QC_AUDIT_COMPLETE** chỉ nghĩa audit xong các batch có sẵn, đối chiếu
parent counts đạt. Không phải full matching hoàn tất, QC nguyên bản đúng hết
hay đạt80%độ phủ. Holdout chỉ được đếm; ví dụ và mục tiêu khôi phục chỉ có train.
Không đọc observations.parquet/raw GPS, không thay pipeline khoa học, ngưỡng,
split, profile, graph hoặc export phục vụ app. Bước sau cần kiểm chứng raw/native
các trường hợp nghi vấn trước khi quyết định sửa hay tái chạy một phần nào.

## Mã và kiểm thử

scripts/audit_saved_parents.py chỉ dùng Python standard library; scripts/build_coverage_audit.py
nhúng đúng mã vào notebook và pin checksum. Kiểm thử tổng hợp bao gồm đếm/QC,
loại holdout khỏi ví dụ, checksum sai, parent trùng, đối chiếu totals, ngắt budget,
resume không đếm trùng, bảo vệ state seal và chạy thực thi cell notebook/ZIP review.

```powershell
.\.venv\Scripts\python.exe scripts\build_coverage_audit.py
.\.venv\Scripts\python.exe -m pytest tests\test_parent_qc_audit.py -q
```
