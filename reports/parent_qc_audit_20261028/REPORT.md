# Kết quả kiểm toán parent/QC thật, 2026-10-28

Notebook trả PARENT_QC_AUDIT_COMPLETE, đã duyệt70.936/70.936batch sẵn có.
ZIP review3.911byte kiểm CRC đạt; SHA nguồn và các tổng parent khớp receipt
Kaggle trước. Đây là kiểm tính nhất quán của metadata; SQLite và ZIP matching
gốc không có trong gói nhỏ để tự hash lại trên laptop. Chưa kiểm độc lập raw GPS.

| Train | Parent |
|---|---:|
| Đã xử lý | 1.343.398 |
| Có quan sát core được chấp nhận | 1.183.504 |
| Chưa có quan sát core được chấp nhận | 159.894 (11,90%) |
| Không có gap qua block QC | 158.820 (99,33% của nhóm chưa có quan sát) |
| Mọi native block đều có status không thành công | 485 |
| Có accepted_gaps tại block QC nhưng cuối cùng không có quan sát core | 589 |

485+158.820+589=159.894; đây là các nhóm parent tách biệt. Native status và
rejected_gap_reason trong summary là số block/gap, không cộng chúng thành parent.
Holdout vẫn75.322/303.479đã xử lý,67.421parent có quan sát core; chỉ đếm đối chiếu,
không đưa vào profile. Accepted observation rows được báo95.252.795train và
5.607.523holdout; chưa đọc lại Parquet để tự tính các tổng này.

## Phát hiện từ75ví dụ được lưu

Mỗi nhóm chưa có quan sát lấy25ví dụ đầu tiên, không phải mẫu ngẫu nhiên.
25/25ví dụ của nhóm không có gap qua QC là partial và có valid_gaps/(sốđiểm-1)
từ50%đến89,04%, dưới guard90%. Đối chiếu mã frozen segment_qc.py cho thấy
điều kiện này đủ để loại các ví dụ đó theo chính sách hiện tại. Chưa kết luận
158.820parent đều có đúng nguyên nhân này: residual, fragmentation hoặc các
bước sau có thể khác ở parent không nằm trong mẫu.

25ví dụ của nhóm native không thành công có15failed_quality và10failed.
25ví dụ có block accepted_gaps nhưng0quan sát core gồm23success và2partial.
Accepted_gaps được ghi trước trimming/clipping/lọc tốc độ; chỉ các record này
không chứng minh lỗi clipping, không xác định cạnh xám có thể khôi phục.

## Quyết định tiếp theo

Ưu tiên kiểm tra raw/native của một tập train nhỏ trong nhóm partial, để biết
gap bị mất vì native path, candidate/residual, hình học/chiều đường hay dữ liệu
GPS. Dùng source row/trip ID đã lưu để chọn đúng parent; không đánh đồng partial
với dữ liệu tốt. Nếu chạy trên Kaggle phải pin graph, phiên bản matcher và
ngân sách hữu hạn; so sánh nguyên trạng trước khi đề xuất sửa lỗi hoặc phương pháp.

Không hạ guard90%, không dùng holdout, không đổi support3/2/2, không chạy lại
toàn bộ matching với cùng tham số. Nếu cân nhắc đổi quy tắc chọn đoạn/guard,
phải mô tả thay đổi để review và đánh giá candidate riêng trước khi phục vụ.

Đợt audit chưa thêm quan sát hoặc profile mới; độ phủ12nhóm vẫn50,36–70,49%.
Không có bằng chứng hứa nâng lên80%. App và thuật toán đề xuất giữ nguyên.
Giữ Saved Output portoflow_coverage_audit/audit_state.sqlite trên Kaggle.

Xem summary.json (tổng được báo) và verification.json (kiểm tra cục bộ/giới hạn).
Không đưa các trip IDs trong examples lên repo; chỉ công bố số tổng hợp.
