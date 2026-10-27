# Khoảng trống độ phủ, 2026-10-28

Đây là chẩn đoán trên profile đã kiểm hash, không phải lần matching mới hay
tăng độ phủ. Giữ22.860cạnh có hướng,12nhóm giờ, cutoff2014-05-01UTC và
support3chuyến/2taxi/2ngày. Không đưa holdout vào train hoặc đổi cạnh xám thành
màu theo suy đoán. SHA manifest/profile nằm trong coverage_gap_audit.json.

## Đếm lại trên export thật

| Nhóm | Đã phân loại | Chưa có lượt hợp lệ | Có lượt, thiếu hỗ trợ | Cạnh gần đủ hỗ trợ |
|---|---:|---:|---:|---:|
| weekday00–06 | 14.636 | 4.994 | 3.230 | 1.268 |
| weekday06–09 | 13.892 | 5.958 | 3.010 | 1.133 |
| weekday09–12 | 15.467 | 4.661 | 2.732 | 1.098 |
| weekday12–16 | 16.113 | 4.017 | 2.730 | 1.059 |
| weekday16–19 | 15.796 | 4.293 | 2.771 | 1.107 |
| weekday19–24 | 15.768 | 4.287 | 2.805 | 1.117 |
| weekend00–06 | 15.056 | 4.794 | 3.010 | 1.207 |
| weekend06–09 | 12.994 | 6.597 | 3.269 | 1.220 |
| weekend09–12 | 11.512 | 7.761 | 3.587 | 1.271 |
| weekend12–16 | 12.451 | 6.850 | 3.559 | 1.277 |
| weekend16–19 | 11.845 | 7.474 | 3.541 | 1.316 |
| weekend19–24 | 13.321 | 6.121 | 3.418 | 1.284 |

Mỗi hàng có cùng mẫu số22.860. Các lý do chưa xác định trong bảng tách biệt;
thất bại từng ngưỡng chuyến/taxi/ngày trong JSON có thể chồng nhau.
"Gần đủ" nghĩa đã có lượt, median/reference hợp lệ và mỗi ngưỡng thiếu không
quá1. Đây là danh sách tìm bằng chứng mới, không phải số cạnh có thể tự nâng màu.
Một chuyến mới chưa chắc bổ sung taxi hoặc ngày độc lập đang thiếu.

Có1.568cạnh không có lượt hợp lệ ở bất kỳ nhóm giờ nào;1.295là residential,
191living_street. Ngoài ra có10cạnh mang tag highway=ladder cần kiểm tra nguồn
graph/khả năng ô tô đi được. Chưa loại hay sửa chúng; thay graph/mẫu số cần
một phiên bản và đánh giá riêng. Graph hiện tại có thể khác mạng đường2013–2014.

## Việc có thể làm tiếp

Train đã xử lý1.343.398/1.343.398parent đủ điều kiện. Chạy lặp lại cùng nguồn,
cùng matcher/QC không tạo thêm quan sát độc lập. Chạy nốt228.157holdout còn lại
giúp đánh giá, không tăng độ phủ train.

1. Trên Kaggle CPU, đọc checkpoint gốc và QC các parent train bị loại, đối chiếu
   các cạnh thiếu với residual/gap/khả năng đi ô tô và bản đồ giai đoạn dữ liệu.
   Chỉ khôi phục bằng chứng nếu phát hiện lỗi kỹ thuật có thể sửa và kiểm chứng;
   không nới guard nhằm ép đạt80%. Một phép chạy cần ngân sách và resume cụ thể.
2. Ưu tiên dữ liệu train thực sự chưa dùng và độc lập, đúng vùng/ngày/giờ trước
   cutoff. Danh sách100ví dụ cạnh gần ngưỡng, kèm loại đường/chiều dài/thiếu từng
   loại hỗ trợ được ghi trong báo cáo để chọn mục tiêu. Chưa có nguồn mới được
   nhập hoặc xác minh; không tải dữ liệu nặng về laptop.
3. Sau khi có bằng chứng mới, deduplicate parent IDs, giữ split, matching/QC,
   dựng candidate riêng rồi đếm lại12nhóm. Không hứa80% trước khi có kết quả.

Checkpoint gốc/ledger SQLite và raw QC không nằm trong repo; gói review nhỏ
không đủ kiểm tra lại các quyết định loại parent hay tái tính support độc lập.
Vì vậy đợt này dừng ở chẩn đoán có bằng chứng, không submit lại job matching
toàn nguồn hoặc thay export phục vụ hiện tại.
