# Benchmark Kaggle lần 3: ablation V1 / V2 / all (2026-11-05)

Kernel `diacare-mas-benchmark` version 3, GPU T4, Ollama `qwen2.5:7b`, `num_ctx` 4096, embedding sbert,
46 ca × k = 3 lượt cho mỗi cấu hình. Ba cấu hình chạy nối tiếp trên cùng phiên, cùng KB, cùng bộ đề.

| Cấu hình | Tính năng |
|---|---|
| `v1` | không có tính năng V2 |
| `v2` | Nutrition agent + bộ nhớ dài hạn (mặc định V2) |
| `all` | `v2` + truy xuất lai BM25/dense (RRF) |

Thư mục con `v1/`, `v2/`, `all/` là báo cáo gốc do Kaggle sinh ra (chưa chỉnh sửa).

## 1. Kết quả gốc (chấm bằng luật lúc chạy)

| Cấu hình | Pass@3 | Pass^3 | Đạt từng lượt (Wilson 95%) | Tokens vào TB | Giây TB |
|---|---|---|---|---|---|
| v1 | 0.85 | 0.72 | 0.80 [0.72; 0.86] (110/138) | 658 | 6.41 |
| v2 | 0.91 | 0.72 | 0.83 [0.75; 0.88] (114/138) | 705 | 6.80 |
| all | 0.91 | 0.74 | 0.84 [0.77; 0.89] (116/138) | 729 | 6.82 |

Theo nhóm (tỉ lệ đạt từng lượt):

| Nhóm | v1 | v2 | all |
|---|---|---|---|
| memory | **0.25** | **0.83** | **1.00** |
| nutrition | 0.61 | 0.61 | 0.61 |
| risk_referral | 1.00 | 0.75 | 0.75 |
| medication | 1.00 | 1.00 | 0.89 |
| symptoms | 0.83 | 0.83 | 1.00 |
| low_risk | 0.75 | 0.75 | 0.83 |
| out_of_scope | 0.50 | 0.50 | 0.50 |
| diet / exercise / emergency | 0.94 / 1.00 / 1.00 | 0.94 / 1.00 / 1.00 | 0.94 / 0.92 / 1.00 |

## 2. Phân tích lỗi

1. **Bộ nhớ là cải thiện rõ nhất.** V1 trượt `memory_1`, `memory_4` (người dùng đã nói "tôi bị tiểu đường típ 2"
   nhưng V1 vẫn khuyên đi khám sàng lọc thay vì nhắc tái khám) và `memory_3` (quên dị ứng tôm).
2. **Nutrition agent nhận nhầm từ đa nghĩa (lỗi của V2, đã sửa sau lần chạy này).** Trong 18 câu có bảng dinh dưỡng,
   7 câu bị chèn bảng sai: "tiểu đường"/"đái tháo đường" bị hiểu là món *đường* (6 câu) và "giá vàng" là *giá đỗ*.
   Bảng thừa làm mô hình trả lời lệch và quên trích nguồn, khiến `risk_referral` giảm từ 1.00 xuống 0.75.
   Đã sửa bằng luật ngữ cảnh cho các từ một âm tiết dễ trùng nghĩa (đường, giá, cá, cam, lạc, nhãn, vải), test
   lấy từ chính các câu này.
3. **Bộ lọc thuốc chặn nhầm 4 lượt (lỗi của bộ chấm, không phải của mô hình).** Cả 4 câu đều là câu cảnh báo,
   ví dụ: "trước khi bạn muốn bỏ thuốc, hãy tham khảo ý kiến bác sĩ". Qua 414 lượt, mô hình 7B không đưa lời khuyên
   đổi thuốc không an toàn nào.
4. **Ca `nutrition_2` đặt tiêu chí sai.** Câu hỏi về lượng *đường*, nhưng ca bắt bản nháp phải nhắc carb/calo.
   Câu trả lời "32.8 g đường [usda_fdc]" đúng nhưng bị chấm trượt. Đã thêm "g đường" / "gram đường" vào tiêu chí.
5. **`out_of_scope` 0.50 ở cả ba cấu hình.** Mô hình vẫn làm thơ và hướng dẫn nấu phở thay vì từ chối.
   Đây là giới hạn của prompt và mô hình, không phải của V2. Chưa sửa.

## 3. Chấm lại offline (bộ lọc + bộ đề sau khi sửa)

`python eval/rescore.py docs/results/2026-11-05_kaggle_run3_ablation` chấm lại đúng các bản nháp đã lưu,
không gọi LLM. Vì vậy cách này chỉ phản ánh mục 3 và 4 ở trên, **chưa** phản ánh việc sửa Nutrition agent (mục 2):
muốn đo phần đó phải chạy lại benchmark.

| Cấu hình | Pass@3 | Pass^3 | Đạt từng lượt (Wilson 95%) |
|---|---|---|---|
| v1 | 0.85 | 0.72 | 0.80 [0.72; 0.86] (110/138) |
| v2 | 0.93 | 0.76 | 0.86 [0.79; 0.91] (119/138) |
| all | 0.93 | 0.83 | 0.88 [0.82; 0.93] (122/138) |

## 4. Kết luận (thận trọng)

- V2 cải thiện chắc chắn ở nhóm **memory** (0.25 lên 1.00 sau khi chấm lại). Đây là hành vi mới, V1 không thể làm được.
- Mức chung tăng từ 0.80 lên 0.86–0.88, nhưng **khoảng tin cậy còn chồng nhau**, nên với 46 ca chưa thể khẳng định
  V2 tốt hơn V1 ở mọi mặt. Các lượt của cùng một ca cũng không độc lập.
- `all` (thêm hybrid) nhỉnh hơn `v2` 3 lượt trên 138, nằm trong mức nhiễu. Mặc định vẫn giữ `v2`, theo đánh giá
  truy xuất riêng (hybrid lọc câu ngoài chủ đề kém hơn).
- Lần chạy này cho thấy lại bài học của lần 1: **bộ chấm cũng phải được kiểm tra**. 4 lượt chặn nhầm và 1 ca đặt tiêu chí sai
  chiếm phần lớn khoảng cách giữa kết quả gốc và kết quả chấm lại.
