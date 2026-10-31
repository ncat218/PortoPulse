# Click A/B và hai trường hợp người dùng, 2026-10-31

## Lỗi tương tác và sửa đổi

Root cause: bindPopup của Leaflet chặn bubbling nên click ngay nét đường không
đến map.on(click). Kiểm thử component cũ chỉ click nền trống và giả lập parent;
không kiểm toàn vòng Streamlit -> callback -> marker. Đã tái hiện failure clickA
bằng app thật trên fixture SYNTHETIC trước sửa và xác nhận đạt sau sửa.

Handler của lớp đường nay nhận click A/B trực tiếp; view-only mở popup cục bộ,
không báo về Python. Marker không chặn click; instance/sequence ngăn replay và
cho phép click mới tại tọa độ cũ. Giữ component ở container path cố định khi
UI đổi từ A sang B hoặc xuất hiện tuyến. Asset JS có cache-version query.

Cảnh báo candidate vẫn giữ trong Nguồn & chất lượng dữ liệu. Số cạnh toàn vùng
nằm trong Độ phủ dữ liệu trong khung giờ; unknown của tuyến vẫn hiện cạnh ETA.
Có bảng vận tốc thực dùng tính ETA/nguồn dự phòng, thời gian từng đoạn và mức
tham chiếu. Bảng bốn tiêu chí ghi rõ có thể tạo chỉ một đường đi. Không đổi hàm
mục tiêu, trọng số, speed estimator, màu export, support/QC hoặc tập train.

## Ca1: tuyến đỏ ngắn

A(lat41.161484,lon-8.662529), B(lat41.161759,lon-8.664889), weekday09–12.
Tái hiện257,113m, ETA31,104s; cả4tiêu chí cùng5cạnh,83%chiều dài có nhãn giảm tốc.
Graph không có chiều ngược của cạnh nguồn314048657->420446037; từ node420446037
chỉ có cạnh ra420446037->314048477. Muốn xuống đường song song theo hướng
ngược không có cạnh trong graph hiện tại. Chưa xác minh chiều xe thực tế bên ngoài.
Một đường khác trong các path ETA-ranked đi1.717,58m/176,35s; không khuyến khích
chọn đường đó theo bộ tốc độ hiện tại. Kết quả Dijkstra tối ưu mô hình/graph,
không khẳng định tối ưu giao thông thực tế.

Ba cạnh đỏ tagresidential có median35,15/27,67/25,08km/h nhưng referenceP85
112,78/109,45/121,75km/h. Median/reference<0,4 nên xuất đỏ theo công thức cũ,
trong khi ETA vẫn dùng median25–35km/h. Đây là tín hiệu cần QC tham chiếu,
không chứng minh đang kẹt xe, không được ép đổi tuyến bằng phạt màu để che lỗi.

Screen trên toàn profile:1.146cạnh tag residential/living_street có reference>90km/h
(849residential,297living_street).90là ngưỡng chẩn đoán để khoanh vùng, không phải
ngưỡng QC mới hoặc khẳng định giới hạn pháp lý. Chưa tính lại P85 từ ledger/GPS,
chưa xác minh cause hay số nhãn cần sửa. Giữ nguyên export và đưa vấn đề reference
lên trước việc tối ưu độ phủ/màu phục vụ.

## Ca2: tuyến nhìn hợp lý hơn

A(lat41.174293,lon-8.655516), B(lat41.168737,lon-8.649465), weekday09–12.
Ngắn nhất913,05m/117,60s. Static, bucket và balanced cùng đi1.035,23m/112,01s.
Đề xuất khác đường ngắn nhất: thêm122,19m để giảm ETA5,58s; đoạn mang nhãn giảm
tốc303,81m xuống164,31m. Phép tính cho thấy mô hình có đổi tuyến theo tốc độ,
nhưng chênh lệch nhỏ này chưa phải lợi ích ngoài đường được đo/kiểm chứng.

## Kiểm chứng và phạm vi

browser_check.json kiểm app Streamlit thật và Leaflet thật trong Chrome ẩn,
export nhỏ SYNTHETIC, tileảnh stub. Có kiểm click ngay đường để hiệnA,B/tuyến,
popup view-only, reset, không remount và thông tin chất lượng mở xem. CI đã thêm
browser smoke test; chưa đọc kết quả GitHub CI. Tests Python giữ endpoint/màu/
one-way, event sequence và bảng ETA đúng cả khi dùng fallback.

Hai ca thật dùng tọa độ làm tròn6chữ số trong ảnh và bộ profile đã kiểm trước,
không rematching, không có quan sát hay độ phủ mới. Nguồn khoa học19file và
checkpoint giữ nguyên; thuật toán đề xuất vẫn chờ thống nhất chính sách cùng người dùng.
