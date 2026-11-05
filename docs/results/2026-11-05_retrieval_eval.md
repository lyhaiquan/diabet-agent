# Retrieval evaluation: dense vs BM25 vs hybrid (RRF)

Measured on 2026-11-05: source-level recall@1, recall@4, MRR over 24 on-topic Vietnamese queries, and the empty-result rate over 4 off-topic queries (eval/retrieval_cases.json).
Embedding: sbert paraphrase-multilingual-MiniLM-L12-v2 (dense threshold 0.2); KB: the 5 files in kb/; k=4, chunks of 600 chars / 100 overlap, RRF k=60.
Command: `python eval/retrieval_eval.py --embed sbert`. "Missed" below = no relevant source in the top 4.

| mode | recall@1 | recall@4 | MRR | off-topic empty rate | off-topic mean chunks |
|---|---|---|---|---|---|
| dense (no threshold) | 0.625 | 0.875 | 0.722 | 0.00 | 4.00 |
| dense (min_score=0.2) | 0.625 | 0.875 | 0.722 | 0.75 | 1.00 |
| bm25 | 0.333 | 0.625 | 0.469 | 0.25 | 2.25 |
| hybrid RRF (min_score=0.2) | 0.667 | 0.833 | 0.736 | 0.25 | 2.25 |

KB: medlineplus_diabetes.txt, medlineplus_diabetic_diet.txt, medlineplus_hypoglycemia.txt, medlineplus_type2_diabetes.txt, who_diabetes_factsheet.txt; embed=sbert; k=4; on-topic=24, off-topic=4
Missed by every mode: diet_plan, hypo_symptoms


## Lần 2: chia đoạn theo ranh giới đoạn/câu/từ (cùng ngày)

Bản chia đoạn cũ cắt cứng mỗi 600 ký tự nên có chữ bị cắt đôi ("has" thành "ha" rồi khớp nhầm "Hà Nội").
Sau khi `chunk_text` cắt ở ranh giới đoạn văn, câu hoặc khoảng trắng (0/68 đoạn còn kết thúc giữa từ):

| mode | recall@1 | recall@4 | MRR | off-topic empty rate | off-topic mean chunks |
|---|---|---|---|---|---|
| dense (no threshold) | 0.708 | 0.917 | 0.785 | 0.00 | 4.00 |
| dense (min_score=0.2) | 0.708 | 0.917 | 0.785 | 0.50 | 1.25 |
| bm25 | 0.333 | 0.500 | 0.410 | 0.50 | 2.00 |
| hybrid RRF (min_score=0.2) | 0.750 | 0.917 | 0.809 | 0.25 | 2.25 |

Bỏ sót ở mọi chế độ: diet_plan.

Quyết định: V2 mặc định dùng dense + ngưỡng 0.2 (`DIACARE_FEATURES=v2`). Hybrid nhỉnh hơn một câu ở recall@1
và MRR (trong mức nhiễu với 24 câu) nhưng lọc câu ngoài chủ đề kém hơn rõ (0.25 so với 0.50), nên chỉ bật khi chọn `all`.
