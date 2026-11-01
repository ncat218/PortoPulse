# Sửa đóng gói trên bản clone sạch — 2026-11-02

## Lỗi đã xác nhận

[GitHub Actions của commit 2c5f3c1](https://github.com/ncat218/PortoPulse/actions/runs/41318028417/job/124882122213)
dừng ở bước chạy scripts/build_kaggle.py, trước pytest và các kiểm thử trình duyệt:

    FileNotFoundError: .../deliverables/portoflow_kaggle.zip

Máy phát triển có sẵn thư mục deliverables từ các lần build trước. Thư mục chỉ
chứa ZIP/checksum bị ignore nên không có trên bản clone mới. Script ghi ZIP
trước khi tạo thư mục cha; kiểm tra trong thư mục làm việc cũ đã bỏ sót lỗi này.
Các lần fail trước không được coi là kiểm thử CI đã đạt.

## Bản sửa

Ba builder tự tạo thư mục cha bằng mkdir(parents=True, exist_ok=True) trước khi
mở ZIP: build_kaggle.py, build_report_recovery.py, build_report_continue.py.
Chúng có thể chạy độc lập, không cần một builder khác tạo thư mục trước.

Không tạo thư mục thủ công trong CI để che phụ thuộc này. Không thay thuật toán,
profile, graph, ngưỡng hỗ trợ, checkpoint hoặc mã khoa học/recovery đã đóng băng.

## Kiểm tra hồi quy

tests/test_build_clean_checkout.py chạy từng builder với cây nguồn mới, không có
deliverables, raw GPS, graph hay export. Kiểm ZIP/CRC, nội dung từng file, revision
SHA và checksum của archive; chạy lại để kiểm thư mục đã tồn tại cũng dùng được.

- Trước sửa: cả 3 trường hợp fail đúng FileNotFoundError.
- Sau sửa: cả 3 trường hợp đạt.

## Kiểm tra toàn bộ từ nguồn sạch

Tạo bản clone cục bộ mới của 2c5f3c1, áp đúng 3 file builder đã sửa và test mới.
Trước khi chạy, xác nhận deliverables không tồn tại. Giữ graph thật đã version
trong repo; không sao chép ZIP bị ignore, môi trường ảo, runs hoặc cache từ repo cũ.

Dùng Python 3.12 và dependency đã cài trên máy Windows, PYTHONPATH trỏ src của
bản clone mới. Thực thi thứ tự giống workflow: build_kaggle, build_report_recovery,
build_report_continue, build_coverage_audit, pytest, Node và full-app browser.
Đây là kiểm cây nguồn sạch trên Windows, không phải kiểm môi trường Linux mới.
Môi trường Ubuntu mới do GitHub Actions kiểm sau khi push.

Kết quả trên bản clone sạch: 4 builder hoàn tất; 85 kiểm thử Python đạt trong
66,54 giây; 2 kiểm thử JavaScript đạt; full-app browser đạt. Có một cảnh báo
deprecation pandas/Streamlit đã có từ trước, không có lỗi kiểm thử.

Full-app browser dùng export tổng hợp và headless profile/cổng localhost riêng;
tile nền được stub. Không mở hoặc dừng app demo của người dùng.

Kết quả GitHub cuối cần đọc tại Actions của đúng commit sửa, không suy từ việc
git push thành công. Không có xử lý GPS/matching mới trong lần sửa đóng gói này.
