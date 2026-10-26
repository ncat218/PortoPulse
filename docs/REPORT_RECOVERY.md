> Cập nhật: nếu recovery đã nhập đủ batch rồi lỗi **Output disk ceiling**, chuyển sang [Report Continue](REPORT_CONTINUE.md). Giữ cả Output matching và Output recovery; giới hạn restore 12 GiB bên dưới không phù hợp với ledger lớn của lượt này.

# PortoFlow — khôi phục report từ Output đã lưu

Ngày2026-10-26. Người dùng báo report timeout sau khoảng1.800s tại vòng đọc
checkpoint; phiên có matching chạy khoảng6giờ. Ảnh cho thấy Kaggle đã lưu
`_output_.zip`5,48GB của `anhthu128/porto-flow`. Chưa có archive thật trên máy
để xác minh số parent hoặc kết luận matching đã hoàn tất.

## Chạy tiếp phần báo cáo

1. Giữ nguyên Output phiên lỗi trên Kaggle.
2. Tạo code Dataset mới từ `deliverables/portoflow_report_recovery.zip`.
3. Tạo notebook mới, import `notebooks/PortoFlow_Report_Recovery.ipynb`.
4. AddInput hai nguồn: code recovery mới và NotebookOutput `anhthu128/porto-flow`,
   chọn đúng saved version có Output5,48GB. Không cần raw Porto hoặc code Dataset cũ.
5. CPU/None, InternetOn; để SOURCE=None, RESUME=None ở lần đầu. SaveVersion → Save&RunAll.
6. Gửi `portoflow_recovered_review.zip`; giữ toàn bộ Output `portoflow_recovery`.

Bộ đọc nhận cả directory lẫn `_output_.zip`, chỉ đọc các member cần thiết,
không giải nén toàn bộ5,48GB và không khởi chạy raw scan/native matching Porto.
Nếu nhiều Output được attach, đặt SOURCE cụ thể trong cell đầu.

Mã phân tích tốc độ/matching trong src/portoflow giữ nguyên từng byte so với
gói đã chạy. Recovery nằm trong scripts, kiểm identity/graph/SHA từng batch,
parent ID duy nhất, train cutoff và số observation được nhận trước khi cộng.
Không dùng bảng SQLite report cũ thiếu receipt. Ledger mới, chunk profile và
batch holdout có checkpoint riêng. Cache có SHA; ZIP nguồn được hash tuần tự
để lần resume có thể bỏ qua các batch đã xác minh mà không mất toàn bộ phiên
vào việc replay phần cũ. Cách cộng số, support3/2/2, proxy, ngưỡng và unknown
đã được đối chiếu với công thức cũ trên fixture tổng hợp.

Cap mỗi job recovery:5.400s hậu xử lý, RAM mềm12.000MiB/output12GiB. Setup/tests
có cap riêng trong notebook. Đây là trần, chưa là dự báo runtime trên Output thật.
Nếu REPORT_RECOVERY_PARTIAL, giữ Output mới, attach thêm nó ở lần chạy tiếp và
đặt RESUME tới directory/ZIP Output recovery đó; vẫn giữ OriginalOutput làm SOURCE.

REPORT_RECOVERY_COMPLETE chỉ có nghĩa báo cáo hoàn tất cho checkpoint đã lưu.
`matching_complete`, matched/expected parent counts được công bố riêng; nếu
matching chưa hết thì chưa được gọi là toàn nguồn hoàn tất. Candidate vẫn cần
review source, QC và holdout; không tự cập nhật app.

Lệnh report của notebook đầy đủ cũng đã chuyển sang công cụ có checkpoint.
Bản code giao đầu được giữ tại artifacts/original_delivery_20261025; không
thay đổi src, matching checkpoint hoặc graph của nó. Khôi phục phiên hiện tại
bằng notebook recovery ở trên, không chạy lại notebook full từ đầu.
