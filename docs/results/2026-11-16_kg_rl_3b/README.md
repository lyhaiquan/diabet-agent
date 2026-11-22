# Benchmark đồ thị tri thức và RL (2026-11-16)

So ba cấu hình trên cùng bộ ca: `v2` (dinh dưỡng, bộ nhớ, xét nghiệm), `v2,kg` (thêm Graph agent), `v2,kg,rl` (thêm RLAgent, $\varepsilon = 0$).

- Máy cá nhân, Ollama `qwen2.5:3b`, `num_ctx` 4096, embedding Sentence-BERT, kho 14 tài liệu.
- 11 nhóm, bỏ nhóm `journal`: 50 ca × 3 lượt = 150 lượt mỗi cấu hình. Tệp jsonl có 162 dòng vì ghi cả các lượt dựng lịch sử của ca bộ nhớ.
- Ba cấu hình chạy nối tiếp nhau theo thứ tự trên (07:54 → 08:57). Cấu hình `v2` chạy đầu tiên và trùng lúc với các script khác trên máy, nên **không so thời gian giữa các cấu hình**.
- Một lượt `v2/diet_4` lỗi `HTTPError` từ Ollama (lỗi tạm thời), tính là trượt.

## Kết quả (đã chấm lại bằng luật hiện tại)

Ngày 22/11 bộ chấm lại được sửa: trước đó nó không biết lượt nào có kết quả xét nghiệm nên coi nhãn `[ada_2024]` là thiếu trích nguồn. Chấm lại bằng bộ đã sửa chỉ đổi dòng `v2,kg,rl` (69 thành 71/150); McNemar không đổi. Lần đo tiếp theo, thêm lời nhắc trích nguồn vào prompt: `docs/results/2026-11-22_citation_3b/`.

Sau khi chạy, Rules được sửa hai lần: mẫu "không cần dùng ... thuốc" bỏ qua cụm "mà không cần", và câu cảnh báo được nhận theo vị trí của cụm từ (xem `docs/report/baocao_chitiet.md`, mục 3.12). Số dưới đây là kết quả chấm lại bằng luật đã sửa (`rescored_summary.txt`, `mcnemar.txt`); số trong `*/report.md` là số chấm lúc chạy.

| Cấu hình | Pass@3 | Pass^3 | Đạt từng lượt [Wilson 95%] |
|---|---|---|---|
| v2 | 0,56 | 0,36 | 0,45 [0,38; 0,53] (68/150) |
| v2,kg | 0,60 | 0,34 | 0,48 [0,40; 0,56] (72/150) |
| v2,kg,rl | 0,56 | 0,38 | 0,47 [0,40; 0,55] (71/150) |

McNemar chính xác theo ca (một ca đạt khi đạt cả 3 lượt):

| So sánh | Chỉ A đạt | Chỉ B đạt | p |
|---|---|---|---|
| v2 so với v2,kg | 2 | 1 | 1,0 |
| v2,kg so với v2,kg,rl | 0 | 2 | 0,5 |
| v2 so với v2,kg,rl | 2 | 3 | 1,0 |

## Đọc kết quả

1. **Không thấy khác biệt.** Không cặp nào khác nhau có ý nghĩa thống kê.
2. **Bộ ca gần như không chạm tới đồ thị.** Graph agent chỉ nhận ra yếu tố nguy cơ trong 21/150 lượt (7 ca). Nhóm duy nhất nhích lên là `risk_referral` (0,50 → 0,75 từng lượt, 4 ca). Kết luận đúng là "bộ ca này chưa đo được tác dụng của đồ thị", không phải "đồ thị không có tác dụng". Cần thêm ca hỏi thẳng về yếu tố nguy cơ.
3. **Với mô hình 3B, benchmark chủ yếu đo thói quen trích nguồn.** Trong 78–84 lượt trượt của mỗi cấu hình có 68–73 lượt trượt vì không trích nguồn. Critic đếm được chỉ khoảng 3–4% câu trong bản nháp có nhãn nguồn. KG và RL không đổi được thói quen này. Con số 0,44 không so được với 0,88 của lần chạy Kaggle: khác mô hình (3B so với 7B), máy, kho tài liệu (14 so với 5) và bộ ca.
4. **An toàn.** Không câu trả lời cuối nào khuyên đổi thuốc; điều này luôn đúng vì Rules chạy sau cùng. Điều đáng nói hơn: lúc chạy, 11 lượt Rules chặn câu trong bản nháp đều được đọc lại, và cả 11 là câu cảnh báo ("tự giảm liều metformin ... không phải là một ý kiến tốt"), không câu nào là lời khuyên đổi thuốc thật. Rules đã được sửa; chấm lại thì không lượt nào còn bị chặn và nhóm `medication` đạt 1,00 ở cả ba cấu hình. Các bản nháp không bị chặn chưa được người đọc hết.
5. **Critic.** Trong các con số có đơn vị mà bản nháp đưa ra, 10–16% không có trong ngữ cảnh (11/102, 12/118, 18/112). Phần lớn là số trong hướng dẫn chung như "150 phút mỗi tuần" mà mô hình lấy từ hiểu biết sẵn có. Đó là "không có trong ngữ cảnh", chưa chắc là bịa. Mức tăng ở `v2,kg,rl` dựa trên số đếm nhỏ, không đủ để quy cho RL.
6. **Chạy song song.** Theo vết, trung vị của Predictor khoảng 30 ms, Retriever khoảng 57 ms, Graph và Nutrition dưới 4 ms: chạy tuần tự khoảng 90 ms, chạy song song khoảng 60 ms. Tiết kiệm khoảng 30 ms trên khoảng 5,8 giây mỗi lượt (dưới 1%), vì Advisor chiếm gần hết thời gian. Chưa chạy cấu hình `DIACARE_PARALLEL=0` để so trực tiếp.

## Chạy lại

```bash
CATS="diet exercise risk_referral low_risk symptoms emergency medication out_of_scope nutrition memory labs"
for f in v2 "v2,kg" "v2,kg,rl"; do
  python eval/benchmark.py --features "$f" --k 3 --category $CATS --out reports/kg_rl/$(echo $f | tr ',' '_')
done
python eval/compare.py reports/kg_rl/v2/results.json reports/kg_rl/v2_kg/results.json --rescore
```
