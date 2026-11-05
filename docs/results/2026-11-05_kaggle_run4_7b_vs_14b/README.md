# Benchmark Kaggle lần 4: qwen2.5 7B và 14B (2026-11-05)

Kernel `diacare-mas-benchmark` version 4, GPU T4, `num_ctx` 4096, embedding sbert, cấu hình `v2`
(nutrition, memory, labs), 50 ca × k = 3. Thư mục này là báo cáo gốc do Kaggle sinh ra.

| Model | Pass@3 | Pass^3 | Đạt từng lượt (Wilson 95%) | Giây TB | Giây trung vị | Giây p95 |
|---|---|---|---|---|---|---|
| qwen2.5:7b | 0.90 | 0.68 | 0.81 [0.74; 0.86] | 10.4 | 9.5 | 21.5 |
| qwen2.5:14b | 0.54 | 0.40 | 0.47 [0.40; 0.55] | 15.5 | 12.0 | 33.8 |

## Vì sao 14B thấp hơn

1. **Không theo định dạng trích nguồn.** 71/150 lượt của 14B trượt vì không ghi `[tên_file]`
   (7B: 24/150). Chỉ 29 bản nháp của 14B có trích nguồn đúng dạng (7B: 91). Bản nháp 14B dài hơn và
   trình bày bằng gạch đầu dòng, markdown, nhưng bỏ qua lời dặn trích nguồn.
2. **Bộ lọc thuốc chặn nhầm câu cảnh báo kiểu mới.** 3 lượt của 14B (và 1 của 7B) bị coi là lời khuyên
   nguy hiểm, nhưng cả 4 câu đều là cảnh báo dạng "việc dừng insulin ... không phải là điều bạn nên tự
   quyết định". Bộ lọc chưa nhận cấu trúc phủ định "... không phải là ...". Không có lời khuyên đổi thuốc thật.
3. **Bỏ hai lỗi trên ra thì hai model ngang nhau**: tính chặn nhầm là đạt và không xét trích nguồn,
   7B đạt 146/150, 14B đạt 145/150.

Kết luận: với harness hiện tại (lời dặn hệ thống, bộ chấm và bộ lọc rút ra từ bản nháp của 7B), đổi lên 14B
**không** cải thiện gì mà còn chậm hơn khoảng 1,5 lần. Muốn dùng 14B phải chỉnh harness cho nó: lời dặn trích
nguồn chặt hơn (có ví dụ mẫu) và thêm mẫu câu cảnh báo "không phải là" vào bộ lọc.
