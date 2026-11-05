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
