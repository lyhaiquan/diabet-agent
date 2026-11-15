# Benchmark nhóm ca nhật ký, qwen2.5:3b (2026-11-15)

Máy cá nhân (GPU 4 GB), Ollama `qwen2.5:3b`, `num_ctx` 4096, embedding băm (`DIACARE_EMBED=hash`), 12 ca nhóm
`journal` × k = 3. Hai cấu hình chỉ khác nhau ở agent Journal:

```bash
python eval/benchmark.py --llm ollama --models qwen2.5:3b --k 3 --category journal --features default  --out journal_on
python eval/benchmark.py --llm ollama --models qwen2.5:3b --k 3 --category journal --features v2,kg,rl --out journal_off
python eval/compare.py journal_off/results.json journal_on/results.json > mcnemar.txt
```

| Cấu hình | Pass@3 | Pass^3 | Đạt từng lượt (Wilson 95%) |
|---|---|---|---|
| có Journal (`default`) | 0.92 | 0.50 | 0.78 [0.62; 0.88] (28/36) |
| không Journal (`v2,kg,rl`) | 0.08 | 0.08 | 0.08 [0.03; 0.22] (3/36) |

So theo ca (đạt = đạt cả ba lượt): 6 ca chỉ đạt khi có Journal, 1 ca chỉ đạt khi không có (`journal_12`, ca chưa ghi
nhật ký), McNemar chính xác p = 0,125. Với 12 ca, khác biệt theo ca chưa đạt mức 0,05.

Ca còn trượt khi có Journal: `journal_5` (0/3, không trích nguồn), `journal_1`, `journal_8`, `journal_9`,
`journal_10`, `journal_12` (mỗi ca 2/3). Lượt trượt của `journal_10` là chặn nhầm: câu "Họ có thể cần phải điều chỉnh
liều metformin hoặc ... tăng liều insulin" nói về bác sĩ.

Dữ liệu trong các ca là số liệu tự đặt (xem `tools/add_journal_cases.py`), không phải của người thật. Thời gian trong
nhật ký tính lùi từ lúc chạy, nên chạy lại vào ngày khác sẽ ra ngày tháng khác trong bản nháp.
