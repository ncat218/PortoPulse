# Bản đồ giữ trạng thái, 2026-10-28

Thuật toán chấm điểm tuyến trong app/journey_routing.py giữ nguyên. Thay đổi
này tập trung vào việc vẽ và truyền dữ liệu, không thay matching/profile/QC.

## Cơ chế

- Component Leaflet có key ổn định; dữ liệu lớp đường gắn ID chứa run, graph,
  hash GeoJSON, nhóm ngày và giờ. Python cache gói compact, giữ nguyên tọa độ.
- Trình duyệt xác nhận đã nạp đúng ID. Các rerun sau truyền `roads=null`, chỉ
  gửi marker, hình học tuyến và khoảng nối A/B. Không gửi lại toàn bộ22.860cạnh.
- Khi iframe mất bộ nhớ mà Python còn xác nhận cũ, iframe yêu cầu lại dữ liệu;
  Python gửi lại lớp đường và nhận xác nhận mới. Đổi nhóm giờ cũng thay lớp này.
- Leaflet giữ nguyên vị trí/zoom khi cập nhật overlay. Chỉ fit tuyến khi ID
  hành trình hoặc phương án thay đổi; thao tác kéo/zoom không gọi server.
- Canvas và chỉ mục ô không gian chọn các cạnh có bounding box giao viewport
  mở rộng12%. Không bỏ lớp đường theo độ phủ; cạnh xám vẫn được vẽ. Bounding box
  có thể chọn dư cạnh ngoài màn hình nhưng không bỏ cạnh cắt ngang viewport.
- Popup/tooltip xử lý tại trình duyệt. Click chỉ báo về Python khi đang chọn
  A/B. Tình trạng từng chiều, hình học cắt đầu/cuối và marker căn giữa giữ nguyên.
- Streamlit fragment cô lập phần hành trình; A/B và lựa chọn tuyến không dựng
  lại bảng22.860mã cạnh hoặc biểu đồ chi tiết phía dưới. Đổi sidebar vẫn rerun app.

## Bằng chứng

reports/map_performance_20261028/performance.json so sánh trên cùng profile
weekday09–12 và graph22.860cạnh. Đường A/B minh họa không phải tọa độ bấm gốc.

| Phép đo | Kết quả cục bộ |
|---|---:|
| Dựng/render HTML nền Folium cũ, median3lần | 2,44s |
| HTML nền cũ | 14.491.123byte |
| Đối số component mới, nạp lớp đường ban đầu | 8.004.470byte |
| Đối số sau xác nhận, gồm tuyến đang xem | 5.934byte |
| Dựng/serialize đối số cập nhật, median7lần | 0,000166s |
| Tính tuyến mới với thuật toán giữ nguyên | 1,01s |

HTML Folium và JSON component là hai dạng payload khác nhau; số liệu không
bao gồm toàn bộ giao thức Streamlit, tốc độ mạng hoặc độ trễ người dùng.
Kiểm hash/đọc artifact, dựng index lạnh và tải CDN vẫn có chi phí ban đầu.

Kiểm thử browser dùng Leaflet thật trong Chrome headless với parent giả lập
giao thức Streamlit, chạy đủ22.860cạnh. Đạt kéo/zoom không phát sự kiện server,
click A/B, overlay không remount/reset viewport, view-only không gọi Python,
đổi nhóm giờ, tải iframe lại và tự lấy lại roads. Tile ảnh được stub; đây không
phải đo FPS hay end-to-end app trong browser. AppTest kiểm phần Python UI riêng.
Xem browser_check.json và validation.json cùng thư mục báo cáo.

## Chạy lại kiểm tra

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_map.py --export runs\demo --report artifacts\map_perf.json --fixture artifacts\map_component\fixture.json
node --test tests\map_frontend.test.cjs
```

Kiểm browser tùy chọn cần Playwright và Chrome/Chromium; không phải dependency
chạy demo. Có thể đặt NODE_PATH tới nơi cài Playwright và PORTOFLOW_TEST_BROWSER
tới executable trình duyệt rồi chạy `node tests/verify_map_browser.cjs`.
Harness dùng cổng localhost tạm và hồ sơ trình duyệt mới, không chạy app Streamlit.
