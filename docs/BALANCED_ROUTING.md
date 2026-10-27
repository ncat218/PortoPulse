# Đề xuất tuyến theo giảm tốc lịch sử và mức đi vòng

Mục tiêu app là tự đề xuất tuyến có đánh đổi rõ ràng giữa thời gian, quãng đường
và phần chưa đủ dữ liệu. Đường ngắn nhất chỉ là mốc để chuẩn hóa và giải thích.
Mã nằm trong app/journey_routing.py; package khoa học và profile Kaggle không đổi.

## Tín hiệu giao thông được dùng thế nào?

Chọn nhóm ngày và giờ Lisbon, lấy median tốc độ train cho cạnh đủ hỗ trợ.
Đoạn đi qua dài L mét với tốc độ v km/h có thời gian `t=3.6*L/v` giây.
Nếu thiếu hỗ trợ, giữ thứ tự dự phòng hiện có: tốc độ tĩnh train, maxspeed,25km/h;
đồng thời công bố unknown. Màu chậm tương đối phục vụ giải thích; không cộng thêm
phạt đỏ/vàng vì ảnh hưởng chậm đã đi vào t qua tốc độ. Đây là profile lịch sử,
không phải phát hiện kẹt xe trực tiếp.

## Hàm mục tiêu

Tính đường ngắn nhất cho A/B sau khi chiếu chúng lên đoạn đường đúng chiều.
Gọi D0 là độ dài đường này và T0 là ETA theo giờ của nó. Với một đường đi P:

```
T(P)     = tổng ETA lịch sử trên P
Tu(P)    = phần ETA trên các đoạn chưa xác định
Trisk(P) = T(P) + (m-1)*Tu(P), m=2 theo cấu hình hiện có
J(P)     = alpha*Trisk(P)/T0 + (1-alpha)*D(P)/D0
```

Mặc định alpha0.8; người dùng đổi trong khoảng0–1. Đây là sở thích sản phẩm,
chưa được hiệu chỉnh bằng nghiên cứu người dùng hay ground truth hành trình.
Nó không phải xác suất ETA đúng, không đặt trần20% đi vòng và không bảo đảm
ETA thực tế nhỏ nhất. Chuẩn hóa theo chính hành trình tránh cộng trực tiếp giây
và mét với đơn vị khác nhau.

D0/T0 cố định sau bước tìm đường ngắn nhất; các thành phần J đều cộng được
trên cạnh và không âm. Vì vậy có thể tìm minimum J bằng Dijkstra hai chiều,
không chỉ chọn một trong ba đường có sẵn. Các mốc tốc độ tĩnh và ưu tiên ETA
vẫn được tính để đánh giá. Tại alpha0 ưu tiên chiều dài; alpha1 khớp mục tiêu
ETA có phạt unknown hiện có.

## Hiển thị và kiểm chứng

App mặc định hiển thị đề xuất cân bằng; đổi A/B, giờ hoặc mức ưu tiên sẽ tính lại.
Công bố phần trăm đi vòng, số mét đi thêm, ETA thay đổi và quãng đường chậm/unknown.
ETA hiển thị chưa cộng phạt unknown. Mọi phương án dùng chung bộ tốc độ theo giờ
khi so sánh; màu của cạnh đi qua được giữ nguyên. Phần đầu/cuối được tính theo
đúng chiều dài đã cắt. Đoạn nối A/B ngoài đường không tính vào ETA ô tô.

Kiểm thử tổng hợp bao gồm:

- Tình huống đi thêm230m để giảm khoảng8giây không được chọn ở mức80/20.
- Tăng ưu tiên thời gian cho phép chọn tuyến dài hơn trong cùng ví dụ.
- Chỉ đổi tốc độ lịch sử, giữ nguyên graph, làm đề xuất đổi sang đường vòng.
- Tìm được một tuyến cân bằng thứ ba không trùng ba mốc so sánh.
- Unknown được công bố và chịu đúng khoản phạt hiện có; giá trị ưu tiên sai bị từ chối.

Các giới hạn còn lại: profile theo khung giờ cố định, dữ liệu lịch sử, holdout
chưa hết và chưa có turn restrictions/chi phí giao lộ. Đề xuất tối ưu theo mô hình
J và graph hiện có; chưa chứng minh là lựa chọn tốt nhất ngoài thực tế.
