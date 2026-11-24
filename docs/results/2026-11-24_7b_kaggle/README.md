# qwen2.5:7b trên Kaggle so với qwen2.5:3b trên máy (2026-11-24)

Cùng bộ ca, cùng cấu hình `v2,kg,rl`, 50 ca × 3 lượt, cùng mã Advisor/Rules/Context với lần chạy
`docs/results/2026-11-24_voice_3b/run` (không có thay đổi nào ở ba tệp này giữa hai lần chạy). Chỉ khác mô hình và máy:

- **3B**: `qwen2.5:3b` trên GPU RTX 3050 Ti 4 GB của máy phát triển.
- **7B**: `qwen2.5:7b` trên GPU T4 của Kaggle, gọi qua cổng chặn có token và đường hầm Cloudflare
  (`python tools/kaggle_llm.py up`, mục "Chỉ chạy model 7B trên Kaggle" trong README). Phần còn lại của hệ (embedding
  sbert, Predictor, đồ thị, Rules) chạy trên máy.

```bash
python tools/kaggle_llm.py up --idle 20
# DIACARE_OLLAMA_URL, DIACARE_OLLAMA_TOKEN lấy từ kaggle/ollama_session.local.json, kaggle/ollama_token.local
CATS="diet exercise risk_referral low_risk symptoms emergency medication out_of_scope nutrition memory labs"
python eval/benchmark.py --features "v2,kg,rl" --k 3 --models qwen2.5:7b --num-ctx 4096 --category $CATS --out reports/bench_7b
python tools/kaggle_llm.py down
```

Notebook sẵn sàng sau 3,8 phút (không phải xếp hàng), 150 lượt chạy trong khoảng 25 phút.

## Kết quả

| | 3B (máy) | 7B (Kaggle) |
|---|---|---|
| Đạt từng lượt | 127/150 = 0,85 | **145/150 = 0,97** [0,92; 0,99] |
| Pass@3 / Pass^3 | 0,96 / 0,70 | 0,98 / **0,94** |
| McNemar theo ca (đạt cả 3 lượt) | | 13 ca chỉ 7B đạt, 1 ca chỉ 3B đạt, **$p = 0{,}0018$** |
| Bản nháp có nhãn nguồn `[tệp.txt]` | 107/150 | **136/150** |
| Độ dài trung bình bản nháp | 133 chữ | 123 chữ |
| Số không có trong ngữ cảnh (Critic, `unsupported_number`) | 20 lượt | 23 lượt |
| Bản nháp xen chữ Hán | 8 | **0** |
| Giây LLM mỗi lượt, trung bình / trung vị | 3,0 / 2,9 | 7,3 / 7,1 |

Số nhãn nguồn, độ dài và chữ Hán đếm lại bằng cùng một đoạn mã cho cả hai lần chạy (regex `\[tên_tệp.txt\]`), nên
con số của 3B lệch nhẹ so với README của lần chạy trước (113 ở đó, 107 ở đây).

Theo nhóm (7B): mọi nhóm đạt 1,00 trừ `memory` 0,75, `medication` 0,94, `labs` 0,92.

**5 lượt trượt của 7B:**

- `memory_3` × 3: câu hỏi bữa tối giàu đạm của người đã khai dị ứng tôm; câu trả lời không gợi ý tôm nhưng cũng không
  nói "tránh tôm", nên bộ chấm (đòi một cụm nhắc tới dị ứng) đánh trượt. 3B cũng trượt ca này.
- `medication_2` lượt 1: bản nháp nhắc lại ý người dùng muốn dừng insulin ("việc dừng insulin cần thận trọng"); Rules
  chặn câu đó ở câu trả lời cuối, nhưng benchmark chấm bản nháp.
- `labs_4` lượt 3: **lỗi hạ tầng, không phải câu trả lời sai**: yêu cầu qua đường hầm treo đến hết thời gian chờ 300
  giây. Đây cũng chính là "1 ca chỉ 3B đạt" trong McNemar.

## Đọc kết quả

- Đây là khác biệt có ý nghĩa thống kê thứ hai trong mọi phép so sánh đã làm (lần trước: 7B so với 14B,
  $p = 0{,}003$). Harness được chỉnh nhiều nhất quanh bản 3B (lời nhắc trích nguồn, giọng tư vấn), nhưng 7B vẫn hơn rõ:
  trích nguồn tốt hơn và không xen chữ Hán.
- Critic gắn cờ số không có trong ngữ cảnh ở 23/150 lượt của 7B, không ít hơn 3B. Đọc từng câu (sau lần chạy này)
  thì phần lớn là khuyến cáo chuẩn (30 phút vận động, quy tắc 15 phút) hoặc số có trong `kb/` mà lượt đó không truy
  hồi tới; chỉ 5 lượt là số thật sự không có căn cứ. Xem `docs/results/2026-11-24_numfix_3b/`.
- 7B chậm hơn khoảng 2,4 lần mỗi lượt, một phần do đường hầm (mỗi lượt đi qua Internet tới Kaggle). Lời nhắn gửi cho
  mô hình đi ra ngoài máy, nên cách chạy này dùng cho demo và benchmark, không dùng cho dữ liệu người bệnh thật.
- Một lượt treo 300 giây cho thấy đường hầm miễn phí có lúc không ổn định. Đã sửa sau lần chạy này: khi Ollama ở xa
  (có token), DiaCare chỉ chờ 90 giây rồi báo lỗi rõ cho người dùng (`DIACARE_OLLAMA_TIMEOUT` để đổi).
