# DiaCare-MAS V1

Hệ đa agent hỗ trợ tư vấn phòng ngừa tiểu đường (đồ án học tập, không thay thế bác sĩ).

```
Hồ sơ + câu hỏi -> Orchestrator -> Predictor (MLP, CDC BRFSS)
                               -> Advisor (RAG trên kb/, LLM qua Ollama)
                               -> Rule agent (an toàn, chuyển khám) -> câu trả lời
                  SQLite lưu bệnh nhân, hội thoại, mọi lượt chạy (token, độ trễ, cờ)
```

## 1. Cài đặt (một lần)

```bash
pip install -r requirements.txt
```

Ollama (chạy LLM trên máy). Cài từ https://ollama.com/download hoặc `winget install Ollama.Ollama`.
Ổ C còn ít chỗ thì đặt thư mục model sang ổ khác TRƯỚC khi tải model (PowerShell):

```powershell
setx OLLAMA_MODELS "D:\ollama\models"
```

Mở lại terminal rồi tải model nhẹ để thử luồng (khoảng 2 GB), bản 7B (khoảng 4-5 GB) dùng khi lấy số liệu cuối:

```bash
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
```

Tài liệu tri thức: đặt 3-5 file `.txt`, `.md` hoặc `.pdf` (hướng dẫn Bộ Y tế, ADA, WHO...) vào thư mục `kb/`.
PDF tiếng Việt bị lỗi font khi trích chữ thì chuyển các trang cần dùng sang `.txt`.
Lần chạy đầu tiên sẽ tự tải model embedding (khoảng 470 MB).

## 2. Chạy

Giao diện web:

```bash
streamlit run src/app.py
```

CLI (lệnh `/patients`, `/history`, `/stats`, `q`):

```bash
python src/cli.py --name "An" --profile hoso.json
```

Benchmark và báo cáo đo đạc (ghi vào `reports/benchmark_<thời gian>/`: `report.md`, `results.json`, biểu đồ PNG):

```bash
python eval/benchmark.py --models qwen2.5:3b qwen2.5:7b --k 3 --num-ctx 4096
```

Chế độ demo (LLM giả + embedding băm, không cần Ollama, chỉ để thử giao diện và sinh báo cáo mẫu):

```powershell
$env:DIACARE_LLM="demo"; $env:DIACARE_EMBED="hash"; $env:DIACARE_KB="đường\dẫn\tới\thư_mục_có_ít_nhất_một_file"
streamlit run src/app.py
```

## 3. Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `DIACARE_LLM` | `ollama` | `ollama` hoặc `demo` |
| `DIACARE_MODEL` | `qwen2.5:3b` | tên model Ollama |
| `DIACARE_NUM_CTX` | `4096` | cửa sổ context gửi cho Ollama |
| `DIACARE_EMBED` | `sbert` | `sbert` hoặc `hash` (demo) |
| `DIACARE_MIN_SCORE` | `0.2` (sbert), `0` (hash) | ngưỡng điểm truy xuất; đoạn thấp hơn bị bỏ |
| `DIACARE_KB` | `kb/` | thư mục tài liệu tri thức |
| `DIACARE_DB` | `data/diacare.db` | file SQLite |
| `DIACARE_LOG` | `logs/runs.jsonl` | log JSONL từng lượt chạy |
| `DIACARE_FEATURES` | `all` | tính năng V2 bật (`nutrition`, ...); `v1` tắt hết để đo ablation |

## 4. Đọc kết quả benchmark

- **Pass@k**: tỉ lệ ca có ít nhất 1 lần đạt trong k lần (năng lực tối đa).
- **Pass^k**: tỉ lệ ca đạt cả k lần (độ tin cậy lặp lại, quan trọng với y tế).
- Mỗi ca chấm trên bản nháp thật của LLM: có trích nguồn đã truy xuất, không khuyên đổi thuốc, nhắc bác sĩ, và các cờ chuyển khám/cấp cứu.
- Mục "Hiệu chỉnh token" gợi ý giá trị `CHARS_PER_TOKEN` trong `src/diacare/context.py` theo số đo thật của model bạn dùng.
- Dataset benchmark: `eval/cases.json` (36 ca, 8 nhóm), sửa hoặc thêm ca trực tiếp trong file này.
- Số đo Predictor (AUC, F1, recall) lấy từ `models/metrics.json`.

## 5. Hạn chế đã biết

- Kiểm tra từ khóa triệu chứng/cấp cứu và lọc thuốc nguy hiểm dựa trên chữ có dấu; câu hỏi gõ không dấu có thể không kích hoạt luật chuyển khám.
- Benchmark chấm an toàn, trích nguồn và định dạng, không chấm độ đúng y khoa của nội dung.
- Khối Reinforcement Learning (Coach agent trong sơ đồ) thuộc V3, chưa làm.
- Điểm nguy cơ của MLP chưa được hiệu chỉnh; giao diện chỉ hiển thị mức thấp/trung bình/cao.
