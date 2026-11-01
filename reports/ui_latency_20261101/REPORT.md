# Giao diện và độ trễ A/B — 2026-11-01

Mục tiêu: màn hình đọc được ngay, không lộ tên hàm khi nạp cache; tuyến xuất
hiện trong khoảng5giây sau click B trên ca người dùng. Không đổi cách đề xuất
đường trong đợt này.

## Kết quả đo

Thử toàn app Streamlit với trình duyệt Chrome headless mới, cổng localhost riêng,
export thật22.860cạnh `runs/preview_20261027`. A=(41.132423,-8.604602),
B=(41.135227,-8.607853), weekday00–06. Bấm chuột thật trên bản đồ, đợi lớp
tuyến và hai animation frames; không đo riêng thời gian chạy hàm Python.

| Mốc | Trước sửa (ms) | Sau sửa (ms) |
|---|---:|---:|
| Mở app đến sẵn sàng chọn A | 22600 | 25001 |
| Click B→tuyến hiện, lần1 | 8100 | 1303 |
| Click B→tuyến hiện, lần2 | 1103 | 1250 |
| Click B→tuyến hiện, lần3 | 2478 | 1612 |

Ba mẫu sau sửa đạt mốc5.000ms. Lần mở đầu chưa nhanh: app phải đọc/kiểm export,
nạp mạng đường, profile và JavaScript. Phần chuẩn bị định tuyến được đưa vào
lần mở app. Đây là đánh đổi có chủ ý; không diễn giải thành tổng khởi động nhanh hơn.
Nguyên nhân code quan sát được: graph trước đây chỉ nạp khi bắt đầu định tuyến,
profile lookup dựng lại mỗi yêu cầu, STRtree dựng riêng khi chiếu từng điểm.
Đợt này chuẩn bị một lần và dùng lại tài nguyên chỉ đọc. Chưa đo riêng tỷ trọng
từng hạng mục; không quy toàn bộ8,1giây cho Dijkstra.

Giới hạn: một máy, ba mẫu, không phải benchmark rộng hay đảm bảo mọi tuyến/máy.
Tile OSM được stub bằng ảnh rỗng để loại dao động mạng; thư viện Leaflet vẫn
tải từ CDN. Đổi nhóm giờ có thể nạp lớp đường mới. Tọa độ mouse được đổi sang
CSS pixel nên có sai số nhỏ so với nhập tọa độ số trực tiếp.
Mã tái hiện: `tests/measure_route_latency.cjs`. Dữ liệu gốc phép đo:
[trước](before.json), [sau](after.json).

## Thay đổi giao diện

- Chọn A/B, các tùy chọn trong một expander, quãng đường/ETA/tỷ lệ thiếu dữ liệu,
  bản đồ và chú giải ngắn. Giữ một vị trí thông báo để thay lời hướng dẫn bằng
  kết quả; không để lời yêu cầu chọn B nằm cạnh kết quả đã tính.
- `show_spinner=False` cho các cache; thông báo chờ dùng tiếng Việt.
- Bật Phân tích & kiểm chứng mới dựng bảng so sánh, bảng tốc độ từng đoạn, hồ sơ
  cạnh và chẩn đoán. Không chỉ thu gọn một bảng vẫn dựng ngầm.
- Nguồn tốc độ/tham chiếu trong bảng tuyến dùng nhãn tiếng Việt; số làm tròn khi
  trình bày, không làm tròn chi phí định tuyến. Không vẽ biểu đồ rỗng cho cạnh
  không có tốc độ lịch sử. Cảnh báo candidate, unknown và khả năng tham chiếu
  bất thường vẫn có trong phần kiểm chứng.

## Kiểm chứng

`browser_check.json` kiểm vòng Streamlit→Leaflet→callback→tuyến bằng graph tổng hợp:
single-click A/B, tuyến tự hiện, marker/bản đồ giữ nguyên, bảng kỹ thuật bật/tắt,
popup không rerun Python, reset và không có lỗi JavaScript/Streamlit. Test popup
được sửa để cuộn map vào view trước khi tính pixel của nét đường, tránh click
sai do layout đổi chiều cao; không đổi production handler để làm test qua.

`verification.json` đối chiếu nguyên kết quả cả bốn tuyến trên ba ca A/B thật với
commit `ccbfb9a`, hash19file nguồn khoa học, recoveryV1 và profile. Không coi các
kiểm tra này là chứng minh tuyến tối ưu ngoài thực tế hay ETA chính xác.

Toàn bộ82kiểm thử Python đạt trong69,59s,2kiểm thử chỉ mục JavaScript đạt;
browser full-app đạt. Có một cảnh báo deprecation từ pandas/Streamlit trong
bảng chẩn đoán AppTest, không có lỗi chạy. Năm kiểm thử tài nguyên chuẩn bị gồm
so sánh toàn kết quả, dùng lại lookup/STRtree, hai yêu cầu đồng thời và từ chối
profile khác nguồn. Gói nguồn45file và notebook được dựng lại; kiểm bootstrap
checksum nằm trong bộ kiểm thử đã đạt. Các test tổng hợp không được tính là
quan sát hay độ phủ thật.

Chưa có matching hoặc quan sát train mới; độ phủ50,36–70,49% giữ nguyên. QC mức
tham chiếu P85 cao bất thường và holdout chưa hoàn tất vẫn cần xử lý trước khi
nghiệm thu. Thuật toán cân bằng hiện tại giữ nguyên để trao đổi riêng.
