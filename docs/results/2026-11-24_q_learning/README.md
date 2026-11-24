# Agent Q-learning nhắc việc hằng ngày, trên dữ liệu mô phỏng (2026-11-24)

**Mọi số liệu ở đây là trên người bệnh mô phỏng do nhóm tự viết (`src/diacare/coach_sim.py`), không phải người thật.**

Code: `src/diacare/coach.py` (agent), `src/diacare/coach_sim.py` (người bệnh mô phỏng), `tools/make_rl_demo_data.py`
(tạo dữ liệu, huấn luyện, đánh giá). Kết quả đầy đủ: `eval.json`. Chạy lại (cùng hạt giống thì ra đúng như cũ):

```bash
python tools/make_rl_demo_data.py --db   # thêm --db để có data/rl_demo/demo.db cho giao diện
```

## Bài toán

Mỗi sáng agent chọn một lời nhắc (1 trong 6 trọng tâm an toàn của `diacare.rl`) cho người đã chẩn đoán đái tháo đường típ 2.

- Trạng thái (36 ô), tính từ nhật ký đường huyết 3 ngày trước bằng hàm phân loại của `diacare.journal`: đo đều
  (ít / vừa / đều) × kiểm soát (chưa đo / đạt / cao / nguy hiểm) × nhóm lời nhắc hôm qua (không / theo dõi / lối sống).
- Phần thưởng tính từ nhật ký của chính ngày đó: có đo +1, bỏ đo −1, cộng trung bình điểm các số đo (đạt +0,5, cao −0,3,
  rất cao −1, hạ đường huyết −1,5 / −1,9), nhắc lại đúng lời hôm qua −0,3. Bỏ đo luôn tệ hơn mọi kết quả đo, kể cả hạ
  đường huyết, để agent không học cách làm người dễ hạ đường huyết bớt đo.
- Cập nhật Q-learning, $\alpha = 0{,}1$, $\gamma = 0{,}9$, quét lại các ngày đã ghi 200 lượt (học ngoài chính sách).
- An toàn: hôm qua có hạ đường huyết hoặc ≥ 250 mg/dL thì luôn "khám sớm" (mặt nạ). Ngoài mặt nạ, agent không được
  chọn "khám sớm": bản đầu cho phép thì agent học dùng "khám sớm" như cách thúc người bệnh đo, cả khi chỉ số bình thường.

## Dữ liệu giả

30 người bệnh (`data/rl_demo/patients.json`), mỗi người theo dõi 14–28 ngày, kết thúc ngày 23/11/2026: 599 ngày có lời
nhắc, 542 số đo đường huyết (`readings.csv`), 599 bước chuyển (`decisions.csv`: trạng thái, lời nhắc, xác suất chọn,
phần thưởng, trạng thái kế tiếp). Lời nhắc do chính sách sinh dữ liệu chọn: 60% ngẫu nhiên đều trong 5 lời nhắc, 40%
theo luật, có ghi xác suất chọn. Dữ liệu phủ 18/36 trạng thái, 72/216 ô (trạng thái, hành động).

## Kết quả trên 200 người bệnh mô phỏng mới (21 ngày, hạt giống khác)

| Chính sách | Tổng thưởng TB / người [KTC 95%] | Tỉ lệ ngày có đo | Số đo đạt mục tiêu |
|---|---|---|---|
| Q-learning ($\gamma = 0{,}9$) | 1,18 [0,09; 2,28] | 0,58 | 0,33 |
| Bandit ($\gamma = 0$, cùng dữ liệu) | 1,19 [0,08; 2,31] | 0,58 | 0,34 |
| Luật cố định | −0,34 [−1,57; 0,88] | 0,61 | 0,32 |
| Ngẫu nhiên | −2,26 [−3,52; −1,01] | 0,48 | 0,36 |

Chênh tổng thưởng từng người: Q-learning − luật cố định +1,53 [0,39; 2,67]; Q-learning − ngẫu nhiên +3,45 [2,28; 4,61];
**Q-learning − bandit −0,01 [−0,68; 0,65]**.

## Đọc kết quả

- Học từ 30 người bệnh là đủ để hơn luật cố định và chọn ngẫu nhiên trên người bệnh mô phỏng mới.
- **Nhìn xa ($\gamma = 0{,}9$) không hơn nhìn một ngày ($\gamma = 0$).** Thử thêm với 300 người bệnh (6.313 ngày): γ = 0 / 0,5 /
  0,9 cho 4,14 / 4,19 / 3,40, tức là không phải do thiếu dữ liệu. Trong mô phỏng, lời nhắc hôm nay có tác dụng muộn
  qua thói quen ẩn của người bệnh, nhưng trạng thái 3 ngày không thấy được thói quen đó đủ rõ, và lời nhắc lặp lại bị phạt
  ngay hôm sau, nên chính sách tốt nhất gần như là chọn tốt cho từng ngày.
- Một bản trước cho kết quả Q-learning hơn hẳn bandit (+3,4). Đó là vì agent được tự chọn "khám sớm" và học dùng nó như
  mẹo thúc người bệnh đo; đã bỏ, xem phần An toàn.
- Mọi ưu thế ở đây chỉ chứng minh agent học được đúng quy luật nhóm đã cài vào mô phỏng. Muốn biết có giúp người thật hay
  không thì phải thử trên người thật, có bác sĩ theo dõi.

## Trên giao diện

- Tab **Hôm nay**: người đã chẩn đoán thấy một "Lời nhắc hôm nay" do agent chọn, mỗi ngày một lần (bảng `coach_events`).
- Trang **Thống kê** (chế độ nhà phát triển): bảng đánh giá trên, chính sách học được, lịch sử lời nhắc và tổng thưởng
  tích lũy của người bệnh đang chọn.
- Demo với 30 người bệnh: chạy Streamlit với `DIACARE_DB=data/rl_demo/demo.db` (tách khỏi dữ liệu thật).
