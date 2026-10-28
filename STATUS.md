# PortoPulse — nhận kiểm toán parent/QC thật 2026-10-28

Đã nhận portoflow_coverage_audit_review.zip, CRC và đối chiếu receipt đạt.
Audit đủ70.936batch; train1.343.398parent,1.183.504có quan sát core hợp lệ,
159.894chưa có. Trong nhóm chưa có:158.820không có gap qua block QC,485mọi
native block có status không thành công,589có block accepted_gaps nhưng0core.
25ví dụ của nhóm zero-QC đều partial và valid-gap fraction dưới90%; mẫu có
chọn trước, chưa đại diện toàn bộ nhóm hay chứng minh lỗi. Giữ nguyên guard.

Độ phủ chưa tăng; chưa matching/profile mới. Bước hữu ích kế tiếp là kiểm raw/
native trên tập train nhỏ, không chạy lại toàn bộ hay nới QC. ZIP gốc/SQLite
audit không có trong gói nhỏ; chưa hash lại hoặc kiểm độc lập raw ở laptop.
Xem reports/parent_qc_audit_20261028/REPORT.md và verification.json.

---
# PortoPulse — chuẩn bị kiểm toán parent/QC trên Kaggle 2026-10-28

Có notebook riêng PortoFlow_Coverage_Audit.ipynb, tự chứa mã stdlib và checksum;
chỉ cần Input Output matching gốc anhthu128/porto-flow có _output_.zip5,48GB.
Không cần Dataset code, pip install, Internet hoặc ledger recovery13GB.
Ngân sách45phút, RAM mềm1.536MiB, Output mềm768MiB; đọc metadata theo batch,
deduplicate parent/source row, đối chiếu summary và giữ state resume đã seal.
Gói review nhỏ chỉ gồm JSON, không chứa SQLite. App/thuật toán/profile giữ nguyên.

11 kiểm thử mới đạt, gồm thực thi bootstrap/cell và review ZIP; toàn bộ71kiểm
thử Python đạt. Đây là
chuẩn bị công cụ, chưa chạy trên Saved Output thật, chưa có quan sát/độ phủ mới.
Máy không có Kaggle CLI/cấu hình auth được xác minh; chưa submit job từ đây.
Xem docs/COVERAGE_AUDIT_KAGGLE.md và reports/coverage_audit_preparation_20261028.json.

---
# PortoPulse — tối ưu bản đồ và chẩn đoán độ phủ 2026-10-28

Thay dựng lại Folium bằng component Leaflet giữ trạng thái và giao thức xác
nhận lớp đường. Sau nạp lớp nền, A/B/tuyến chỉ gửi overlay; kéo/zoom và popup
ở trình duyệt, chỉ vẽ cạnh giao viewport. Streamlit fragment cô lập hành trình.
Đổi nhóm giờ, tải lại iframe có cơ chế nạp lại; màu từng chiều và điểm cuối giữ
đúng hình học. Không thay thuật toán đề xuất, nguồn khoa học, profile hay guard.

Đo22.860cạnh: HTML nền cũ14.491.123byte, cập nhật overlay mới5.934byte sau xác
nhận. Dựng nền cũ median2,44s; không diễn giải thành FPS hay độ trễ toàn app.
60 kiểm thử Python và2 kiểm thử chỉ mục JavaScript đạt. Kiểm thử browser
Leaflet thật chạy riêng đạt, có stub tile; AppTest kiểm Python UI.
Xem docs/MAP_PERFORMANCE.md và reports/map_performance_20261028.

Audit profile thật cho1.568cạnh chưa có lượt hợp lệ ở cả12nhóm. Mỗi nhóm có
4.017–7.761cạnh chưa có lượt và2.730–3.587cạnh có lượt nhưng thiếu hỗ trợ.
Độ phủ giữ50,36–70,49%; chưa có dữ liệu train mới được nhập. Có danh sách ưu
tiên cạnh gần ngưỡng và hướng QC checkpoint gốc; không nới ngưỡng, không nhập
holdout vào train, không submit lại toàn nguồn. Xem docs/COVERAGE_GAPS.md.

---
# PortoPulse — đề xuất cân bằng theo giảm tốc lịch sử 2026-10-27

App mặc định đề xuất balanced, dùng ETA theo giờ và tỷ lệ quãng đường so với
đường ngắn nhất. Mặc định trọng số80/20, người dùng điều chỉnh được; đây là
sở thích đánh đổi, không phải độ chính xác. Phần unknown chịu khoản phạt cũ;
không phạt màu đỏ/vàng thêm lần nữa. Dijkstra tìm minimum tổng chi phí chuẩn hóa
trên graph có hướng, gồm vị trí A/B giữa cạnh. Các tuyến cũ là mốc đối chiếu.

UI công bố mét/phần trăm đi vòng, ETA thay đổi và quãng đường chậm/unknown.
54 kiểm thử đạt, gồm tình huống230m/8giây, đổi dữ liệu giảm tốc làm đổi tuyến,
tìm tuyến cân bằng khác ba mốc và điều chỉnh ưu tiên trên Streamlit AppTest.
Một A/B minh họa với profile thật qua6khung giờ cho2đường đề xuất khác nhau;
không phải đúng tọa độ bấm gốc trong ảnh, chưa đo lợi ích ngoài thực tế.
19 file khoa học và matching checkpoints giữ nguyên; không có matching mới.

Xem docs/BALANCED_ROUTING.md và reports/balanced_routing_20261027.
Hiệu năng vẽ lại bản đồ vẫn cần tối ưu riêng; phép đo cũ được ghi rõ commit nguồn.

---
# PortoPulse — sửa điểm B, màu chiều đường và demo 2026-10-27

App định tuyến tới vị trí A/B trên cạnh gần nhất, gồm cạnh đầu/cuối bị cắt,
đúng chiều xe chạy. Điểm ngoài đường có đoạn nối nét đứt không tính ETA.
Marker A/B căn giữa đúng tọa độ. Hai chiều trùng hình học được tách nét trên
lớp nền; tuyến giữ profile/màu của chính cạnh đang đi. Cache tuyến cũ được làm mới.

44 kiểm thử đạt, gồm8 kiểm tra endpoint/màu/đường một chiều và Streamlit AppTest.
Kiểm tra nhỏ trên graph Porto thật từ cạnh trong ảnh đạt; không có matching mới.
19 file khoa học giữ nguyên byte. Xem reports/app_route_fix_20261027.

README hướng dẫn clone https://github.com/ncat218/PortoPulse.git và chạy
scripts/run_demo.py; repo có graph và review ZIP để ghép preview cục bộ.
Không commit venv, raw GPS, matching ledger hoặc GeoJSON192MB đã ghép.
Độ phủ profile vẫn50,36–70,49% tùy nhóm giờ, chưa nhóm nào đạt80%.

---
# PortoFlow — bản xem thử cục bộ 2026-10-27

Đã ghép runs/preview_20261027 từ ZIP review đã kiểm và graph cục bộ trùng SHA.
274.320 profile giữ nguyên; traffic.geojson dựng lại khớp SHA từng byte với
candidate Kaggle. Manifest riêng ghi preview_only và chờ QC/holdout review;
không thay export đang dùng. verify_checkpoint đạt cho toàn bộ file preview.
Chưa khởi động server hay trình duyệt; người dùng yêu cầu tự chạy PowerShell.

Lệnh: .\.venv\Scripts\python.exe scripts\launch_app.py --export runs\preview_20261027

---
# PortoFlow — kết quả Kaggle thật đã nhận 2026-10-26

Đã nhận notebooks/portoflow_final_review.zip. Report hoàn tất (REPORT_CONTINUE_COMPLETE).
Kiểm CRC/hash các file có trong gói, graph/core identity và code revisions; đếm
lại 274.320 profile cho22.860 cạnh×12 nhóm giờ, support/nhãn/ngưỡng và clipped-length
coverage khớp báo cáo. Độ phủ từng nhóm từ50,36% đến70,49%; chưa nhóm nào đạt80%.

Train matching1.343.398/1.343.398 parent đã xử lý hết; holdout75.322/303.479,
còn228.157. Matching_complete=False là do holdout. Không đưa holdout vào profiles.
ETA báo cáo trên148.312 component: MAE56,93→51,22s, RMSE84,84→76,48s;
CSV component không có trong reviewZIP nên chưa tính lại ETA độc lập.

Candidate vẫn chờ QC/holdout review. Gói nhỏ không đủ raw/checkpoint/manual
review cases để nghiệm thu mọi support/speed hay provenance; app chưa được thay.
Giữ toàn bộ Output trên Kaggle. Chi tiết [báo cáo](reports/real_run_20261026/REPORT.md)
và [biên nhận](reports/real_run_20261026/verification.json).

---

# PortoFlow — tiếp tục ledger sau lỗi dung lượng 2026-10-26

Log thật người dùng gửi: Report_Recovery nhập 70.936/70.936 batch, tạo hai chỉ
mục rồi chạm cap Output12GiB ở đầu profiles. Save Version giữ Output recovery.
Log ghi train1.343.398/holdout75.322 parent; matching_complete=False. Các số này
chưa được đối chiếu độc lập với archive thật.

Notebook mới `PortoFlow_Report_Continue.ipynb`, code
`portoflow_report_continue.zip`: dùng ledger đã seal ở chế độ chỉ đọc; không
import batch/tạo index/matching. Kiểm kích thước và dung lượng trống trước;
nếu ZIP chỉ stage ledger sang /tmp có cap24GiB, Output mới cap2GiB. Cần Input
matching ban đầu và Input recovery vừa lỗi. Cache mới nhỏ, tiếp tục được.

19 file scientific và script recoveryV1 giữ nguyên byte để tương thích seal.
36 kiểm thử đạt; ZIP giải nén đạt7 kiểm tra riêng. Đã đối chiếu profile/coverage/ETA,
immutable ledger, checkpoint giả hỏng, storage fast-fail và source/bootstrap ZIP.
Chưa chạy mã tiếp tục trên archive thật; candidate/app chưa được thay thế.

[Hướng dẫn mới](docs/REPORT_CONTINUE.md) ·
[Biên nhận kiểm thử](docs/report_continue_validation.json).

---

# PortoFlow — report recovery2026-10-26

Người dùng báo lượt Kaggle đã chạy matching khoảng6giờ, rồi report timeout sau
1.800s khi đọc batch. Screenshot có Output `_output_.zip`5,48GB. Chưa có archive
thật trên máy để xác minh số parent hoặc kết luận matching đã hết toàn nguồn.

Đã sửa đường gọi report để dùng ledger/chunk profile/batch holdout có checkpoint,
không xóa và replay lại toàn bộ tiến độ sau mỗi lần dừng. Có notebook riêng
`PortoFlow_Report_Recovery.ipynb` và ZIP `portoflow_report_recovery.zip` để đọc
Output đã lưu, chỉ hậu xử lý. Bản đầy đủ cho các lượt sau cũng gọi report mới.

**26 kiểm thử đạt**; ZIP recovery giải nén đạt2kiểm tra report-only riêng.
**19 file scientific package giữ nguyên từng byte so với bản đã giao**;
original_delivery_20261025 được giữ để audit. Không thay SRC matching, graph,
checkpoint cũ hoặc tự cập nhật app. Công thức aggregation/profiles/ETA đã đối
chiếu với bản gốc trên fixture tổng hợp. Chưa chạy recovery trên Output5,48GB thật.

[Cách chạy recovery](docs/REPORT_RECOVERY.md) ·
[Biên nhận kiểm thử](docs/report_recovery_validation.json).

Bước tiếp theo: người dùng chạy notebook recovery với code Dataset mới và đúng
SavedOutput phiên lỗi; gửi portoflow_recovered_review.zip, giữ toàn bộ Output mới.
Matching_complete được công bố riêng; report xong không là bằng chứng toàn bộ
matching hoặc nghiệm thu khoa học đã hoàn tất.

---

# PortoFlow — tiến độ 2026-10-25

Project độc lập tại `C:/Users/ADMIN/Documents/CS313/PortoFlow`, package `portoflow`.

- Graph OSM thật: **22.860 cạnh core /26.254 cạnh gồm đệm500m**, đúng100km².
- Đã có pipeline graph → EOF scan → whole-parent split → native block matching
  → core-clipped observations → train-only profiles → holdout ETA → candidate export.
- Đã có app riêng và routing A→B; trước khi có export hiển thị graph preview.
- **13 kiểm thử đạt**, gồm native synthetic end-to-end, resume, leakage, clipping,
  app và nội dung/bootstrap notebook/ZIP.
- ZIP giải nén đã chạy native end-to-end tổng hợp riêng: **1passed/8deselected**;
  package được import từ chính ZIP giải nén, không dùng source ở folder khác.
- Notebook riêng: `notebooks/PortoFlow_Kaggle.ipynb`.
- Code Dataset riêng: `deliverables/portoflow_kaggle.zip`, có graph đã kiểm SHA.

**Chưa chạy matching toàn dữ liệu Porto thật hoặc nghiệm thu tốc độ/ETA trên
vùng mới. Chưa chạy notebook trên Kaggle.** Các kiểm thử pipeline đều ghi rõ
SYNTHETIC; graph thật không đồng nghĩa có kết quả giao thông thật.

Bước tiếp theo: chạy Kaggle với code ZIP và raw Porto; giữ Output/checkpoints,
gửi portoflow_review.zip để kiểm QC, độ phủ, holdout và hiệu năng app.

Người dùng tự tạo repo GitHub và gửi URL sau. Chưa tạo/push repo. Chỉ cập nhật
GitHub sau mốc hoàn thành/khi cần; không có lịch hằng ngày hoặc automation.

Chi tiết kiểm chứng: [validation.json](docs/validation.json).

