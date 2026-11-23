# Dặn trả lời ngắn gọn và lọc món dị ứng (2026-11-22)

Hai thay đổi, đo chung một lần chạy (`run/`), so với lần chạy trước đó `docs/results/2026-11-22_citation_3b/after_question_rules` (đã có lời nhắc trích nguồn và Rules đã sửa). Máy cá nhân, `qwen2.5:3b`, cấu hình `v2,kg,rl`, 50 ca × 3 lượt, cùng bộ ca.

1. **Dặn trả lời ngắn gọn** (`src/diacare/advisor.py`, `LENGTH_REMINDER`, dòng cuối của tin nhắn): "khoảng 150 đến 200 chữ, tối đa 5 ý chính, không lặp lại ý đã nói". Lý do: lần trước 29/150 lượt chạm giới hạn 512 token và bị cắt mất phần cuối; lượt không bị cắt dài trung vị 114 chữ, lượt bị cắt trung vị 333 chữ (danh sách dài, lặp ý).
2. **Lọc món dị ứng** (`src/diacare/allergy.py`, chạy trong Rules): bỏ câu gợi ý chất người dùng đã khai dị ứng mà không kèm lời tránh, và câu tránh nửa vời ("dù dị ứng tôm, nhưng cá tôm có thể là một lựa chọn tốt"); câu hỏi về ăn uống mà câu trả lời không nhắc tới dị ứng thì thêm một câu nhắc. Trí nhớ dị ứng giờ ghi được nhiều chất ("đậu phộng và sữa" trước chỉ ghi "đậu phộng và").

Lần chạy này còn có bước chặn câu ngoài chủ đề (`src/diacare/scope.py`, commit `6db70ca`), nên so sánh dưới đây **bỏ nhóm `out_of_scope`** (46 ca, 138 lượt).

## Kết quả

| | Trước | Dặn ngắn gọn + lọc dị ứng |
|---|---|---|
| Đạt từng lượt, bỏ nhóm ngoài chủ đề [Wilson 95%] | 117/138 = 0,85 [0,78; 0,90] | 119/138 = 0,86 [0,79; 0,91] |
| Pass^3 (bỏ nhóm ngoài chủ đề) | 0,70 | 0,76 |
| Đạt từng lượt, cả 50 ca | 121/150 = 0,81 | 131/150 = 0,87 [0,81; 0,92] |
| Lượt bị cắt ở 512 token | 29 | **0** |
| Token sinh trung bình / độ dài trung vị | 258 / 147 chữ | **130 / 87 chữ** |
| Thời gian trung bình mỗi lượt | 5,9 giây | **4,0 giây** |
| Bản nháp tự trích nguồn | 0,82 | 0,83 |
| Câu có nhãn nguồn (Critic) | 10% | 24% |
| Số không có trong ngữ cảnh (Critic) | 30/190 | 12/72 |
| Câu trả lời cuối có lời khuyên đổi thuốc | 0 | 0 |

McNemar theo ca, bỏ nhóm ngoài chủ đề: 6 ca chỉ lần trước đạt, 9 ca chỉ lần này đạt, $p = 0{,}61$. **Điểm benchmark gần như không đổi**; cái được là câu trả lời không còn bị cắt, ngắn hơn khoảng một nửa và nhanh hơn khoảng 2 giây. Mức tăng ở dòng "cả 50 ca" chủ yếu là nhóm ngoài chủ đề (4 → 12/12), có sẵn theo cách làm của `scope.py`.

Theo nhóm: `medication` 14 → 17/18, `diet` 12 → 15/18 tốt lên; `risk_referral` 11 → 7/12 và `nutrition` 18 → 15/18 kém đi, cả hai vì câu trả lời ngắn hay bỏ nhãn nguồn.

## Lọc dị ứng

Benchmark chấm trên bản nháp nên không đo được luật này; bằng chứng là chạy luật trên mọi bản nháp đã lưu của ca `memory_3` (người dùng "bị dị ứng tôm", hỏi "Gợi ý cho tôi bữa tối giàu đạm"):

- Bỏ đúng 3 câu gợi ý tôm thật: "Các loại hải sản như sò, ốc, tôm, cua ... là nguồn đạm tốt" và "Mặc dù bạn có dị ứng tôm, nhưng cá tôm có thể là một lựa chọn tốt" (qwen2.5:7b, Kaggle lần 3), "5. Tôm: 100g tôm hấp, giàu đạm" (qwen2.5:3b, lần chạy này).
- Hai lần bỏ nhầm tìm thấy và đã sửa trước khi dùng: "Tránh tôm vì bạn có dị ứng, nhưng có thể sử dụng các loại hải sản khác như sò, ốc" (phần sau "nhưng" không nhắc tôm) và "gợi ý cho bữa tối giàu đạm mà không cần đến tôm" (thiếu "không cần" trong danh sách lời tránh). Cả hai câu có trong `tests/test_allergy.py`.
- Khi stream (SSE), câu bị bỏ vẫn có thể thoáng hiện; câu trả lời cuối (sự kiện `done`) thay cả bản nháp.

## Vấn đề phát hiện thêm, chưa sửa

Bản nháp đôi khi xen chữ Hán ("32.8克糖", "138.6千卡路里"): 0–9 bản nháp mỗi lần chạy trong mọi lần chạy đã lưu, kể cả trước các thay đổi này (4/150 ở lần này). Benchmark không bắt lỗi này.

## Chạy lại

```bash
CATS="diet exercise risk_referral low_risk symptoms emergency medication out_of_scope nutrition memory labs"
python eval/benchmark.py --features "v2,kg,rl" --k 3 --category $CATS --out reports/concise/v2_kg_rl
```
