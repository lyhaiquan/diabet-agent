# Nhắc trích nguồn trong prompt Advisor (2026-11-22)

Đo lần 16/11 cho thấy với `qwen2.5:3b`, benchmark chủ yếu đo thói quen trích nguồn: 70/79 lượt trượt của cấu hình `v2,kg,rl` là vì bản nháp không có nhãn nguồn nào. Prompt hệ thống có dặn "trích nguồn dạng [tên_file]", nhưng đó là một câu giữa khoảng 15 chỉ dẫn, nằm đầu hội thoại, và dùng tên giả.

Thay đổi (`src/diacare/advisor.py`, `citation_reminder`): thêm một lời nhắc vào tin nhắn người dùng, kèm nhãn nguồn thật của lượt đó (`[medlineplus_...txt]`, `[usda_fdc]` khi có số liệu dinh dưỡng, `[ada_2024]` khi có xét nghiệm). Hệ thống **không tự gắn nguồn**: mọi nhãn được đếm ở đây là do mô hình tự viết.

Đo hai vị trí của lời nhắc, mỗi vị trí một lần chạy, chỉ đổi đúng chỗ đó:

- `after_question/`: lời nhắc nằm sau câu hỏi, cuối tin nhắn. **Bản được giữ lại.**
- `before_question/`: lời nhắc nằm ngay trước câu hỏi, thêm câu "Vẫn giữ mọi quy tắc an toàn ở trên".

Máy cá nhân, Ollama `qwen2.5:3b`, `num_ctx` 4096, Sentence-BERT, kho 14 tài liệu, cấu hình `v2,kg,rl` ($\varepsilon = 0$), cùng 11 nhóm và 50 ca × 3 lượt như lần 16/11. Mốc so sánh là `docs/results/2026-11-16_kg_rl_3b/v2_kg_rl`.

## Kết quả (chấm lại bằng luật hiện tại)

| | Mốc 16/11 | Nhắc trước câu hỏi | **Nhắc sau câu hỏi** |
|---|---|---|---|
| Bản nháp tự trích nguồn hợp lệ (lượt có tài liệu) | 27/141 = 0,19 | 85/141 = 0,60 | **121/141 = 0,86** |
| Câu có nhãn nguồn (Critic) | 4,4% | 6,5% | 7,1% |
| Đạt từng lượt [Wilson 95%] | 71/150 = 0,47 [0,40; 0,55] | 101/150 = 0,67 [0,59; 0,74] | **117/150 = 0,78 [0,71; 0,84]** |
| Pass@3 / Pass^3 | 0,56 / 0,38 | 0,86 / 0,48 | **0,90 / 0,64** |
| Trượt vì không trích nguồn | 70 | 29 | 15 |
| Nhóm `medication` (bản nháp) | 18/18 | 13/18 | 9/18 |
| Nhóm `out_of_scope` | 3/12 | 2/12 | 2/12 |
| Câu trả lời cuối có lời khuyên đổi thuốc | 0 | 0 | 0 |
| Lượt có nhãn nguồn lạ | 1 | 1 | 3 |

McNemar chính xác theo ca (một ca đạt khi đạt cả 3 lượt):

| So sánh | Chỉ A đạt | Chỉ B đạt | p |
|---|---|---|---|
| Mốc so với nhắc sau câu hỏi | 9 | 22 | 0,029 |
| Mốc so với nhắc trước câu hỏi | 8 | 13 | 0,38 |
| Nhắc sau so với nhắc trước câu hỏi | 12 | 4 | 0,077 |

## Đọc kết quả

1. **Lời nhắc sau câu hỏi có tác dụng rõ.** Tỉ lệ bản nháp tự trích nguồn tăng từ 0,19 lên 0,86 và tỉ lệ đạt từng lượt từ 0,47 lên 0,78; khác biệt theo ca có ý nghĩa ở mức 0,05. Các nhóm trước đây trượt gần hết vì thiếu nguồn (`exercise`, `symptoms`, `low_risk`, `nutrition`) giờ đạt phần lớn.
2. **"Có trích nguồn" nghĩa là bản nháp có ít nhất một nhãn đúng**, không phải mọi đoạn đều có nhãn: tính theo câu chỉ 7% câu có nhãn.
3. **Cái giá ở nhóm câu về thuốc.** Bản nháp nhóm `medication` đạt 9/18 (mốc 18/18). Hai nguyên nhân, đọc từ bản nháp:
   - Rules chặn nhầm câu cảnh báo: "thảo luận với bác sĩ về việc bỏ thuốc", "tài liệu không đề cập đến việc bỏ thuốc", "không thể đưa ra quyết định về việc bỏ thuốc". Lỗi này của Rules có từ trước; bản nháp dài hơn và nhắc lại câu hỏi nhiều hơn nên chạm vào nó nhiều hơn.
   - Mô hình chép lại câu hỏi vào bản nháp (có lượt viết nguyên "Câu hỏi: Tôi có thể tự giảm liều metformin..."), và 4 lượt không viết chữ "bác sĩ" (viết "đội ngũ y tế").

   Người dùng không thấy lời khuyên không an toàn: Rules chạy sau cùng, cả 18 câu trả lời cuối của nhóm này đều nhắc bác sĩ, và không câu trả lời cuối nào khuyên đổi thuốc.
4. **Đặt lời nhắc trước câu hỏi** sửa được một phần nhóm thuốc (13/18) nhưng mất phần lớn mức tăng trích nguồn (0,60). Thua bản sau câu hỏi 4 ca so với 12, nên bản sau câu hỏi được giữ.
5. **Câu ngoài chủ đề** vẫn chỉ 2/12; lời nhắc không làm tốt hay xấu đi rõ rệt. Đây là việc cần làm riêng.
6. **Bị cắt ở 512 token:** 27 lượt (nhắc sau) và 5 lượt (nhắc trước). Mốc 16/11 chạy trước khi có cờ `answer_truncated` (commit `db1887b`, cùng ngày), nên không so được với mốc.

## Sửa bộ chấm lại

`rescore_record` (`src/diacare/bench.py`) không biết lượt nào có kết quả xét nghiệm, nên coi nhãn `[ada_2024]` là thiếu trích nguồn. Đã sửa bằng cách dò lại xét nghiệm trong câu hỏi và các lượt dựng lịch sử của ca, như LabAgent làm lúc chạy. Sau khi sửa, chấm lại lần "nhắc sau câu hỏi" ra đúng 117/150 như lúc chạy; lần "nhắc trước câu hỏi" lệch 1 lượt (101 so với 100: một lượt ghi `[usda_fdc]` khi không có số liệu dinh dưỡng, mà bộ chấm lại mặc định coi như có). Số của lần 16/11 chấm lại bằng bộ chấm đã sửa: `v2` 68/150, `v2,kg` 72/150, `v2,kg,rl` 71/150 (trước ghi 69/150).

## Chạy lại

```bash
CATS="diet exercise risk_referral low_risk symptoms emergency medication out_of_scope nutrition memory labs"
python eval/benchmark.py --features "v2,kg,rl" --k 3 --category $CATS --out reports/cite_prompt/v2_kg_rl
python eval/compare.py docs/results/2026-11-16_kg_rl_3b/v2_kg_rl/results.json reports/cite_prompt/v2_kg_rl/results.json --rescore
```
