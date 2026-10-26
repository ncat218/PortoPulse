# Quy trình phát triển độc lập

Mọi lệnh chạy từ gốc repo này. Không import package hoặc đọc config, checkpoint,
venv hay export của dự án5.542cạnh. Các thuật toán nền được sao chép có chọn lọc
vào package riêng để phát triển và kiểm thử độc lập.

Sau mỗi mốc cần cập nhật: sửa code/tài liệu trong repo này, chạy kiểm tra phù hợp,
ghi kết quả thật và giới hạn vào STATUS.md, kiểm diff và file chuẩn bị commit,
commit mô tả thay đổi rồi push nhánh main. Không tạo commit rỗng để ghi nhận
ngày; không lên lịch cập nhật hằng ngày.

Git chỉ chứa code, notebook, graph công khai có attribution, tài liệu và fixture
tổng hợp. Raw Porto, credentials, venv, native cache và bulk outputs nằm trong
các thư mục đã bỏ qua. Giữ checkpoints ở Kaggle Output hoặc kho dữ liệu phù hợp.

Native matching dùng Python3.12/fastmm0.3.2. Decoder và per-gap QC được tái dùng
trong repo; RegionFastMMMatcher có scope lớn riêng và hủy borrower trước owner.
Đổi graph/config/code/runtime phải tạo work mới hoặc chứng minh compatibility;
không sửa identity để ép reuse checkpoint.
