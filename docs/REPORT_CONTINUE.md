# PortoFlow — tiếp tục sau lỗi dung lượng report

Ngày 2026-10-26. Log người dùng gửi cho thấy recovery đã nhập **70.936/70.936
batch**, tạo `evidence_edge` và `evidence_night`, rồi dừng ở đầu profiles với
`OSError: Output disk ceiling exceeded; retain checkpoints and stop`.
Đây là giới hạn 12 GiB trong mã recovery, khác timeout 1.800 giây ban đầu.
Giới hạn nạp lại cache 12 GiB của notebook cũ cũng khiến nó không phù hợp cho
checkpoint này. Không tăng trần rồi replay cùng một lượt nhập.

Log ghi train 1.343.398 parent, holdout 75.322 parent và
`all eligible complete: False`. Đây là số từ log, chưa được đối chiếu độc lập
với archive thật. Matching chưa hoàn tất; report xong chỉ tổng kết checkpoint.

## Chạy trên Kaggle

1. Giữ cả hai Saved Version: matching Porto_flow ban đầu và recovery vừa lỗi.
2. Tạo code Dataset mới từ `deliverables/portoflow_report_continue.zip`.
3. Tạo notebook mới, import `notebooks/PortoFlow_Report_Continue.ipynb`.
4. Add Input đủ **ba nguồn**:
   - Code Dataset mới ở bước 2.
   - Notebook Output `anhthu128/porto-flow`, đúng version ban đầu có `_output_.zip` 5,48 GB.
   - Notebook Output của lần **Report_Recovery vừa lỗi dung lượng**, chứa
     `portoflow_recovery/recovery_evidence.sqlite`, `ledger_checkpoint.json`
     và `source_receipt.json` (Kaggle có thể đóng trong `_output_.zip`).
5. CPU/None, Internet On. Để `SOURCE=None`, `CACHE=INPUT`, `RESUME=None` mặc định.
   Save Version → Save & Run All. Không cần raw Porto hay Dataset code cũ.
6. Gửi `portoflow_final_review.zip`; giữ Output `portoflow_report_final`.

Nếu có nhiều bản Output cùng loại được attach, chọn SOURCE/CACHE cụ thể.
SOURCE là ZIP matching nguyên bản; CACHE là directory/ZIP recovery vừa lỗi.
Không dùng notebook full hoặc notebook Report_Recovery cũ cho checkpoint này.

## Cách giữ tiến độ và tài nguyên

`report_recovery.py` bản V1 và toàn bộ package khoa học giữ nguyên từng byte,
để xác minh đúng ledger đã tạo. Công cụ tiếp tục là `scripts/report_continue.py`.
Nó kiểm source ZIP SHA, matching/code/runtime identity, graph SHA, ledger seal,
receipt từng batch, parent counts và cờ ingest_complete trước khi đọc profile.
Mở SQLite immutable/read-only; không nhập batch, tạo chỉ mục hay matching.

Nếu Input là folder, đọc ledger trực tiếp. Nếu là ZIP, chỉ stream member SQLite
vào `/tmp/portoflow_sealed_ledger`, đồng thời kiểm SHA; không giải nén toàn bộ
Output, không chép DB lớn vào `/kaggle/working`. Kiểm trước kích thước giải nén,
dung lượng trống ở ổ tạm và ổ Output. Cap scratch 24 GiB, Output mới 2 GiB,
reserve 1 GiB, report 5.400 giây, RAM mềm 12.000 MiB; setup/tests có cap riêng.
Đây là trần, không phải cam kết đủ cho mọi archive hay lời hứa thời gian hoàn tất.

Thiếu chỗ trả `REPORT_CONTINUE_STORAGE_BLOCKED` sớm, kèm số GiB cần/còn.
Hết thời gian trả `REPORT_CONTINUE_PARTIAL`, giữ chunk profile và batch ETA.
Hai trạng thái này không phải hoàn tất. Temp ledger không được lưu trong Output;
bản gốc vẫn nằm ở Input recovery đã lưu. Khi chạy tiếp giữ cả hai Input gốc và
attach thêm Output nhỏ `portoflow_report_final`, đặt RESUME tới Output nhỏ đó
để tái sử dụng profile/evaluation cache. Không dùng RESUME cho ledger lớn.

Candidate vẫn chờ review source/QC/holdout; không tự cập nhật app. Support 3/2/2,
cutoff, unknown, median/P85, công thức màu và ETA không đổi. Kiểm thử dùng dữ liệu
tổng hợp; chưa chạy mã tiếp tục này trên archive thật của người dùng.
