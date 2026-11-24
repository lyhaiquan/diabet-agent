# Câu trả lời giọng tư vấn, hiển thị cho người bệnh (2026-11-24)

So với lần chạy `docs/results/2026-11-22_concise_allergy_3b/run`. Máy cá nhân, `qwen2.5:3b`, cấu hình `v2,kg,rl`, 50 ca × 3 lượt, cùng bộ ca.

Ba thay đổi, chỉ thay đổi thứ ba làm đổi chữ mô hình sinh ra:

1. **Hiển thị** (`src/diacare/present.py`, chỉ ở giao diện Streamlit, câu trả lời cuối giữ nguyên từng ký tự):
   - nhãn `[medlineplus_diabetic_diet.txt]` thành chú thích ¹, nhãn lặp liền nhau trong một đoạn gộp lại, cuối bài có
     dòng "Nguồn: ¹ MedlinePlus – Chế độ ăn cho người đái tháo đường";
   - câu "Đây chỉ là thông tin tham khảo…" in nhỏ dưới tin nhắn thay vì nằm trong thân bài;
   - dòng "Trọng tâm tư vấn do agent học tăng cường chọn" và nút 👍/👎 chỉ còn ở chế độ nhà phát triển.
2. **Lời nhắc tái khám cho người đã chẩn đoán chỉ nói một lần mỗi phiên** (`rules.apply_rules(remind_diagnosed=)`).
   Cờ `diagnosed_followup` vẫn bật. Lời nhắc triệu chứng, cấp cứu, hạ đường huyết vẫn nhắc mỗi lần cần.
3. **Prompt giọng tư vấn** (`src/diacare/advisor.py`): xưng "mình", gọi "bạn", không viết "dựa trên tài liệu"; dòng
   cuối dặn bốn nhịp: trả lời thẳng, giải thích vì sao chỉ bằng con số có trong ngữ cảnh, 2–3 việc cụ thể, khi nào nên đi khám.

Lý do: câu trả lời trước đọc như log ("… [medlineplus_diabetic_diet.txt] … [medlineplus_diabetic_diet.txt]"), có ba
lời nhắc mẫu chồng ở cuối, lặp lại mọi lượt.

## Kết quả

| | Trước | Giọng tư vấn |
|---|---|---|
| Đạt từng lượt, cả 50 ca | 131/150 = 0,87 | 127/150 = 0,85 [0,78; 0,90] |
| Pass^3 | 0,78 | 0,70 |
| McNemar theo ca (bỏ nhóm ngoài chủ đề) | | 9 ca chỉ trước đạt, 5 ca chỉ sau đạt, $p = 0{,}42$ |
| Bản nháp có nhãn nguồn (đếm bằng regex) | 116/150 | 113/150 |
| Độ dài trung bình bản nháp | 90 chữ | 133 chữ |
| Thời gian trung bình mỗi lượt | 4,0 giây | 4,7 giây |
| Số không có trong ngữ cảnh (Critic, `unsupported_number`) | 11 lượt | **20 lượt** |
| Bản nháp xen chữ Hán | 4 | 8 |

Theo nhóm: `symptoms` 1,00 → 0,75, `diet` 0,83 → 0,72, `nutrition` 0,83 → 0,72 kém đi; `memory` 0,67 → 0,83,
`risk_referral` 0,58 → 0,67 tốt lên.

**Đọc kết quả:** điểm benchmark không khác biệt có ý nghĩa ($p = 0{,}42$), và tỉ lệ trích nguồn giữ được. Nhưng mô
hình 3B viết dài hơn và **tự đưa ra con số nhiều gần gấp đôi** dù đã dặn "chỉ dùng con số có trong thông tin ở trên"
(ví dụ khi chạy thử: "8 thìa đường là khoảng 328 g"). Dặn "giải thích vì sao bằng con số" có lẽ lại gợi mô hình bịa
số. Phần hiển thị (1) và nhắc một lần mỗi phiên (2) không phụ thuộc kết quả này.

Chưa làm: bản prompt bỏ cụm "con số" ở nhịp (2) để đo xem số bịa có giảm lại không.
