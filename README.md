# PortoPulse

Demo **PortoFlow**: xem giao thông taxi lịch sử trong vùng Porto **10×10 km**,
chọn điểm A/B để nhận tuyến đề xuất cân bằng thời gian–quãng đường theo giao thông lịch sử.
Các tuyến ngắn nhất, tốc độ tĩnh và ưu tiên ETA được giữ làm mốc đối chiếu.
Giao diện tiếng Việt; ứng dụng chạy cục bộ bằng Streamlit.

![Vùng nghiên cứu Porto 10×10 km](data/region_preview.png)

## Clone và chạy demo trên Windows

Cài **Git** và **Python 3.12** trước. Mở PowerShell rồi chạy:

```powershell
git clone https://github.com/ncat218/PortoPulse.git
cd PortoPulse
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements/constraints.txt -e ".[app]"
.\.venv\Scripts\python.exe scripts\run_demo.py
```

Mở **http://localhost:8502**. Giữ PowerShell chạy; nhấn `Ctrl+C` để tắt app.
Nếu không có lệnh `py` nhưng `python --version` là3.12, dùng
`python -m venv .venv` ở bước tạo môi trường.

Repo có graph đã kiểm SHA và gói profile đã tính trên Kaggle từ dữ liệu thật.
Lần mở đầu tự ghép bản xem thử vào `runs/demo` (GeoJSON khoảng192MB), có thể
mất thêm ít thời gian và cần tối thiểu2GiB trống. Những lần sau dùng lại bản đã
kiểm hash. Demo không cần raw Porto, tài khoản Kaggle hay chạy lại matching.
Không cần cài fastmm cho việc xem app.

Nếu cổng8502 đang được dùng, chọn cổng khác:

```powershell
.\.venv\Scripts\python.exe scripts\run_demo.py --port 8503
```

Mở http://localhost:8503. Nếu đã có export riêng, chạy trực tiếp:

```powershell
.\.venv\Scripts\python.exe scripts\launch_app.py --export "DUONG_DAN_TOI_EXPORT"
```

## Chơi thử app

1. Chọn **weekday/weekend** và khung giờ **Europe/Lisbon** ở thanh bên.
2. Xem **Bản đồ giao thông**, bấm vào đường để xem tốc độ, số chuyến, taxi và ngày hỗ trợ.
3. Chuyển sang **Chọn hành trình**. Bấm **A · Điểm đi**, chọn A trên bản đồ;
   bấm/chọn tiếp B. Có đủ hai điểm, app tự tính tuyến. Có thể nhập tọa độ trong
   **Nhập tọa độ A/B**, đổi A↔B hoặc chọn lại.
4. App tự chọn **Đề xuất cân bằng thời gian–quãng đường**. Thẻ giải thích công bố
   đi thêm bao nhiêu mét/phần trăm so với đường ngắn nhất và ETA ước lượng thay đổi
   bao nhiêu giây. Bảng so sánh giữ các mốc ngắn nhất, tốc độ tĩnh và ưu tiên ETA;
   các phương án có thể trùng đường đi.
5. Mở **Ưu tiên thời gian hay quãng đường** để điều chỉnh. Mặc định80% thời gian,
   20% quãng đường là sở thích đánh đổi của demo, không phải độ chính xác80% hay
   cam kết lợi ích ngoài thực tế. Giá trị cao hơn sẵn sàng đi vòng để giảm ETA.

Tuyến bắt đầu/kết thúc tại vị trí chiếu của A/B trên đoạn đường gần nhất,
bao gồm phần cạnh đầu và cuối, thay vì chỉ đi đến nút giao gần nhất.
Đường một chiều được giữ đúng. Nếu chọn A/B trong tòa nhà hoặc ngoài mạng đường,
nét đứt nối tới đường chỉ là khoảng cách hình học, không phải tuyến đi bộ/ô tô
đã kiểm chứng và không được tính vào ETA.

## Thao tác bản đồ và hiệu năng

Bản đồ giữ nguyên trong trình duyệt khi chọn A/B hoặc đổi tuyến. Sau lần nạp
lớp đường, các cập nhật chỉ gửi điểm và tuyến; kéo/zoom, xem popup không chạy
lại Python. Lớp đường chỉ vẽ các cạnh giao vùng đang xem, giữ đúng màu và hai
chiều. Đổi nhóm ngày/giờ cần nạp lớp đường mới; tải lại trang tự yêu cầu lại dữ
liệu nếu bộ nhớ trình duyệt đã mất. Bảng và biểu đồ chi tiết nằm ngoài phần
cập nhật hành trình. Lần mở đầu vẫn cần đọc/kiểm hash export và nạp thư viện
bản đồ qua Internet; tính tuyến mới vẫn mất thời gian riêng.

Phép đo cục bộ trên22.860cạnh: HTML nền Folium trước đây khoảng14,49MB;
đối số cập nhật tuyến mới khoảng5,93KB sau xác nhận nạp lớp đường. Đây là số
byte và chi phí dựng dữ liệu, không phải cam kết FPS hoặc độ trễ trên mọi máy.
[Đo lường và kiểm chứng](docs/MAP_PERFORMANCE.md).

## Đọc màu và ETA

| Màu | Ý nghĩa |
|---|---|
| Xanh lá | Di chuyển tương đối bình thường |
| Vàng | Chậm tương đối |
| Đỏ | Chậm nhiều tương đối |
| Xám | Chưa xác định, chưa đủ bằng chứng |
| Viền xanh dương | Đường đi đang chọn; màu bên trong vẫn là tình trạng cạnh theo đúng chiều xe chạy |

Hai chiều của cùng một đường có thể có màu khác nhau. Các đường trùng hình học
được tách nhẹ thành nét song song trên lớp bản đồ để nhìn được cả hai chiều;
phép tách nét chỉ dùng để hiển thị, không thay hình học dùng tính quãng đường.

ETA dùng tốc độ lịch sử, giữ khung giờ khởi hành cho toàn tuyến. Đoạn thiếu
dữ liệu dùng proxy dự phòng và được công bố trong tỷ lệ chưa xác định.
Đề xuất cân bằng dùng tốc độ lịch sử theo nhóm ngày/giờ để tính thời gian qua
từng cạnh. Đoạn chậm tốn thời gian hơn; màu đỏ/vàng không bị phạt thêm lần nữa.
Chi phí chọn tuyến còn cân nhắc tỷ lệ đi vòng và phạt phần chưa xác định.
ETA trong bảng dùng cùng một bộ ước lượng cho mọi phương án. Đây chưa phải
thời gian thực tế đo được hoặc bằng chứng tiết kiệm thời gian ngoài đường.

Quy tắc hiện tại tối thiểu hóa `alpha*T_risk/T_short + (1-alpha)*D/D_short`
trên toàn graph có hướng, với `alpha=0.8` mặc định. `D_short` và `T_short` là
quãng đường và ETA lịch sử của tuyến ngắn nhất cho chính A/B; `T_risk` bằng ETA
cộng phần phạt hiện có cho thời gian trên đoạn chưa xác định (hệ số2).
Đây là tổng chi phí cộng được trên cạnh nên vẫn dùng Dijkstra hai chiều; tuyến
cân bằng được tìm riêng, có thể khác cả ba mốc so sánh. Không đặt trần cứng cho
tỷ lệ đi vòng. [Chi tiết chính sách đề xuất](docs/BALANCED_ROUTING.md).

Ví dụ kiểm thử theo số liệu ảnh demo: tuyến1.0395km/3.5194phút và tuyến
1.2699km/3.3832phút. Với80/20, quy tắc cân bằng chọn tuyến ngắn hơn thay vì
đi thêm230m chỉ để giảm ETA khoảng8giây. Khi tốc độ trên đường chính giảm mạnh,
đề xuất có thể chuyển sang đường vòng. Đây là ví dụ tổng hợp để kiểm tra hành vi,
không phải xác minh lợi ích thực tế của đúng lần bấm A/B trong ảnh.

## Kết quả hiện có và giới hạn

Graph cố định có **22.860 cạnh có hướng**, context matching26.254cạnh.
Profile có274.320 tổ hợp cạnh–nhóm giờ. Train đã xử lý **1.343.398/1.343.398**
chuyến đủ điều kiện; holdout xử lý **75.322/303.479**, còn228.157chuyến.
**Chưa khung giờ nào đạt80% độ phủ.**

| Giờ Lisbon | Ngày thường | Cuối tuần |
|---|---:|---:|
| 00–06 | 64,02% | 65,86% |
| 06–09 | 60,77% | 56,84% |
| 09–12 | 67,66% | 50,36% |
| 12–16 | 70,49% | 54,47% |
| 16–19 | 69,10% | 51,82% |
| 19–24 | 68,98% | 58,27% |

Trên148.312 component holdout được chấm, Kaggle báo MAE ETA56,93→51,22giây
khi dùng profile khung giờ thay tốc độ tĩnh. Review ZIP không có CSV từng
component nên chỉ số này chưa được tính lại độc lập trên máy cục bộ.

**Bản demo là candidate đang chờ kiểm QC/holdout; không phải giao thông trực tiếp.**
Các tốc độ cạnh được nội suy từ khoảng GPS15giây. Graph OSM hiện tại có thể khác
mạng đường thời kỳ dữ liệu2013–2014. Train/holdout tách nguyên chuyến;
holdout không được đưa vào profile. Giữ support3chuyến/2taxi/2ngày và ngưỡng
tỷ lệ0,7/0,4; unknown giữ xám. Chạy nốt holdout để hoàn thiện đánh giá không làm
tăng độ phủ train. [Báo cáo kiểm tra](reports/real_run_20261026/REPORT.md).

Chẩn đoán bổ sung ngày28/10:1.568cạnh không có lượt hợp lệ ở cả12nhóm giờ.
Mỗi nhóm còn4.017–7.761cạnh chưa có lượt, và2.730–3.587cạnh có lượt nhưng
thiếu hỗ trợ. Chưa bổ sung được quan sát train mới, vì vậy độ phủ chưa tăng.
[Phân tích khoảng trống và hướng bổ sung](docs/COVERAGE_GAPS.md).

Để đếm lại từ export cục bộ (chỉ đọc):

```powershell
.\.venv\Scripts\python.exe scripts\audit_coverage_gaps.py --export runs\demo --output artifacts\coverage_gaps.json
```

## Pipeline và khôi phục Kaggle

Xử lý raw toàn nguồn chạy trên Kaggle CPU; demo không chạy bước nặng trên laptop.

- [Notebook pipeline đầy đủ](notebooks/PortoFlow_Kaggle.ipynb)
- [Notebook kiểm toán độ phủ/QC từ Output gốc](notebooks/PortoFlow_Coverage_Audit.ipynb) · [Cách chạy](docs/COVERAGE_AUDIT_KAGGLE.md)
- [Khôi phục report sau timeout](docs/REPORT_RECOVERY.md)
- [Tiếp tục ledger sau lỗi dung lượng](docs/REPORT_CONTINUE.md)
- [Thiết kế pipeline](docs/PIPELINE.md) · [Tiến độ](STATUS.md)

Để xây gói code cho notebook từ repo:

```powershell
.\.venv\Scripts\python.exe scripts\build_kaggle.py
```

Để chạy kiểm thử, cài thêm test (và fastmm nếu muốn chạy native synthetic E2E):

```powershell
.\.venv\Scripts\python.exe -m pip install -c requirements/constraints.txt -e ".[app,test,fastmm]"
.\.venv\Scripts\python.exe scripts\build_kaggle.py
.\.venv\Scripts\python.exe scripts\build_report_recovery.py
.\.venv\Scripts\python.exe scripts\build_report_continue.py
.\.venv\Scripts\python.exe scripts\build_coverage_audit.py
.\.venv\Scripts\python.exe -m pytest -q
```

Các fixture kiểm thử được ghi nhãn SYNTHETIC, tách biệt với kết quả Kaggle thật.
Không có lịch cập nhật tự động hằng ngày; cập nhật sau mốc hữu ích hoặc khi cần.

Nguồn GPS: [UCI Taxi Service Trajectory Prediction](https://archive.ics.uci.edu/dataset/339/taxi+service+trajectory+prediction+challenge+ecml+pkdd+2015)
và [Kaggle Porto](https://www.kaggle.com/competitions/pkdd-15-predict-taxi-service-trajectory-i/data).
Graph ©[OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL.
Repo không chứa raw GPS, ledger13GB hoặc toàn bộ matching checkpoints.
