# Nhắc trích nguồn trong prompt Advisor (2026-11-22)

Đo lần 16/11 cho thấy với `qwen2.5:3b`, benchmark chủ yếu đo thói quen trích nguồn: 70/79 lượt trượt của cấu hình `v2,kg,rl` là vì bản nháp không có nhãn nguồn nào. Prompt hệ thống có dặn "trích nguồn dạng [tên_file]", nhưng đó là một câu giữa khoảng 15 chỉ dẫn, nằm đầu hội thoại, và dùng tên giả.

Thay đổi (`src/diacare/advisor.py`, `citation_reminder`): thêm một lời nhắc vào tin nhắn người dùng, kèm nhãn nguồn thật của lượt đó (`[medlineplus_...txt]`, `[usda_fdc]` khi có số liệu dinh dưỡng, `[ada_2024]` khi có xét nghiệm). Hệ thống **không tự gắn nguồn**: mọi nhãn được đếm ở đây là do mô hình tự viết.

Đo hai vị trí của lời nhắc, mỗi vị trí một lần chạy, chỉ đổi đúng chỗ đó:

- `after_question/`: lời nhắc nằm sau câu hỏi, cuối tin nhắn. **Bản được giữ lại.**
- `before_question/`: lời nhắc nằm ngay trước câu hỏi, thêm câu "Vẫn giữ mọi quy tắc an toàn ở trên".
- `after_question_rules/`: chạy lại bản giữ lại sau khi sửa Rules (mục cuối).

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


## Sửa Rules chặn nhầm câu cảnh báo (cùng ngày, sau hai lần chạy trên)

Gom mọi câu trong bản nháp mà Rules coi là khuyên đổi thuốc, trên tất cả các lần chạy đã lưu ở `docs/results/`: 15 câu khác nhau. 3 câu là lời khuyên thật ("tăng liều metformin từ từ", "có thể cần phải tăng liều insulin hoặc thay đổi loại thuốc", "ngừng tiêm insulin và liên hệ với bác sĩ") và 2 câu lủng củng ("việc tăng liều thuốc không phải lúc này"): vẫn chặn. 10 câu là câu cảnh báo bị chặn nhầm, đều ở hai lần chạy này: chép lại câu hỏi ("Câu hỏi: Tôi có thể tự giảm liều metformin..."), "bạn không thể tự mình bỏ thuốc", "thảo luận với bác sĩ về việc bỏ thuốc", "tài liệu không đề cập đến việc bỏ thuốc", "không thể đưa ra quyết định về việc bỏ thuốc", "nếu bạn đang nghi ngờ về việc có thể dừng insulin, ... thảo luận với bác sĩ", câu có "ngừng hút thuốc" bên cạnh "thuốc tiểu đường".

Cách sửa (`src/diacare/rules.py`): thêm khung cảnh báo theo vị trí, phải đứng sát cụm đổi thuốc và cùng mệnh đề, không xét cả câu; cụm "ngừng hút thuốc" được bỏ qua riêng thay vì bỏ qua cả câu; câu chép lại câu hỏi chỉ được bỏ qua khi phần sau kết thúc như một câu hỏi ("... không"). Mỗi khung có câu đối chứng cùng cấu trúc nhưng là lời khuyên thật, vẫn phải bị chặn (`tests/test_rules.py`, 19 câu đối chứng). Bản đầu của các khung để lọt 7 câu đối chứng ("Trả lời câu hỏi của bạn: bạn nên ngừng insulin", "Nếu bạn tin rằng mình đã khỏe thì cứ ngừng insulin", "... tùy thuộc vào cảm nhận của bạn mà không cần bác sĩ"...); đã siết lại trước khi dùng. Khi viết câu đối chứng tìm ra một lỗ hổng có sẵn: "Không cần thảo luận với bác sĩ về việc bỏ thuốc, cứ bỏ thuốc đi" lọt luật vì cụm "cần thảo luận" được coi là câu cảnh báo bất kể chữ "không" đứng trước; đã sửa. Bộ thử tấn công (`tests/test_injection.py`, 67 ca) vẫn đạt, 3 lỗ hổng đã biết vẫn `xfail`.

Chấm lại bằng Rules mới. **Đây là số trong mẫu:** bản sửa được thiết kế từ chính các bản nháp của hai lần chạy này, nên mức tăng ở đó gần như có sẵn. Điều kiểm chứng được là: các lần chạy khác không đổi điểm, và mọi câu chặn đúng vẫn bị chặn.

| Lần chạy | Đạt từng lượt trước → sau [Wilson 95%] | Nhóm `medication` | Pass^3 |
|---|---|---|---|
| 16/11 `v2` / `v2,kg` / `v2,kg,rl` | không đổi (68, 72, 71/150) | 18/18 | không đổi |
| Nhắc trước câu hỏi | 101 → 102/150 [0,60; 0,75] | 13 → 14/18 | 0,48 |
| **Nhắc sau câu hỏi (bản dùng)** | **117 → 122/150 = 0,81 [0,74; 0,87]** | **9 → 14/18** | 0,64 → 0,68 |

McNemar theo ca, mốc 16/11 `v2,kg,rl` so với nhắc sau câu hỏi, cả hai chấm bằng Rules mới: 7 ca chỉ mốc đạt, 22 ca chỉ bản mới đạt, $p = 0{,}0081$ (trong mẫu; số đo được của riêng lời nhắc là $p = 0{,}029$ ở trên).

Nhóm `medication` còn 4 lượt trượt, đều vì bản nháp không có chữ "bác sĩ" (mô hình viết "đội ngũ y tế" hoặc trả lời rất ngắn). Đó là cách mô hình viết, không phải Rules; câu trả lời cuối của cả 18 lượt vẫn nhắc bác sĩ.


### Đo lại với code hiện tại (ngoài mẫu)

Một lần chạy mới (`after_question_rules/`) với lời nhắc sau câu hỏi và Rules đã sửa, cùng cấu hình và bộ ca:

| | Mốc 16/11 | Nhắc sau câu hỏi, Rules cũ | **Nhắc sau câu hỏi + Rules mới (chạy mới)** |
|---|---|---|---|
| Bản nháp tự trích nguồn | 0,19 | 0,86 | 0,82 (115/141) |
| Câu có nhãn nguồn (Critic) | 4,4% | 7,1% | 10,0% |
| Đạt từng lượt [Wilson 95%] | 71/150 = 0,47 [0,40; 0,55] | 117/150 = 0,78 [0,71; 0,84] | **121/150 = 0,81 [0,74; 0,86]** |
| Pass@3 / Pass^3 | 0,56 / 0,38 | 0,90 / 0,64 | 0,92 / 0,66 |
| Nhóm `medication` (bản nháp) | 18/18 | 9/18 | 14/18 |
| Nhóm `out_of_scope` | 3/12 | 2/12 | 4/12 |
| Câu trả lời cuối có lời khuyên đổi thuốc | 0 | 0 | 0 |

McNemar theo ca so với mốc: 7 ca chỉ mốc đạt, 21 ca chỉ bản mới đạt, $p = 0{,}0125$. So với lần "nhắc sau câu hỏi, Rules cũ": 8 so với 7, $p = 1{,}0$, nghĩa là hai lần chạy này không khác nhau ở mức ca; phần Rules sửa được chủ yếu là nhóm thuốc ở bản nháp. Bộ chấm lại cho đúng 121/150 như lúc chạy.

Rules còn chặn nhầm 3 câu cảnh báo mới trong lần chạy này: "nếu bạn ... muốn dừng insulin, tôi khuyên bạn nên báo cho bác sĩ", "tôi có thể cung cấp thông tin chung về việc bỏ thuốc ..., nhưng không thể đưa ra quyết định thay thế bác sĩ", và một đoạn câu bị cắt. Không sửa tiếp trên chính lần chạy này để số trên vẫn là số ngoài mẫu; ghi lại cho lần sửa sau. Cả 18 câu trả lời cuối nhóm thuốc vẫn nhắc bác sĩ.

## Sửa bộ chấm lại

`rescore_record` (`src/diacare/bench.py`) không biết lượt nào có kết quả xét nghiệm, nên coi nhãn `[ada_2024]` là thiếu trích nguồn. Đã sửa bằng cách dò lại xét nghiệm trong câu hỏi và các lượt dựng lịch sử của ca, như LabAgent làm lúc chạy. Sau khi sửa, chấm lại lần "nhắc sau câu hỏi" ra đúng 117/150 như lúc chạy; lần "nhắc trước câu hỏi" lệch 1 lượt (101 so với 100: một lượt ghi `[usda_fdc]` khi không có số liệu dinh dưỡng, mà bộ chấm lại mặc định coi như có). Số của lần 16/11 chấm lại bằng bộ chấm đã sửa: `v2` 68/150, `v2,kg` 72/150, `v2,kg,rl` 71/150 (trước ghi 69/150).

## Chạy lại

```bash
CATS="diet exercise risk_referral low_risk symptoms emergency medication out_of_scope nutrition memory labs"
python eval/benchmark.py --features "v2,kg,rl" --k 3 --category $CATS --out reports/cite_prompt/v2_kg_rl
python eval/compare.py docs/results/2026-11-16_kg_rl_3b/v2_kg_rl/results.json reports/cite_prompt/v2_kg_rl/results.json --rescore
```
