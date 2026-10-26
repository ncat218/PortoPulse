# PortoFlow — kiểm tra kết quả Kaggle 2026-10-26

Report hoàn tất; đã kiểm CRC, hash các file candidate có trong gói, graph và phiên bản mã.
Đếm lại 274.320 profile = 22.860 cạnh × 12 nhóm giờ; kiểm support/nhãn/ngưỡng trên profile và độ phủ chiều dài.

Train xử lý 1,343,398/1,343,398; holdout 75,322/303,479, còn 228,157.
Train đã xử lý hết; matching thêm holdout không được đưa vào profile và không tăng độ phủ train.

| Nhóm giờ Lisbon | Có nhãn | Chưa xác định | Độ phủ |
|---|---:|---:|---:|
| weekday/00-06 | 14,636 | 8,224 | 64.02% |
| weekday/06-09 | 13,892 | 8,968 | 60.77% |
| weekday/09-12 | 15,467 | 7,393 | 67.66% |
| weekday/12-16 | 16,113 | 6,747 | 70.49% |
| weekday/16-19 | 15,796 | 7,064 | 69.10% |
| weekday/19-24 | 15,768 | 7,092 | 68.98% |
| weekend/00-06 | 15,056 | 7,804 | 65.86% |
| weekend/06-09 | 12,994 | 9,866 | 56.84% |
| weekend/09-12 | 11,512 | 11,348 | 50.36% |
| weekend/12-16 | 12,451 | 10,409 | 54.47% |
| weekend/16-19 | 11,845 | 11,015 | 51.82% |
| weekend/19-24 | 13,321 | 9,539 | 58.27% |

ETA trên 148,312 component holdout: MAE 56.93 → 51.22 giây (10.04%); RMSE 84.84 → 76.48 giây.
Các chỉ số ETA lấy từ báo cáo; ZIP không có holdout_components.csv để tính lại độc lập.

Candidate giữ trạng thái chờ QC/holdout review; chưa thay export của app.
Giữ toàn bộ Output Kaggle. Gói review nhỏ không chứa toàn bộ graph/GeoJSON/checkpoint hay manual review cases.
Cần bằng chứng checkpoint/QC để nghiệm thu; việc chạy xong không chứng minh toàn bộ pipeline/dữ liệu đã được xác thực.
