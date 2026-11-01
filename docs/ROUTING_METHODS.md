# Công thức và cách xây dựng bốn phương án định tuyến

Ngày đối chiếu: **01/11/2026**. Tài liệu mô tả đúng cách chọn đường ở bản
**74d851f**; không đổi thuật toán, trọng số hoặc dữ liệu trong lần cập nhật
tài liệu này. Dùng để tra cứu và chuẩn bị trình bày demo PortoFlow.

## 1. ETA là gì?

ETA viết tắt của **Estimated Time of Arrival**, nghĩa là thời điểm đến dự kiến.
Trong giao diện hiện tại, “ETA ước lượng: 3 phút” biểu thị **thời gian di chuyển
dự kiến từ A đến B**. Nếu xuất phát lúc 08:00, tương ứng dự kiến đến lúc 08:03.

Đây là ước lượng từ tốc độ taxi lịch sử theo nhóm ngày và khung giờ Lisbon,
không phải thời gian đo trên chuyến đi hiện tại hay giao thông trực tiếp.

## 2. Các đại lượng dùng chung

Xem mạng đường là đồ thị có hướng $G=(V,E)$:

- $V$: các nút nối đường; thêm nút ảo A/B khi tính tuyến.
- $E$: các đoạn đường theo chiều xe chạy.
- $P$: một đường đi hợp lệ từ A đến B.
- $L_e$: số mét thực sự đi qua trên cạnh $e$; có thể chỉ là phần đầu/cuối cạnh.
- $g$: tổ hợp nhóm ngày và khung giờ, ví dụ weekday + 09–12.
- $\widehat v_{e,g}$: tốc độ dùng tính ETA ở khung $g$, đơn vị km/h.
- $\widehat v^s_e$: tốc độ tĩnh dùng làm mốc, đơn vị km/h.

Thời gian trên từng cạnh:

$$
t_{e,g}=\frac{3.6L_e}{\widehat v_{e,g}}\quad\text{giây}
$$

Hệ số 3,6 đổi km/h sang m/s. Tổng chiều dài và ETA của tuyến:

$$
D(P)=\sum_{e\in P}L_e,\qquad
T_g(P)=\sum_{e\in P}t_{e,g}
$$

Nếu đi qua cùng một cạnh nhiều lần, mỗi lượt đều được cộng. Không lấy trung
bình cộng tốc độ các cạnh rồi chia tổng quãng đường.

Ví dụ minh họa, không phải quan sát Porto thật:

| Cạnh | Đi qua | Tốc độ | Thời gian |
|---|---:|---:|---:|
| e1 | 500 m | 30 km/h | 3,6 × 500 / 30 = 60 giây |
| e2 | 500 m | 15 km/h | 3,6 × 500 / 15 = 120 giây |
| Cả tuyến | 1.000 m | | 180 giây = 3 phút |

Tốc độ hiệu dụng của cả tuyến này là 20 km/h, không phải (30+15)/2 = 22,5 km/h.

### 2.1. Tốc độ lịch sử được xây dựng thế nào?

Sau matching/QC, với một chuyến $j$ đi qua cạnh $e$, dữ liệu được gộp thành
quãng đường $d_{j,e}$ và thời gian $\tau_{j,e}$. Tốc độ theo chuyến:

$$
v_{j,e}=3.6\frac{d_{j,e}}{\tau_{j,e}}
$$

- **Tốc độ tĩnh** $v^s_e$: trung vị tốc độ theo chuyến trên cạnh đó trong toàn
  tập train hợp lệ, gộp các nhóm ngày/giờ.
- **Tốc độ theo khung** $v_{e,g}$: trung vị tốc độ theo chuyến sau khi giới hạn
  vào tổ hợp nhóm ngày/giờ $g$. Quãng đường và thời gian được gộp trong chính
  tổ hợp đó trước khi tính tốc độ theo chuyến.

Trung vị là giá trị giữa của dãy đã sắp xếp; nếu số phần tử chẵn, lấy trung
bình hai giá trị giữa. Không lấy trung bình cộng toàn bộ các tốc độ.
Điều kiện hỗ trợ của bản demo thật là ít nhất 3 chuyến, 2 taxi, 2 ngày độc lập.
Profile theo khung phải được phân loại khác unknown thì bộ định tuyến mới dùng
median của khung. Nhãn còn phụ thuộc mức tham chiếu hợp lệ; chỉ có một giá trị
median trong bảng chưa đủ để coi khung đó đáng tin cậy.

Chỉ dùng dữ liệu train trước cutoff **2014-05-01 UTC**, tách train/holdout
theo nguyên chuyến; holdout không được đưa vào profile.

### 2.2. Thiếu dữ liệu thì dùng tốc độ gì?

Tốc độ tĩnh có dự phòng:

$$
\widehat v^s_e=
\begin{cases}
v^s_e & \text{nếu có tốc độ tĩnh hợp lệ}\\
v^{map}_e & \text{nếu đọc được maxspeed trên bản đồ}\\
25 & \text{nếu không có cả hai nguồn trên}
\end{cases}
$$

$v^{map}_e$ chỉ là proxy từ thuộc tính bản đồ, không phải tốc độ đã đo.

Tốc độ để tính ETA theo khung:

$$
\widehat v_{e,g}=
\begin{cases}
v_{e,g} & \text{nếu profile khung được phân loại và có tốc độ hợp lệ}\\
\widehat v^s_e & \text{nếu phải dùng dự phòng}
\end{cases}
$$

Đặt $u_{e,g}=0$ khi dùng được tốc độ khung; $u_{e,g}=1$ khi phải dùng dự phòng
vì thiếu thông tin khung. Có tốc độ tĩnh dự phòng vẫn không làm một cạnh unknown
trở thành cạnh đã phân loại trong khung đang xem.

Tổng phần ETA nằm trên các cạnh dùng dự phòng:

$$
T_u(P)=\sum_{e\in P}u_{e,g}t_{e,g}
$$

Chi phí thời gian có xét thiếu dữ liệu:

$$
T_{\mathrm{risk}}(P)=T_g(P)+(m-1)T_u(P),\qquad m=2
$$

Thời gian trên phần có dữ liệu được tính bình thường, phần dùng dự phòng được
nhân 2 **khi chọn đường**. Đây là hệ số chính sách hiện có, chưa phải mô hình
bất định được hiệu chỉnh hay kết luận thời gian thực sẽ gấp đôi.

## 3. Phương án 1 — Mốc so sánh: ngắn nhất

Mục tiêu:

$$
P_D=\underset{P:A\to B}{\arg\min}\ D(P)
$$

Trọng số đưa vào Dijkstra cho mỗi cạnh:

$$
w_D(e)=L_e
$$

Tốc độ, màu chậm và phần thiếu dữ liệu không ảnh hưởng đến việc chọn tuyến này.
Sau khi chọn xong, app vẫn tính ETA bằng tốc độ theo khung để so sánh với các
phương án khác.

Vai trò: mốc cho biết có thể đi ít mét nhất là bao nhiêu trên mạng đường hiện có.
Không khẳng định tuyến ít mét nhất sẽ mất ít thời gian nhất.

## 4. Phương án 2 — Mốc so sánh: tốc độ tĩnh

Thời gian tính bằng tốc độ tĩnh:

$$
T_s(P)=\sum_{e\in P}\frac{3.6L_e}{\widehat v^s_e}
$$

Mục tiêu và trọng số:

$$
P_S=\underset{P:A\to B}{\arg\min}\ T_s(P),\qquad
w_S(e)=\frac{3.6L_e}{\widehat v^s_e}
$$

Mỗi cạnh có tốc độ tĩnh riêng. Không dùng tốc độ riêng của giờ đang chọn để
chọn tuyến này và không nhân phạt unknown trong hàm mục tiêu tĩnh.

Vai trò: mốc định tuyến dùng lịch sử gộp, giúp đánh giá tác động của việc phân
biệt giờ/ngày. “Tĩnh” mô tả mô hình tốc độ, không phải xe đứng yên.

## 5. Phương án 3 — Ưu tiên ETA theo giờ, có xét độ phủ

Mục tiêu:

$$
P_H=\underset{P:A\to B}{\arg\min}\ T_{\mathrm{risk}}(P)
$$

Trọng số:

$$
w_H(e)=\left[1+(m-1)u_{e,g}\right]\frac{3.6L_e}{\widehat v_{e,g}},
\qquad m=2
$$

Nếu mọi đoạn đủ dữ liệu, mục tiêu trở thành tối thiểu tổng ETA lịch sử theo
khung đang chọn. Nếu có phần thiếu dữ liệu, tuyến có ETA hiển thị thấp nhất
chưa chắc được chọn vì phần đó chịu khoản phạt khi tối ưu.

Không có thành phần phạt quãng đường riêng trong phương án này; chiều dài đã
tham gia tính thời gian qua $L_e/v_e$. Nó có thể đi xa hơn để giảm chi phí thời gian.

## 6. Phương án 4 — Đề xuất cân bằng thời gian–quãng đường

### 6.1. Xác định mốc chuẩn hóa cho chính A/B đang chọn

Từ tuyến ngắn nhất $P_D$, lấy:

$$
D_0=D(P_D),\qquad T_0=T_g(P_D)
$$

$T_0$ là ETA theo khung của tuyến ngắn nhất, **chưa cộng phạt thiếu dữ liệu**.
Không dùng ETA của tuyến nhanh nhất hoặc ETA tĩnh làm mẫu số. A/B trùng vị trí
không tạo hành trình hợp lệ; app báo chọn hai điểm cách nhau.

Nếu chính tuyến ngắn nhất có phần thiếu dữ liệu, điểm $J(P_D)$ có thể lớn hơn
1 vì tử số có phạt còn $T_0$ không có phạt. Ví dụ ở mục 7 không có unknown nên
điểm mốc bằng 1.

### 6.2. Hàm mục tiêu

$$
J(P)=
\alpha\frac{T_{\mathrm{risk}}(P)}{T_0}
+(1-\alpha)\frac{D(P)}{D_0}
$$

$$
P_B=\underset{P:A\to B}{\arg\min}\ J(P)
$$

Mặc định $\alpha=0.8$:

$$
J(P)=0.8\frac{T_g(P)+T_u(P)}{T_0}
+0.2\frac{D(P)}{D_0}
$$

Giải thích từng phần:

1. $T_{\mathrm{risk}}/T_0$: chi phí thời gian tương đối so với mốc.
2. $D/D_0$: quãng đường tương đối so với đường ngắn nhất.
3. Chuẩn hóa đưa hai thành phần về không đơn vị trước khi kết hợp.
4. $\alpha$ quyết định đánh đổi. Tăng $\alpha$ làm thời gian được ưu tiên hơn.

80/20 là trọng số ưu tiên sản phẩm, chưa được hiệu chỉnh bằng nghiên cứu người
dùng. Không phải độ chính xác 80%, không phải giới hạn đi vòng 20%, không phải
đi ngẫu nhiên 80% thời gian/20% quãng đường.

### 6.3. Trọng số thực sự đưa vào Dijkstra

$$
w_B(e)=
\alpha\frac{[1+(m-1)u_{e,g}]\,3.6L_e/\widehat v_{e,g}}{T_0}
+(1-\alpha)\frac{L_e}{D_0}
$$

Vì $D_0,T_0$ cố định sau khi tìm tuyến ngắn nhất, tổng các $w_B(e)$ đúng bằng
$J(P)$. Các trọng số không âm. Do đó Dijkstra tìm trực tiếp tuyến có $J$ nhỏ
nhất trên toàn đồ thị, có thể là tuyến khác cả ba mốc.

App không chỉ chấm điểm ba tuyến có sẵn rồi chọn một trong ba.

### 6.4. Diễn giải thành “đi thêm 1 km cần giảm bao nhiêu thời gian?”

Với $\alpha>0$, nhân $J$ với hằng số dương $T_0/\alpha$ không đổi thứ tự:

$$
\underset P{\arg\min}\ J(P)=
\underset P{\arg\min}\left[T_{\mathrm{risk}}(P)+\lambda D(P)\right]
$$

$$
\lambda=\frac{1-\alpha}{\alpha}\frac{T_0}{D_0}
$$

Nếu $T_0$ tính bằng phút và $D_0,D(P)$ bằng km, $\lambda$ có đơn vị phút/km.

Ví dụ $D_0=5$ km, $T_0=10$ phút, $\alpha=0.8$:

$$
\lambda=\frac{0.2}{0.8}\frac{10}{5}=0.5\ \text{phút/km}
$$

Trong chính ví dụ này, thêm 1 km cần giảm **hơn 30 giây chi phí thời gian**
để có điểm tốt hơn. Khi mọi đoạn đủ dữ liệu, đó cũng là hơn 30 giây ETA.
Nếu mức giảm đúng 30 giây, hai phương án có cùng điểm.

Đây là phép biến đổi đại số của công thức đang chạy, không phải chính sách mới.
$\lambda$ thay đổi theo A/B và $\alpha$, chưa phải mức đánh đổi cố định cho mọi
hành trình. Khi $\alpha=0$, app tối ưu chiều dài; khi $\alpha=1$, mục tiêu khớp
phương án ưu tiên ETA có xét thiếu dữ liệu. Các tuyến đồng điểm có thể khác nhau.

## 7. Ví dụ tính đủ cả bốn phương án

**Dữ liệu minh họa tổng hợp, không phải kết quả đo trên Porto.** Giả sử có bốn
hành lang từ cùng A đến cùng B, không nối chéo để tạo đường lai. Thời gian trong
bảng đã được cộng từ từng đoạn. Mọi đoạn đều đủ dữ liệu, do đó $T_u=0$.

| Hành lang | D (km) | ETA theo khung T (phút) | Thời gian tĩnh Ts (phút) |
|---|---:|---:|---:|
| R0 | 5.0 | 10.0 | 10.0 |
| R1 | 5.4 | 9.8 | 7.0 |
| R2 | 6.0 | 9.0 | 8.0 |
| R3 | 5.1 | 9.4 | 7.5 |

### Bước 1: chọn tuyến ngắn nhất

So sánh 5.0, 5.4, 6.0 và 5.1 km → **R0**.
Suy ra $D_0=5$ km, $T_0=10$ phút.

### Bước 2: chọn theo tốc độ tĩnh

So sánh 10.0, 7.0, 8.0 và 7.5 phút tĩnh → **R1**.

### Bước 3: chọn ưu tiên ETA theo giờ

Không có unknown, nên so sánh 10.0, 9.8, 9.0 và 9.4 phút → **R2**.

### Bước 4: tính điểm cân bằng với alpha = 0.8

| Hành lang | Thành phần thời gian | Thành phần quãng đường | Tổng J |
|---|---:|---:|---:|
| R0 | 0.8 × 10.0/10 = 0.800 | 0.2 × 5.0/5 = 0.200 | 1.000 |
| R1 | 0.8 × 9.8/10 = 0.784 | 0.2 × 5.4/5 = 0.216 | 1.000 |
| R2 | 0.8 × 9.0/10 = 0.720 | 0.2 × 6.0/5 = 0.240 | 0.960 |
| R3 | 0.8 × 9.4/10 = 0.752 | 0.2 × 5.1/5 = 0.204 | **0.956** |

**R3 có điểm thấp nhất**, nên được đề xuất cân bằng.

- So với ngắn nhất R0: thêm 100 m, ETA giảm 36 giây.
- So với ưu tiên ETA R2: chấp nhận ETA lâu hơn 24 giây để đi ít hơn 900 m.
- Với $\lambda=30$ giây/km, thêm 900 m cần giảm hơn 27 giây chi phí thời gian.
  R2 chỉ giảm 24 giây so với R3, nên chưa đủ để được phương án cân bằng ưu tiên.

Kết quả bốn tiêu chí:

| Tiêu chí | Tuyến chọn | ETA app hiển thị |
|---|---|---:|
| Ngắn nhất | R0 | 10.0 phút |
| Tốc độ tĩnh | R1 | 9.8 phút |
| ETA theo giờ, có độ phủ | R2 | 9.0 phút |
| Cân bằng | R3 | 9.4 phút |

R1 được chọn bằng thời gian tĩnh 7 phút nhưng hiển thị ETA theo khung 9,8 phút.
Đó là chủ ý dùng chung mô hình khi so sánh, không phải nhầm lẫn hai loại tốc độ.
Chênh lệch điểm nhỏ trong ví dụ là kết quả công thức, không chứng minh khác biệt
có ý nghĩa thống kê hoặc độ chính xác ETA thực tế.

## 8. Ví dụ riêng về thiếu dữ liệu

**Một tình huống tổng hợp khác**, chỉ có hai tuyến:

- K: 5 km, ETA 10 phút, không có phần thiếu dữ liệu.
- U: 5.2 km, ETA dự phòng 8 phút; 4 trong 8 phút thuộc đoạn chưa xác định.

K là tuyến ngắn nhất, nên $D_0=5$ km, $T_0=10$ phút.

$$
T_{\mathrm{risk}}(K)=10,\qquad
T_{\mathrm{risk}}(U)=8+(2-1)\times4=12\ \text{phút}
$$

$$
J(K)=0.8\times10/10+0.2\times5/5=1
$$

$$
J(U)=0.8\times12/10+0.2\times5.2/5=1.168
$$

Phương án theo giờ và cân bằng đều chọn K. Nếu bỏ khoản phạt, điểm cân bằng U
sẽ là 0.848 và nó được chọn. Ví dụ cho thấy thiếu dữ liệu có thể đổi quyết định.

Nếu người dùng xem U, ETA vẫn hiện **8 phút**, không phải 12 phút. Tỷ lệ thiếu
dữ liệu trên giao diện tính theo **quãng đường**, không phải $T_u/T$:

$$
q_D(P)=\frac{\sum_{e\in P}u_{e,g}L_e}{D(P)}\times100\%
$$

Chỉ biết 4/8 phút dùng dự phòng chưa đủ để suy ra phần trăm quãng đường unknown.

## 9. Các bước xây dựng tuyến trong mã

1. Đọc graph, profile và cấu hình đã lưu; kiểm graph/profile cùng phiên bản.
2. Chiếu A/B lên hình học đường gần nhất trong hệ tọa độ mét. Dùng STRtree để
   tra cứu; giới hạn khoảng cách 300 m. Các chiều trùng hình học được xét riêng.
3. Thêm nguồn/đích ảo; nối phần cạnh từ A về phía trước và phần cạnh đi đến B.
   Cắt đúng chiều dài đầu/cuối, giữ chiều xe chạy. Nếu cùng cạnh và đi xuôi,
   có thể nối trực tiếp phần giữa A/B.
4. Tính tuyến distance trước, lấy $D_0,T_0$. Sau đó tính static, bucket và
   balanced với trọng số ở các mục trên. Thứ tự menu không phải thứ tự thực thi.
5. Với nhiều cạnh có cùng cặp nút có hướng, giữ cạnh có chi phí nhỏ nhất cho
   tiêu chí đang xét; khi hòa chi phí dùng khóa cạnh/vị trí để xử lý nhất quán.
6. Gọi NetworkX weighted shortest_path; trường hợp nguồn/đích cụ thể và trọng
   số này dùng **Dijkstra hai chiều**. Tìm từ phía B trên đồ thị đảo không cho
   phép xe đi ngược chiều ngoài graph. Không có đường hợp lệ thì báo không có tuyến.
7. Khôi phục các đoạn, tính hình học, tổng quãng đường và ETA; gửi lớp tuyến
   nhỏ sang bản đồ. Khoảng nối từ điểm click ngoài đường tới vị trí chiếu không
   được tính vào ETA hoặc quãng đường ô tô.

Chuẩn bị graph/lookup/STRtree từ đầu chỉ giúp giảm trễ, không đổi các công thức.

### Vì sao Dijkstra dùng được?

Với graph và profile đang xét, chiều dài, tốc độ và các hệ số đều cho trọng số
không âm. Chi phí cả tuyến là tổng chi phí các cạnh. Balanced cũng có tính cộng
được vì $D_0,T_0,\alpha,m$ cố định trong một lần tính.

“Tối ưu” ở đây nghĩa là đạt tổng chi phí nhỏ nhất theo đúng tiêu chí trên đồ
thị đang có. Không khẳng định nhanh nhất ngoài đường thực.

## 10. Màu, ETA và các giới hạn cần nói khi trình bày

- Tốc độ lịch sử đi trực tiếp vào thời gian $L/v$. Không cộng phạt riêng chỉ vì
  màu đỏ hoặc vàng; hiện không có luật bắt buộc tránh mọi đoạn đỏ.
- Màu dựa trên mức giảm tốc so với tham chiếu. Đỏ không đồng nghĩa đóng đường
  hay xe chắc chắn đứng yên. Tham chiếu P85 cao bất thường đã được ghi nhận,
  cần QC thêm trước nghiệm thu; màu không tự chứng minh kẹt xe thật.
- Mọi tuyến đều được **hiển thị ETA bằng cùng mô hình khung giờ**, chưa cộng
  phạt unknown. Riêng cách chọn static dùng $T_s$, không dùng ETA hiển thị.
- Giữ khung giờ khởi hành cho toàn tuyến; chưa cập nhật vận tốc theo thời điểm
  xe đến từng cạnh. Chưa có mô hình chờ rồi đi, đèn đỏ hay chi phí rẽ; chưa mô
  hình hóa đầy đủ turn restrictions/chi phí quay đầu.
- Các tiêu chí có thể cùng chọn một tuyến. Nhãn phương án mô tả mục tiêu, không
  bảo đảm có bốn đường khác nhau. Không cố tạo tuyến khác chỉ để khác.
- ETA giảm là chênh lệch mô hình lịch sử, chưa phải thời gian tiết kiệm đo ngoài
  thực tế. Candidate còn chờ QC/holdout; không gọi 80/20 là độ chính xác.

## 11. Nói ngắn gọn khi demo

> Ứng dụng biểu diễn đường phố thành đồ thị có hướng và dùng Dijkstra hai chiều.
> Bốn lựa chọn khác nhau ở trọng số cạnh: chiều dài, thời gian từ tốc độ tĩnh,
> thời gian theo khung có xét thiếu dữ liệu, hoặc tổng chuẩn hóa thời gian và
> quãng đường. Tuyến cân bằng mặc định ưu tiên thời gian 80%, quãng đường 20%.
> Tốc độ lấy từ taxi lịch sử nên ETA là ước lượng, chưa phải giao thông trực tiếp.

Nếu được hỏi “đi vòng có đáng không?”, dùng ví dụ mục 7: **chấp nhận thêm
24 giây so với tuyến ETA thấp nhất để bớt 900 m**, theo trọng số minh họa.

## 12. Đối chiếu mã và tài liệu

| Nội dung | Nơi triển khai |
|---|---|
| Chọn tốc độ khung/tĩnh và thứ tự dự phòng | [edge_speed](../src/portoflow/route.py) |
| Gộp tốc độ theo chuyến, median, support | [profiles.py](../src/portoflow/profiles.py) |
| Trọng số bốn phương án | [_cost trong journey_routing.py](../app/journey_routing.py) |
| Chiếu A/B, graph ảo, Dijkstra, chuẩn hóa và chấm điểm | [recommend_coordinate_routes](../app/journey_routing.py) |
| Hệ số unknown 2 và tốc độ dự phòng 25 | [Cấu hình mặc định](../configs/default.yaml) |
| Mức ưu tiên mặc định và điều chỉnh | [journey_view.py](../app/journey_view.py) |
| Kiểm thử chính sách cân bằng | [test_balanced_routes.py](../tests/test_balanced_routes.py) |
| Kiểm thử đầu/cuối, chiều và màu | [test_journey_endpoints.py](../tests/test_journey_endpoints.py) |
| Tính ETA từng đoạn khớp tổng | [test_route_speed_details.py](../tests/test_route_speed_details.py) |

Các ví dụ số ở mục 2, 7 và 8 là minh họa tổng hợp có phép tính kiểm lại, không
được dùng như bằng chứng hiệu quả trên dữ liệu thật. [Bản tóm tắt chính sách
cân bằng](BALANCED_ROUTING.md) và [hướng dẫn chạy app](../README.md).
