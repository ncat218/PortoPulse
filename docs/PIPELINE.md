# Porto — vùng 10×10 km và toàn nguồn dữ liệu

Ngày chốt phạm vi: **2026-10-25**. Người dùng chọn: **“10x10 đi, tôi thích 10”**,
sau khi yêu cầu thử toàn bộ dữ liệu và chấp nhận đường thiếu quan sát giữ trạng
thái **Chưa xác định**.

## Phạm vi mới

- Vùng nghiên cứu hình vuông **10.000 × 10.000 m**, diện tích **100 km²**,
  dựng trong hệ tọa độ mét EPSG:32629 tại Porto. Không quy đổi kích thước bằng
  một khoảng kinh/vĩ độ cố định. Tâm và tọa độ polygon phải được lưu trong
  metadata khi dựng graph. Tâm giữ vùng cũ: **[-8.63, 41.16]**.
- Số cạnh có hướng theo mạng đường thực trong vùng; không cố định ở 15.000.
  Thống kê riêng cạnh trong vùng và cạnh thuộc vùng đệm phục vụ matching.
- Duyệt toàn bộ nguồn Porto đến EOF; xử lý hết các đoạn GPS train hợp lệ trong
  vùng, có checkpoint để tiếp tục khi hết một phiên. Hoàn tất lượt xử lý được
  xác định bằng việc xử lý hết input phù hợp, thay vì dừng khi đạt 80% độ phủ.
- Xét cả chuyến đi xuyên vùng. Thiết kế mới cần xử lý các block liên tục trong
  vùng, giữ ID chuyến/taxi và chỉ số, thời gian GPS gốc; không nối qua khoảng
  ngoài vùng hoặc GPS thiếu. Chính sách này cần được kiểm chứng trước bulk.
- Train và holdout tách biệt theo thời gian trên nguyên chuyến trước khi cắt
  block. Holdout dùng để đánh giá, không bổ sung vào profile train.
- Giữ **Chưa xác định** khi thiếu hỗ trợ. Công bố độ phủ theo cạnh, chiều dài
  đường, từng khung giờ và các tuyến A→B; 80% là mục tiêu tham khảo của thiết kế
  mới. Các ngưỡng support, tốc độ và kiểm chất lượng cần được ghi rõ, kiểm chứng.

## Đã triển khai

Đã dựng graph OSM thật bằng OSMnx2.1.1: **22.860 cạnh có hướng trong vùng**,
**26.254 cạnh trong graph matching gồm đệm500m**. Chiều dài có hướng cắt trong
vùng là2.055,936km, không phải chiều dài đường vật lý không phân hướng.
Polygon metric có diện tích đúng100.000.000m². Graph dùng nội dung WGS84 và
checksum cho version, lưu tại `data`.

Đã có luồng riêng trong `src/portoflow/pipeline.py`: graph → quét EOF →
matching mọi parent đủ điều kiện trong cả train/holdout → báo cáo và candidate
export. Decoder fastmm0.3.2 và per-gap QC được tái dùng; initializer riêng cho
graph lớn giữ native Network owner sống. Không đổi adapter/gate của lượt cũ.

Mọi block liên tục≥6GPS trong vùng đệm có đoạn chạm core đều được xét, không
giới hạn2block/parent hoặc yêu cầu90%GPS toàn chuyến ở trong vùng. Block bị cắt
trim1gap mỗi đầu; partial giữ chính sách90%gap hợp lệ và tối thiểu3gap sau trim.
Khoảng cách và thời lượng được cắt theo phần cạnh thật trong square100km².
Các block vẫn dùng một ID chuyến/taxi; profile chỉ nhận train.

**Chưa matching toàn dữ liệu Porto trên graph mới.** Candidate export sau chạy
còn cần review GPS/native, độ bền và đánh giá ETA holdout. Code tính MAE/RMSE
static/bucket trên cùng các component holdout gồm≥3gap GPS gốc liên tục còn
đủ15s/gap; loại gap cắt biên/thiếu thời lượng. Target là15s×sốgap, không lấy
thời lượng nội suy một phần cạnh làm ground truth. Không diễn giải thành độ
chính xác toàn chuyến hoặc lợi ích tuyến thay thế, không tự kích hoạt app.


## Chạy trên Kaggle

1. Tạo/cập nhật code Dataset từ `deliverables/portoflow_kaggle.zip`.
2. Import `notebooks/PortoFlow_Kaggle.ipynb` của dự án PortoFlow.
3. Attach code Dataset và raw Porto `train.csv.zip`/`train.csv` đầy đủ. Gói code
   có graph mới đã kiểm SHA; không cần artifact từ project khác.
4. CPU/None, InternetOn, SaveVersion → Save&RunAll. Nếu nhiều nguồn train,
   chọn `SOURCE` cụ thể ở cell đầu. Notebook chạy fixture và native probe trước
   khi mở raw/matching Porto.
5. Gửi `portoflow_review.zip`; **giữ toàn bộ Output** gồm thư mục
   `portoflow_run`, nhất là SQLite, graph và region_batches.

Trần: graph600s, scan5.400s, matching21.600s, report1.800s mỗi phiên; RAM mềm
12.000MiB/output12GiB. Setup/probes có cap riêng theo lệnh notebook. Đây là
giới hạn tài nguyên, chưa phải dự báo toàn nguồn hoàn tất trong một phiên.

Hết phiên thì attach Output mới làm Input, đặt `RESUME` đến đúng thư mục
`portoflow_run`. Giữ bộ code và versions dependency từ lượt trước;
notebook dùng environment freeze khi resume. Checkpoint theo20parent; SHA
index/batches, graph, code, config và runtime phải khớp. CSV trong ZIP vẫn phải
giải nén lại prefix khi scan chưa EOF, nhưng GPS đã commit không parse lại.

80% chỉ là mốc tham khảo; matching đi đến hết các parent đủ điều kiện. Nếu
hết tài nguyên hoặc còn parent chưa xử lý, trạng thái ghi PARTIAL; không gọi
đó là đã chạy xong toàn nguồn. Không ghép checkpoint khác graph vào lượt này.
