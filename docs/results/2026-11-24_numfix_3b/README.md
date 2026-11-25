# Số "không có trong ngữ cảnh": phân loại lại và một lời dặn mới (2026-11-24, qwen2.5:3b)

## 1. Phân loại các số Critic gắn cờ

Critic gắn cờ `unsupported_number` ở 20/150 lượt (3B, `docs/results/2026-11-24_voice_3b/run`) và 23/150 lượt (7B,
`docs/results/2026-11-24_7b_kaggle`). Trước đây các báo cáo gọi đó là "số mô hình tự bịa". Đọc từng câu chứa số bị
gắn cờ cho thấy cách gọi đó quá nặng. Các số rơi vào ba nhóm (phân loại bằng tay, theo câu chứa số):

| Nhóm | 3B (lượt) | 7B (lượt) | Ví dụ |
|---|---|---|---|
| (a) có trong kho `kb/` nhưng lượt đó không truy hồi tới | 5 | 3 | 150 phút/tuần (WHO), HbA1c 5,7 %, FPG 126 mg/dL, 130/180 mg/dL, "2 giờ sau ăn" |
| (b) khuyến cáo chuẩn không có trong `kb/` | 11 | 15 | 30 phút vận động mỗi ngày, quy tắc 15 phút khi hạ đường huyết, ngủ 7–9 giờ |
| (c) không có căn cứ, hoặc sai | **4** | **5** | gram/kcal của món (6 g đạm, 150 gram thịt, 106 kcal), "FPG trên 160 mg/dL thì đi khám ngay", 58 % gán nhầm cho WHO, "thường xuyên trên 13 mmol/L" |

Một lượt có số thuộc nhiều nhóm được tính vào nhóm nặng nhất. Số thật sự không có căn cứ là **4/150 (3B) và 5/150
(7B)**, tập trung ở hai chỗ: gram, kcal của món ăn (câu hỏi dinh dưỡng) và ngưỡng chẩn đoán hay tỉ lệ phần trăm.
Nhóm (a) cho thấy Critic chỉ so với các đoạn tài liệu đã truy hồi, không so với cả kho. Nhóm (b) là kiến thức đúng
nhưng hệ thống không có nguồn để trích. Thêm một trang khuyến cáo có nguồn vào `kb/` sẽ đổi ngữ cảnh của mọi ca
benchmark, nên chưa làm.

## 2. Thay đổi

Dặn thêm trong prompt hệ thống của Advisor (`src/diacare/advisor.py`), ngay sau lời dặn về số liệu dinh dưỡng:

> Chỉ nêu gram, kcal hay lượng đạm, tinh bột của món có trong bảng dinh dưỡng; món không có trong bảng thì gợi ý món
> mà không kèm số. Ngưỡng chẩn đoán và tỉ lệ phần trăm chỉ nêu khi có trong tài liệu.

Lời dặn bốn nhịp (`LENGTH_REMINDER`) đã có câu "chỉ dùng con số có trong thông tin ở trên" từ trước; giả thuyết cũ
("lời dặn giải thích bằng con số làm mô hình bịa số") không còn đúng với prompt hiện tại nên không thử.

## 3. Kết quả

Cùng cấu hình `v2,kg,rl`, 50 ca × 3 lượt, qwen2.5:3b trên máy. Chạy thành hai phần: `run_4cat` (4 nhóm hay có số:
diet, nutrition, memory, risk_referral) và `run_rest` (7 nhóm còn lại).

| | Trước (voice_3b) | Sau |
|---|---|---|
| Đạt từng lượt, cả 150 lượt | 127/150 | 124/150 |
| 4 nhóm hay có số | 44/60 | 42/60 |
| 7 nhóm còn lại | 83/90 | 82/90 |
| Lượt có số bị Critic gắn cờ | 20 | 17 |
| trong 4 nhóm hay có số | 8 | 5 |
| Số nhóm (c), 4 nhóm hay có số | 4 | 1 ("30% người mắc là do hút thuốc") |
| Số nhóm (c), 7 nhóm còn lại | 0 | 1 ("hôn mê thường do đường huyết dưới 50 mg/dL") |
| Số nhóm (c), cả 150 lượt | 4 | 2 |
| Ca chỉ đạt ở một bản (đạt cả 3 lượt), 4 nhóm hay có số | 6 | 2 |
| Ca chỉ đạt ở một bản, 7 nhóm còn lại | 3 | 4 |

McNemar theo ca (đạt cả ba lượt): 9 ca chỉ đạt ở bản trước, 6 ca chỉ đạt ở bản sau, $p = 0{,}61$: **không có khác
biệt có ý nghĩa** về tỉ lệ đạt. Các lượt trượt mới chủ yếu là "không trích nguồn" ở nhóm diet: mô hình gợi ý món mà
không kèm số và cũng không gắn nhãn nguồn.

## 4. Đọc kết quả

- Số không có căn cứ giảm ở đúng hai chỗ được nhắm tới (không còn gram/kcal tự đặt cho món), nhưng mẫu quá nhỏ (4 → 2
  lượt trên 150) để khẳng định.
- Cái giá có thể có: ở bốn nhóm hay có số, 6 ca chỉ đạt trước so với 2 ca chỉ đạt sau, phần lớn vì bản nháp nhóm diet
  không còn gắn nhãn nguồn. Cũng chưa đủ mẫu để khẳng định. Lời dặn đang được giữ vì nó nhắm vào lỗi có thể gây hại
  (số sai hiện cho người bệnh), còn lỗi thiếu nhãn nguồn không làm sai nội dung; muốn bỏ thì xoá hai câu thêm vào
  `SYSTEM_PROMPT` trong `src/diacare/advisor.py`.
- Critic vẫn không bắt được số dạng khoảng ("45-60 gram", "100g ngũ cốc" dính liền) và số viết kèm chữ Hán
  ("32.8克"); hai lỗi này có trong bản nháp của lần chạy sau. Critic là cận dưới của số không có căn cứ.
- Câu sai vẫn hiện cho người dùng: Critic chỉ đo và gắn cờ, không sửa câu trả lời. Chặn số nhóm (c) cần hiểu nghĩa
  (ví dụ "15 phút" trong quy tắc hạ đường huyết là lời khuyên đúng và an toàn), nên chưa làm.

## 5. Chấm lại sau khi sửa Critic (2026-11-25): kết luận đảo chiều

Critic được sửa để bắt số dạng khoảng ("45-60 gram"), số dính chữ ("100g") và số kèm chữ Hán ("32.8克"). Chấm lại
bản nháp đã lưu của cả lần chạy trước (`2026-11-24_voice_3b/run`) và lần chạy sau (`run_4cat`, `run_rest`) theo
cùng một cách, với ngữ cảnh dựng lại gần đúng:

    python tools/critic_rescore.py docs/results/2026-11-24_voice_3b/run/results.json \
        docs/results/2026-11-24_numfix_3b/run_4cat/results.json docs/results/2026-11-24_numfix_3b/run_rest/results.json

| | Trước | Sau |
|---|---|---|
| Lượt có số không tìm thấy trong ngữ cảnh dựng lại | 19/150 | 23/150 (13 + 10) |
| Lượt có gram, kcal tự đặt cho món (đọc tay) | 5 | 8 |

Con số 4 → 2 ở mục 3 là do Critic cũ không thấy đúng những dạng số mà mô hình chuyển sang dùng sau lời dặn. Lời dặn
**không** giảm được số tự đặt. Nó vẫn nằm trong `SYSTEM_PROMPT`; chưa quyết định giữ hay bỏ.
