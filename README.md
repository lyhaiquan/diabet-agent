# DiaCare-MAS: hệ đa agent hỗ trợ tư vấn phòng ngừa tiểu đường

Đồ án học tập. **Không thay thế bác sĩ**: mọi câu trả lời đều kèm lời nhắc tham khảo ý kiến chuyên môn,
kết quả xét nghiệm chỉ được *đối chiếu ngưỡng*, không phải chẩn đoán.

Hệ thống kết hợp bốn khối theo sơ đồ ý tưởng ban đầu:

1. **Dự đoán nguy cơ từ nhiều nguồn**: mô hình học trên CDC BRFSS 2015, BRFSS 2023 và NHANES 2013–2020 (khoảng 535 nghìn người, 21 chỉ số), xác suất đã hiệu chỉnh; kiểm tra ngoài trên Pima (NIDDK); mô hình triệu chứng từ UCI 529.
2. **Tri thức + RAG + Đồ thị tri thức (KG) + LLM**: truy xuất tài liệu (MedlinePlus, WHO) và đồ thị tri thức 5 loại cạnh rồi để LLM chạy cục bộ qua Ollama viết câu trả lời.
3. **Học tăng cường (RL)**: agent Q-learning chọn lời nhắc mỗi ngày cho người đã chẩn đoán, học từ nhật ký đường huyết (có đo không, chỉ số có đạt mục tiêu không), có mặt nạ an toàn; huấn luyện và đánh giá trên 30 người bệnh mô phỏng. Trong khung chat, một contextual bandit ($\gamma = 0$) chọn trọng tâm tư vấn.
4. **Luật an toàn**: chặn lời khuyên đổi thuốc, chuyển khám khi có triệu chứng, cấp cứu, xét nghiệm vượt ngưỡng.

## Kiến trúc

![Kiến trúc toàn hệ ở V4.9. Giữa là pipeline tư vấn: Orchestrator gọi 11 agent theo thứ tự cố định, bốn agent chỉ đọc chạy song song, chỉ Advisor gọi mô hình ngôn ngữ. Bên trái là các luồng không gọi LLM: giọng nói, trợ lý chủ động hỏi, nhập xét nghiệm và Agent bữa ăn. Khung tím là dịch vụ chạy ngoài DiaCare: Calo Khay (nhận diện món, project riêng) và Ollama (trên máy hoặc trên Kaggle).](docs/report/figs/c10_kien_truc_v49.png)

Ba phần:

- **Pipeline tư vấn** (giữa hình): Orchestrator gọi 11 agent cho mỗi câu hỏi, Critic kiểm tra bản nháp, Rules luôn chạy
  cuối. Chỉ Advisor gọi mô hình ngôn ngữ.
- **Luồng ngoài pipeline, không gọi LLM** (bên trái): giọng nói (PhoWhisper nghe, Piper đọc, đều chạy trên máy), trợ lý
  chủ động hỏi, nhập xét nghiệm (OCR), Agent bữa ăn.
- **Dịch vụ ngoài** (khung tím): **Calo Khay** nhận diện món trên ảnh khay cơm, là project riêng của nhóm, chạy ở cổng
  8010 trong môi trường có torch. Mã của nó **không nằm trong repo này**; DiaCare chỉ gọi HTTP (xem
  [Dịch vụ nhận diện món Calo Khay](#dịch-vụ-nhận-diện-món-calo-khay-trang-bữa-ăn)). **Ollama** chạy trên máy (3B) hoặc
  trên Kaggle (7B).

Hình sinh bằng `python docs/report/make_figs.py`.

Orchestrator gọi các agent **theo thứ tự cố định**; bốn agent chỉ đọc câu hỏi và hồ sơ (Predictor, Retriever, Graph,
Nutrition) chạy song song bằng luồng (`DIACARE_PARALLEL=0` để chạy tuần tự). Mỗi agent chỉ nhận lát ngữ cảnh mình cần
(`build_context`), bộ nhớ đứng trước xét nghiệm, rồi đến dinh dưỡng, đồ thị tri thức, định hướng RL và tài liệu khi cắt theo ngân sách token.

| Agent / Module | File | Vai trò |
|---|---|---|
| Orchestrator | `src/diacare/orchestrator.py` | Điều phối, bắt câu chào hỏi, ghi trace từng bước |
| Memory | `src/diacare/memory.py` | Trích và nhớ thông tin bệnh nhân (dị ứng, thuốc, chẩn đoán), tóm tắt lịch sử dài |
| Lab + OCR | `src/diacare/labs.py`, `ocr.py` | Đọc HbA1c, đường huyết lúc đói, OGTT 2 giờ, đường huyết bất kỳ (từ chữ, PDF scan, ảnh chụp); đổi đơn vị; xếp mức |
| Predictor | `src/diacare/predictor.py` | Dự đoán xác suất tiểu đường (đã hiệu chỉnh) từ 21 chỉ số hồ sơ; học trên 3 nguồn CDC |
| Retriever | `src/diacare/retriever.py` | Truy xuất dense (sbert), tuỳ chọn lai BM25 + RRF |
| Graph (KG) | `src/diacare/kg.py` | Đồ thị tri thức 5 loại cạnh (ADA 2024, luật, USDA, thống kê BRFSS, khẳng định KB đã kiểm chứng) trên Neo4j hoặc NetworkX |
| Nutrition | `src/diacare/nutrition.py` | Nhận món ăn Việt, tra USDA FoodData Central, xử lý từ đa nghĩa |
| Coach (Q-learning) | `src/diacare/coach.py`, `coach_sim.py` | Chọn lời nhắc mỗi ngày từ nhật ký 3 ngày qua; bảng Q 36 × 6, học ngoài chính sách (bảng `coach_events`, `models/q_coach.json`) |
| RL trọng tâm chat | `src/diacare/rl.py` | Contextual bandit ($\gamma = 0$) chọn trọng tâm tư vấn cho Advisor; 👍/👎 chỉ hiện ở chế độ nhà phát triển |
| Advisor | `src/diacare/advisor.py`, `llm.py` | Gọi Ollama `/api/chat`, hỗ trợ stream |
| Rules | `src/diacare/rules.py` | Chặn lời khuyên đổi thuốc, gắn cờ chuyển khám / cấp cứu / xét nghiệm |
| Agent bữa ăn (ngoài pipeline) | `src/diacare/meal_scan.py`, `src/meal_ui.py` | Gửi ảnh khay cơm cho Calo Khay, vẽ vùng và số từng món lên ảnh, bắt xác nhận món chưa chắc, tính khoảng tinh bột bằng bảng |
| Trợ lý chủ động hỏi (câu soạn sẵn, không phải agent) | `src/diacare/checkin.py`, `src/checkin_ui.py` | Mở lời mỗi ngày từ nhật ký; số đo trong câu trả lời hoặc câu kể ("vừa đo đường huyết 7,2") thành thẻ xác nhận |
| Giọng nói | `src/diacare/speech.py`, `tts.py`, `src/voice_ui.py` | PhoWhisper nhận dạng, Piper đọc to, nút micro to để nói chuyện rảnh tay |
| Critic (bước kiểm tra, không phải agent) | `src/diacare/critic.py` | So bản nháp với ngữ cảnh: nhãn nguồn lạ, con số có đơn vị không có trong ngữ cảnh; chỉ gắn cờ |
| Guard | `src/diacare/guard.py` | Dò dấu hiệu prompt injection trong câu hỏi (gắn cờ), loại đoạn tài liệu có câu ra lệnh cho mô hình |

## Tính năng

- **Tự theo dõi giữa hai lần tái khám** (cho người đã chẩn đoán ĐTĐ típ 2). Ba trang Hôm nay, Nhật ký, Tái khám:
  - ghi đường huyết, huyết áp, cân nặng (ghi bù được, nhưng giờ đo không được ở tương lai);
  - so với mục tiêu điều trị ADA 2024 (trước ăn 4,4–7,2 mmol/L, sau ăn < 10,0, huyết áp < 130/80), không so với ngưỡng
    chẩn đoán;
  - cảnh báo hạ đường huyết hoặc chỉ số rất cao, nhắc chưa đo hôm nay hay sắp tới lịch khám;
  - lập bản tóm tắt PDF một trang mang đi khám;
  - trang Tư vấn đọc nhật ký 14 ngày gần nhất (JournalAgent): trợ lý trả lời theo số đo của chính người dùng.
    Nhật ký được tóm tắt sẵn kèm nhận định cao hơn, thấp hơn hay trong mục tiêu, vì mô hình 3B hay tự so sai.
  - **trợ lý chủ động hỏi** (`src/diacare/checkin.py`, `src/checkin_ui.py`): mỗi ngày một lần, khi người đã chẩn đoán
    mở trang Tư vấn, trợ lý mở lời trước thay vì đợi người dùng gõ. Nó chọn một điều đáng hỏi nhất từ nhật ký: vừa có
    số đo hạ đường huyết hoặc rất cao trong 24 giờ, hôm nay chưa đo, mấy hôm cao liền, hoặc đã đo đủ thì hỏi có cần
    tư vấn gì không. Kèm theo là lời nhắc hôm nay của agent Q-learning (cùng lời với tab Hôm nay). Người dùng trả lời
    bằng chữ:
    - có số đo ("6,5", "7,8 sau ăn lúc 12h", "tối qua 9 giờ đo 8,1"): hiện thẻ xác nhận giá trị, đơn vị, thời điểm
      đo, ngày giờ; chỉ ghi vào nhật ký khi bấm **Lưu**, rồi trợ lý báo trong hay ngoài mục tiêu, kèm lời khuyên an
      toàn soạn sẵn nếu hạ đường huyết hoặc rất cao;
    - "chưa đo": một câu soạn sẵn, lượt hỏi vẫn mở để lát nữa gõ số vẫn ghi được;
    - kể triệu chứng ("run tay, vã mồ hôi", "không ổn") ngay sau câu hỏi về số đo nguy hiểm: nhắc lại lời khuyên an
      toàn soạn sẵn (quy tắc 15–15, gọi 115 nếu lả đi), không chờ LLM;
    - câu hỏi hay lời kể khác (kể cả "8,5 lúc đói có cao không?"): chuyển cho pipeline tư vấn như mọi câu hỏi, có lời
      mở đầu trong lịch sử để mô hình hiểu ngữ cảnh.

    Mọi câu của trợ lý ở đây là câu soạn sẵn từ dữ liệu nhật ký, không do LLM viết, và không chạy trong
    `orchestrator.run`, nên benchmark không đổi. Lượt hỏi mỗi ngày lưu ở bảng `checkins`. Ghi số đo đều đặn hơn
    cũng là thứ agent Q-learning được thưởng (có đo +1, bỏ đo −1).

    **Trả lời bằng giọng nói:** dưới lời mở đầu có ô ghi âm và nút "Đọc câu hỏi" (giọng tiếng Việt của máy). Ghi âm
    được nhận dạng bằng PhoWhisper ngay trên máy, rồi chữ nghe được hiện trong ô để sửa và bấm **Gửi** (Whisper có thể
    "bịa" câu khi gặp tiếng ồn, nên không gửi thẳng). Sau đó đi đúng đường của câu gõ chữ; số đọc bằng chữ ("sáu phẩy
    năm", "bảy rưỡi") được đổi thành số.

    **Trên web** (V4.9): trang Tư vấn của giao diện Next.js mở lời giống hệt, qua `POST .../checkin/open`,
    `.../checkin/reply`, `.../checkin/save`, `.../checkin/cancel`. Streamlit và API cùng gọi các hàm `open_for_day`,
    `handle_reply`, `save_reading` trong `checkin.py`, nên cả hai giao diện chung một lượt hỏi mỗi ngày (mở lời ở
    Streamlit thì web không hỏi lại). Số đo vẫn chỉ lưu khi bấm **Lưu vào nhật ký** trên thẻ xác nhận; máy chủ kiểm tra
    lại giá trị trước khi lưu. Micro trên web điền chữ nghe được vào ô nhập, rồi đi cùng đường với câu gõ.
  - **trang Bữa ăn: chụp khay cơm, ước lượng tinh bột** (`src/diacare/meal_scan.py`, `src/meal_ui.py`): người dùng
    tải hoặc chụp ảnh khay cơm; agent bữa ăn gửi ảnh cho dịch vụ **Calo Khay** (project xử lý ảnh riêng của nhóm:
    YOLO26s-seg + DINOv2 nhận diện 44 món căng tin, ước lượng gram theo diện tích so với đĩa) qua HTTP
    `POST /api/scan`. DiaCare hiện bảng món để kiểm tra: món mô hình chưa chắc phải tích **Đúng món** (hoặc đổi tên theo
    gợi ý) mới lưu được; gram sửa được, nhất là **cơm** (mô hình chưa đo được cơm, đang để mức trung bình 228 g, mà cơm
    là phần nhiều tinh bột nhất). Tinh bột tính theo bảng `data/nutrition/calo_khay_carb.csv`, ra một **khoảng**:
    thấp = gram × (1 − sai số) × carb, cao = gram × (1 + sai số) × carb cận trên; sai số gram ±30% (mức của Calo Khay),
    ±50% cho gram "trung bình" (cơm 228 g, hoặc không thấy đĩa), gram người dùng tự sửa thì ±15%. Đồ uống ghi "chưa tính". Bữa đã lưu ở bảng `meals` (danh sách món mã hoá như ghi
    chú). Không con số nào do LLM viết; đây là ước lượng để theo dõi, không dùng để tính liều insulin. Ảnh khay được
    vẽ lại với vùng và số thứ tự từng món (trùng cột `#` của bảng), để thấy món nào bị nhận sai. Có thể gửi ảnh ngay ở
    ô chat của trang Tư vấn.

    **Bữa không phải khay cơm** (V4.9): nút **Tự nhập món (không có ảnh)** mở bảng trống; bảng tinh bột có thêm 20 món
    người dùng tự chọn (phở, bún bò, bún chả, bánh cuốn, bánh mì, cháo, mì gói, xôi, khoai lang, ngô, yến mạch và 9 loại
    quả). Gram là cả phần ăn (cả bát phở gồm nước); món tự thêm tính sai số gram ±15%. Ví dụ một bát phở bò 600 g:
    khoảng 52–88 g tinh bột.

    **Trên web** (V4.9): trang **Bữa ăn** của Next.js làm đủ các bước trên. Trình duyệt gửi ảnh cho API
    (`POST /meals/scan`), API mới gọi Calo Khay; tinh bột tính ở máy chủ (`POST .../meals/estimate`) để hai giao diện
    ra cùng một khoảng. Lưu, xem, xoá bữa: `POST/GET .../meals`, `DELETE .../meals/{mid}`.

    **Gợi ý ăn uống từ đường huyết sau ăn** (`meal_scan.meal_advice`): thẻ ở trang Hôm nay và Bữa ăn (web:
    `GET .../meals/advice`). Từ các bữa có đường huyết sau ăn cao hơn mục tiêu, nó chỉ ra món góp nhiều tinh bột nhất
    ("Nên hạn chế: cơm trắng khoảng 290 g, góp khoảng 81 g tinh bột (95% tinh bột của 2 bữa cao). Thử bớt còn khoảng
    190 g") và món ít tinh bột có thể ăn thêm (lấy từ bảng, ưu tiên món có trong các bữa vẫn trong mục tiêu của chính
    người dùng). Tính bằng code, không qua LLM; một lần cao thì nói rõ là chưa đủ kết luận; 24 giờ qua có hạ đường
    huyết thì **không** khuyên ăn bớt; chưa đo sau ăn thì nhắc đo trước. Các câu này cũng vào ngữ cảnh của trang Tư
    vấn (ngân sách token riêng), để câu hỏi "hôm nay tôi nên ăn gì" được trả lời theo đúng dữ liệu của người dùng.
    Chỉ số tự đo trong nhật ký được tính, không tính phiếu xét nghiệm (không biết lấy máu lúc nào so với bữa ăn). Lần
    đo ghi "sau ăn" mà giờ đo quá sát (dưới 45 phút) hoặc quá xa (hơn 3 giờ) bữa gần nhất thì thẻ nói rõ vì sao chưa
    tính; bữa vừa ăn chưa có số đo thì thẻ ghi khung giờ nên đo (ví dụ "đo trong khoảng 16:50–19:05, tốt nhất khoảng
    18:05").

    **Nối với đường huyết:** mỗi bữa được ghép với lần đo đầu tiên 45 phút – 3 giờ sau bữa (cột "Đường huyết sau ăn";
    trong khoảng đó mà chưa đo thì trang nhắc đo). Trang Tư vấn đọc cả phần này (bữa gần nhất, đường huyết sau bữa,
    các bữa cao sau ăn trung bình bao nhiêu gam tinh bột so với các bữa trong mục tiêu), với ngân sách token riêng nên
    phần nhật ký đường huyết và benchmark không đổi.

  Giao diện mặc định là chế độ người dùng. Log agent, đồ thị tri thức và thống kê chỉ hiện khi bật **Chế độ nhà phát
  triển** (nút gạt ở thanh bên, hoặc `DIACARE_DEV=1`).
- **Dịch vụ API (FastAPI)** để giao diện web hoặc điện thoại gọi vào. Xem mục [Dịch vụ API](#dịch-vụ-api).
- **Giao diện chat** (Streamlit). Ô chat ghim dưới đáy màn hình. Câu trả lời **hiện dần theo từng câu** khi LLM
  đang viết: mỗi câu phải qua bộ lọc an toàn trước khi hiện, nên lời khuyên đổi thuốc không bao giờ lọt lên màn hình.
- **Nhập kết quả xét nghiệm (kèm OCR cho PDF scan & ảnh chụp)**: tải `.txt`, `.csv`, `.json`, `.pdf` (có lớp chữ hoặc PDF scan),
  ảnh `.png`, `.jpg`, `.jpeg`, dán nội dung phiếu, hoặc gõ thẳng trong chat ("HbA1c của tôi 6.8%"). Tự đổi mmol/L sang mg/dL,
  mmol/mol sang %, tự sửa lỗi OCR đơn vị phổ biến (`0/0` -> `%`, `mg/d1` -> `mg/dL`). File mẫu: `docs/samples/xet_nghiem_mau.txt`.
  Ở Nhật ký → Xét nghiệm, chọn tệp là tự lưu ngay. Ảnh phiếu gửi qua nút **+** của ô chat cũng được nhận ra và lưu
  (ảnh không đọc ra chỉ số thì coi là ảnh bữa ăn).

  | Chỉ số | Bình thường | Tiền tiểu đường | Ngưỡng tiểu đường |
  |---|---|---|---|
  | HbA1c | < 5.7% | 5.7–6.4% | ≥ 6.5% |
  | Đường huyết lúc đói | < 100 mg/dL | 100–125 | ≥ 126 |
  | OGTT 2 giờ | < 140 | 140–199 | ≥ 200 |
  | Đường huyết bất kỳ | | | ≥ 200 kèm triệu chứng |

  Dưới 70 mg/dL được đánh dấu hạ đường huyết, kèm lời nhắc gọi 115.
- **Xem agent hoạt động**: dưới mỗi câu trả lời có mục "Agent đã làm gì" (agent nào, làm gì, bao nhiêu ms).
  Trang **Hoạt động agent** có **sơ đồ động phát lại** đúng lượt chạy từ log, bảng từng bước, và biểu đồ thời gian
  trung bình mỗi agent. Log lưu trong SQLite (`runs.trace_json`) và `logs/runs.jsonl`. Tệp JSONL không mã hoá nên chỉ ghi độ dài câu hỏi,
  không ghi nguyên văn.
- **Hồ sơ bệnh nhân, phiên hội thoại, lịch sử, thống kê** lưu trong SQLite. Các cột chữ chứa thông tin sức khoẻ (tên,
  hồ sơ, hội thoại, trí nhớ, ghi chú, câu hỏi và câu trả lời trong log) được mã hoá Fernet; khoá ở `DIACARE_DB_KEY` hoặc
  tệp `<tên DB>.key` sinh một lần cạnh DB. Mã hoá bảo vệ khi lộ riêng tệp `.db`, không bảo vệ khi lộ cả máy.
- **So sánh hai mô hình dự đoán** trên cùng hồ sơ: MLP bản cũ và mô hình đa nguồn đã hiệu chỉnh
  (`GET /patients/{id}/risk-models`, hoặc bảng trong chế độ nhà phát triển).
- **Câu chào hỏi** được trả lời ngay, không dự đoán nguy cơ và không gọi LLM. Lời nhắc nguy cơ cao chỉ hiện một lần mỗi phiên,
  trừ khi người dùng hỏi thẳng.

## Cài đặt

```bash
pip install -r requirements.txt
```

Ollama: cài từ https://ollama.com/download, rồi tải model:

```bash
ollama pull qwen2.5:7b
```

Model 3B (`qwen2.5:3b`) nhẹ hơn, đủ để thử luồng. Lần chạy đầu sẽ tự tải model embedding (khoảng 470 MB).

**Huấn luyện lại Predictor** (mô hình đã có sẵn trong `models/`). Tải dữ liệu theo `../diacare_datasets/LINK_DATASET.md`
(BRFSS 2015, BRFSS 2023, NHANES, Pima, UCI 529), rồi:

```bash
python tools/build_multisource.py   # gộp về 21 chỉ số -> data/multisource/*.parquet
python tools/train_multisource.py   # huấn luyện, so với mô hình cũ, hiệu chỉnh -> models/predictor_ms.joblib
python tools/train_aux_models.py    # kiểm tra ngoài trên Pima, mô hình triệu chứng UCI 529
```

Bản cũ chỉ học BRFSS 2015 (`python src/train_predictor.py`) vẫn dùng được bằng `DIACARE_PREDICTOR=v1`.

## Chạy

**Trên Windows, một cú bấm:** bấm đúp `chay_local.bat`. Script tự bật Ollama nếu chưa chạy, tải model nếu chưa có,
nạp sẵn model vào GPU, đặt các biến môi trường rồi mở giao diện ở `http://localhost:8501`. Mặc định dùng `qwen2.5:3b`
(vừa GPU 4 GB, mỗi câu khoảng 5–10 giây); muốn dùng 7B thì chạy `chay_local.bat qwen2.5:7b`. Thư mục model lấy từ
biến môi trường `OLLAMA_MODELS` (ví dụ `D:\ollama\models` để không đầy ổ C).

`chay_local.bat` bật đủ đồ thị tri thức, agent học tăng cường và đọc nhật ký (`DIACARE_FEATURES=v2,kg,rl,journal`, không bật hybrid);
đồ thị chạy bằng networkx trong bộ nhớ nên không cần Docker. `chay_v3.bat` giữ lại cho quen tay, giờ giống hệt.
Muốn đồ thị đọc từ Neo4j thì dùng `chay_kg.bat` (cần Docker Desktop). Trong Git Bash gọi bằng `./chay_kg.bat`.

**Chat ngay trong terminal** (không mở trình duyệt): bấm đúp `chay_cli.bat`. Mặc định dùng hồ sơ
`docs/samples/hoso_nguy_co_cao.json`; hồ sơ khác: `chay_cli.bat docs\samples\hoso_nguy_co_thap.json`. Trong lúc chat
gõ `/patients`, `/history`, `/stats`, hoặc `q` để thoát.

Lần gọi model đầu tiên sau khi bật máy có thể mất gần một phút vì Ollama khởi tạo GPU; script đã làm bước này trước
khi mở giao diện.

Giao diện web (chạy tay):

```bash
streamlit run src/app.py
```

CLI:

```bash
python src/cli.py --name "An" --profile hoso.json
```

Chế độ demo (LLM giả + embedding băm, không cần Ollama, chỉ để thử giao diện):

```powershell
$env:DIACARE_LLM="demo"; $env:DIACARE_EMBED="hash"; streamlit run src/app.py
```

### Dịch vụ API

```bash
uvicorn api.main:app --app-dir src --port 8000
```

Mở `http://localhost:8000/docs` để xem và thử mọi endpoint. Bấm **Authorize**, nhập email và mật khẩu đã đăng ký.

| Nhóm | Endpoint chính |
|---|---|
| Tài khoản | `POST /auth/register`, `POST /auth/token` (OAuth2 password flow, trả JWT), `GET /me` |
| Hồ sơ | `GET/POST /patients`, `GET/PATCH /patients/{id}`, `GET/DELETE /patients/{id}/memories` |
| Nhật ký | `POST /patients/{id}/readings/glucose`, `.../bp`, `.../weight`; `GET .../readings`, `DELETE .../readings/{rid}`, `GET .../today`, `GET .../summary?days=14`, `GET/PUT/DELETE .../targets` (mục tiêu riêng do bác sĩ đặt) |
| Xét nghiệm | `GET/POST /patients/{id}/labs` (gõ chữ), `POST .../labs/file` (ảnh, PDF; tối đa 10 MB) |
| Tái khám | `GET/PUT .../appointment`, `GET/POST .../questions`, `POST .../questions/{qid}/done`, `GET .../visit-report.pdf` |
| Tư vấn | `POST /patients/{id}/chat` (JSON, hoặc `"stream": true` để nhận luồng SSE), `GET .../sessions`, `GET .../sessions/{sid}/messages`, `POST /feedback/{event_id}` (👍/👎 cho agent RL) |
| Trợ lý chủ động hỏi | `POST .../checkin/open` (mở lời mỗi ngày một lần), `.../checkin/reply` (`handled=false` thì gửi câu cho `/chat`; có `card` thì hiện thẻ xác nhận), `.../checkin/save`, `.../checkin/cancel` |
| Bữa ăn | `GET /meals/dishes`, `POST /meals/scan` (ảnh -> Calo Khay, chưa lưu), `POST .../meals/estimate`, `GET/POST .../meals`, `DELETE .../meals/{mid}` |
| Lời nhắc | `POST .../nudge/feedback` (👍/👎 cho lời nhắc Q-learning hôm nay) |

Luồng SSE của `/chat` gửi lần lượt các sự kiện:

- `session`: mã phiên.
- `step`: từng agent vừa chạy xong.
- `token`: phần chữ mới, đã qua bộ lọc an toàn.
- `done`: kết quả cuối. Giao diện phải thay phần chữ đang hiện bằng `answer`, vì Rules có thể sửa bản nháp: bỏ câu
  khuyên đổi thuốc (giữ phần còn lại), hoặc thêm lời nhắc "chỉ điều chỉnh liều theo bác sĩ".

Bảo mật:

- Mật khẩu băm bằng scrypt.
- Token là JWT HS256, hạn 7 ngày. Khoá ký lấy từ `DIACARE_API_SECRET`; nếu không đặt, hệ tự sinh một lần vào
  `data/api_secret.key` (không lên git).
- Mỗi tài khoản chỉ thấy hồ sơ của mình. Tài nguyên của người khác trả 404.
- CORS chỉ mở cho các origin trong `DIACARE_CORS` (mặc định `http://localhost:3000`).
- Chống dò mật khẩu: sai 5 lần cho một email, hoặc 30 lần từ một địa chỉ IP, trong 15 phút thì trả 429 kèm
  `Retry-After` (như nhau dù email có tài khoản hay không); mỗi IP tạo tối đa 20 tài khoản mỗi giờ. Không khoá cứng
  tài khoản. Bộ đếm nằm trong tiến trình API (đúng khi chạy một worker, như Dockerfile).
- Tệp tải lên: tối đa 10 MB; PDF xét nghiệm tối đa 10 trang; ảnh tối đa 50 triệu điểm ảnh, kiểm tra từ phần đầu tệp
  trước khi giải nén (chặn "bom giải nén": PNG vài KB nhưng giải nén ra hàng GB); trang PDF scan được kết xuất tối đa
  12 triệu điểm ảnh. Vượt giới hạn trả 413.

Cách chạy:

- Phần AI nặng (Predictor, Retriever, LLM, KG) dựng một lần khi khởi động.
- Cơ sở dữ liệu: PostgreSQL khi đặt `DIACARE_DATABASE_URL=postgresql://...` (Docker Compose đặt sẵn), nếu không thì
  SQLite (`DIACARE_DB`, chế độ WAL). Mỗi request mở một kết nối riêng.
- Nhiều người hỏi cùng lúc thì chạy song song, tối đa `DIACARE_CHAT_CONCURRENCY` lượt (mặc định 4). Quá số đó thì chờ
  tối đa `DIACARE_CHAT_QUEUE_SECONDS` (120 giây) rồi trả 503 kèm `Retry-After`. Ollama tự xếp hàng các câu gửi tới.
  Hai câu trong cùng một phiên chạy lần lượt để giữ đúng lịch sử và thứ tự tin nhắn. Phản hồi 👍/👎 sửa mô hình RL
  dưới một khoá riêng; với PostgreSQL đó là advisory lock, đúng cả khi chạy nhiều tiến trình.
- Chat có hai chế độ: `stream=false` trả JSON khi xong; `stream=true` trả luồng SSE (`step`, `token`, `done`), giao
  diện web dùng chế độ này để chữ hiện dần.

### Giao diện web (Next.js)

Trong `web/` có giao diện cho người bệnh, ưu tiên màn hình điện thoại, gọi vào dịch vụ API ở trên. Gồm các trang:

- Đăng nhập, đăng ký.
- Tạo hồ sơ theo dõi. Một tài khoản theo dõi được cho nhiều người thân.
- **Hôm nay**: cảnh báo, ghi đường huyết, số liệu và biểu đồ 14 ngày, cài giờ nhắc đo.
  Nhắc đo là thông báo của trình duyệt: chọn tối đa 4 mốc giờ, tới giờ mà 2 giờ trước đó chưa có số đo thì nhắc.
  Chỉ hoạt động khi DiaCare đang mở trên trình duyệt (tab nền cũng được); chưa phải thông báo đẩy.
- **Nhật ký**: đường huyết; huyết áp và cân nặng; xét nghiệm, có chụp ảnh phiếu.
- **Bữa ăn**: chụp ảnh khay cơm (trên điện thoại mở thẳng camera sau) hoặc tự nhập món, kiểm tra từng món và gram,
  xem khoảng tinh bột, lưu; bảng các bữa 7 ngày kèm đường huyết sau ăn.
- **Tư vấn**: chữ hiện dần qua SSE, có nút 👍/👎 cho agent RL. Người đã chẩn đoán được trợ lý hỏi trước mỗi ngày một
  lần; số đo trong câu trả lời hiện thẻ xác nhận.
- **Tái khám**: lịch hẹn, mục tiêu đường huyết riêng do bác sĩ đặt, câu hỏi cho bác sĩ, tải PDF.
  Mặc định so với mục tiêu chung ADA 2024 (trước ăn 4,4–7,2; sau ăn dưới 10,0 mmol/L). Nhập mục tiêu riêng thì mọi
  thống kê, biểu đồ, PDF và trợ lý Tư vấn đều dùng mục tiêu đó. Ngưỡng hạ đường huyết (3,9) không đổi.

```bash
uvicorn api.main:app --app-dir src --port 8000   # cửa sổ 1: API (mất khoảng 30 giây để nạp mô hình)
cd web
npm install                                       # lần đầu, khoảng 370 MB
npm run dev                                       # cửa sổ 2: http://localhost:3000
```

API đặt ở cổng khác thì chép `web/.env.example` thành `web/.env.local` và sửa `NEXT_PUBLIC_API_URL`. Phiên bản dùng:
Next.js 16.4, React 19.3, TypeScript 5.9. Ngoài các gói đó không cài thêm thư viện nào; biểu đồ tự vẽ bằng SVG.
Token đăng nhập lưu trong `localStorage` của trình duyệt. Cách này đủ cho đồ án; bản chạy thật nên chuyển sang
cookie `HttpOnly`.

### Chạy bằng Docker Compose

```bash
copy .env.example .env           # lần đầu: đặt POSTGRES_PASSWORD (chữ, số, - và _)
docker compose up --build        # web http://localhost:3000, API http://localhost:8000/docs
```

Bốn dịch vụ: `db` (PostgreSQL 16, không mở cổng ra ngoài mạng Docker), `ollama` (tự tải `qwen2.5:3b`, khoảng 1,9 GB
ở lần đầu), `api`, `web`. Dữ liệu người dùng nằm trong volume `pg-data`; khoá mã hoá DB và khoá ký token nằm trong
volume `diacare-data`. Mất `diacare-data` thì không đọc lại được các cột đã mã hoá, nên phải sao lưu cả hai.
`docker compose down` không xoá volume, `docker compose down -v` mới xoá.

- Đổi model: `DIACARE_MODEL=qwen2.5:7b docker compose up --build`.
- Chạy thử không cần mô hình ngôn ngữ: `DIACARE_LLM=demo DIACARE_EMBED=hash docker compose up -d --build --no-deps db api web`
  (`--no-deps` để Compose không kéo ảnh Ollama 3,2 GB; vẫn cần tệp `.env` có `POSTGRES_PASSWORD`). Ở V4.6 (còn dùng
  SQLite) đã chạy thử: ảnh `api` 2,2 GB, `web` 755 MB, `/health`, web, chat demo và mã hoá DB trong volume đều chạy.
  Từ V4.7 có thêm dịch vụ `db`; lệnh này và dịch vụ Ollama trong Compose chưa được chạy thử.
- Có GPU NVIDIA: bỏ dấu `#` ở khối `deploy` của dịch vụ `ollama`.
- Khoá ký token tự sinh vào volume; muốn tự đặt thì khai báo `DIACARE_API_SECRET` trong tệp `.env`.

Volume `diacare-data` gắn vào `/app/var` (khoá mã hoá DB, khoá ký token), tách khỏi bảng dinh dưỡng trong ảnh.
Volume tạo từ bản trước V4.7 còn tệp `/app/var/diacare.db` (SQLite); từ V4.7 API không đọc tệp đó nữa. Muốn giữ dữ
liệu cũ thì chép tệp ra (`docker compose cp api:/app/var/diacare.db .`) rồi chuyển sang bằng script ở mục dưới.

### Chuyển dữ liệu từ SQLite sang PostgreSQL

Dữ liệu cũ trong `data/diacare.db` (hoặc volume Docker bản trước) chuyển sang bằng:

```bash
python tools/sqlite_to_postgres.py data/diacare.db postgresql://diacare:MẬT_KHẨU@127.0.0.1:5432/diacare --key-dir data
```

Script giữ nguyên id và chép nguyên dữ liệu đã mã hoá, rồi đặt lại bộ đếm id. Nó chép `diacare.db.key` thành
`<key-dir>/diacare_db.key` (tên tệp khoá khi chạy với PostgreSQL) và `api_secret.key`, để dữ liệu và token đăng nhập cũ
vẫn dùng được. Bảng đích đã có dữ liệu thì dừng (thêm `--replace` để chép lại); tệp khoá đích đã có mà khác thì dừng,
không ghi đè. Tệp SQLite không bị sửa. Sau đó chạy API với `DIACARE_DATABASE_URL` và `DIACARE_KEY_DIR` trỏ tới hai chỗ
trên.

Chạy cả bộ test trên PostgreSQL: đặt `DIACARE_TEST_PG_URL=postgresql://...` rồi `python -m pytest`. Mọi `Store` trong
test được chuyển sang một schema riêng; test đọc thẳng tệp SQLite được bỏ qua (xem `tests/conftest.py`).

### MCP server (dùng DiaCare trong Claude Desktop, Claude Code, VS Code...)

`src/diacare/mcp_server.py` mở các công cụ **tất định** của DiaCare theo chuẩn Model Context Protocol qua stdio:
`check_lab` (xét nghiệm so với ADA 2024), `search_guidelines` (tài liệu MedlinePlus/WHO kèm nguồn),
`risk_factor_evidence` (đồ thị tri thức + BRFSS), `food_nutrition` (món Việt, USDA), `tray_carbs` (khay cơm Calo Khay),
`predict_risk` (21 chỉ số BRFSS), và tài liệu `kb/` dưới dạng resource `kb://<tệp>`. Không mở công cụ "tư vấn" (mô hình
bên ngoài sẽ viết lại câu trả lời, bỏ qua lớp Rules) và không mở dữ liệu người bệnh. Giao thức viết bằng thư viện chuẩn,
không cần cài gói `mcp`. Khai báo cho host (ví dụ `claude_desktop_config.json`):

```json
{"mcpServers": {"diacare": {"command": "python", "args": ["-m", "diacare.mcp_server"],
                            "env": {"PYTHONPATH": "C:/DATA/diacare-mas/src"}}}}
```

### Giọng nói

Người dùng nói thay vì gõ. Có hai chỗ dùng:

- **Trang Hôm nay, nút "Nói số đo".** Ví dụ nói "đường huyết lúc đói sáu phẩy tám" hoặc "huyết áp một trăm hai mươi lăm
  trên tám mươi". App hiện chữ nghe được kèm số đo đề xuất, người dùng bấm xác nhận mới lưu. Câu không nói đơn vị như
  "sáu tám" có thể là 68 mg/dL (đang hạ đường huyết) hoặc 6,8 mmol/L, nên app đưa cả hai lựa chọn và không tự đoán.
- **Trang Tư vấn, nút micro.** Chữ nghe được hiện vào ô nhập để sửa trước khi gửi. Nút "Đọc to" đọc câu trả lời bằng
  giọng tiếng Việt có sẵn của máy, và chỉ đọc câu trả lời cuối đã qua Rules, không đọc bản nháp.
- **Streamlit, trò chuyện bằng giọng nói** (V4.9). Bật "🎙️ Trò chuyện bằng giọng nói" ở trang Tư vấn: một nút micro
  to ở giữa. Bấm một lần rồi cứ nói; nói xong (im 0,8 giây) trợ lý tự trả lời, đọc to bằng giọng tiếng Việt
  [Piper](https://github.com/rhasspy/piper) chạy trên máy, rồi nghe tiếp. Bấm khi trợ lý đang nói để ngắt, bấm khi đang
  nghe để dừng. Câu trả lời bằng giọng được dặn ngắn (50–90 chữ). Nói số đo lúc nào cũng hiện thẻ xác nhận ("vừa đo
  đường huyết bảy phẩy hai"); câu hỏi có số đọc bằng chữ ("HbA1c sáu phẩy tám thì sao") được đổi thành số. Ô chat cũng
  có nút micro nhỏ: chữ nghe được hiện ra để sửa trước khi gửi.
- **Streamlit, trả lời trợ lý chủ động hỏi.** Ô ghi âm và nút "Đọc câu hỏi" dưới lời mở đầu (mục Tính năng).
  `chay_local.ps1` trỏ `DIACARE_ASR_MODEL` tới bản PhoWhisper đã tải ở `D:\hf_cache` nếu có, để chạy không cần mạng
  (nạp lần đầu khoảng 26 giây).

Cách làm:

- Trình duyệt tự ghi âm thành WAV 16 kHz, nên máy chủ không cần ffmpeg.
- API nhận dạng bằng [PhoWhisper-small](https://huggingface.co/vinai/PhoWhisper-small) của VinAI (BSD-3), chạy CPU:
  khoảng 2–3 giây cho một câu ngắn, lần đầu mất khoảng 30 giây để nạp mô hình.
- Âm thanh không được lưu; endpoint là `POST /transcribe`.
- Đọc số tiếng Việt nằm trong `src/diacare/speech.py`: "một trăm linh năm", "bảy rưỡi", "sáu phẩy tám".

```bash
# tải mô hình một lần (khoảng 970 MB); đặt HF_HOME để chọn thư mục lưu
HF_HOME=D:/hf_cache python -c "from huggingface_hub import snapshot_download; snapshot_download('vinai/PhoWhisper-small')"
HF_HOME=D:/hf_cache uvicorn api.main:app --app-dir src --port 8000
```

`DIACARE_ASR=demo` thay mô hình bằng bộ nhận dạng giả lập để test.

Giọng đọc Piper (`pip install piper-tts`, đã có trong `requirements.txt`) cần tải giọng một lần (khoảng 61 MB);
`chay_local.ps1` tự đặt `DIACARE_TTS_MODEL` nếu giọng nằm trong `D:\hf_cache`:

```bash
HF_HOME=D:/hf_cache python -c "from huggingface_hub import hf_hub_download as d; [d('rhasspy/piper-voices', 'vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx' + e) for e in ('', '.json')]"
```

Lưu ý khi dùng:

- Micro chỉ dùng được trên `localhost` hoặc HTTPS.
- Giọng đọc phụ thuộc máy. Windows cần thêm giọng Tiếng Việt trong phần Cài đặt; app sẽ báo nếu máy chưa có.
- Gặp tiếng ồn không phải lời nói, Whisper có thể "bịa" ra một câu. Vì vậy mọi số đo nghe được đều phải được xác nhận
  trước khi lưu.

### Dịch vụ nhận diện món Calo Khay (trang Bữa ăn)

Calo Khay cần torch, ultralytics, transformers nên chạy trong môi trường riêng, không cài vào DiaCare. Bấm đúp
**`chay_calo_khay.bat`**: nó chạy backend FastAPI có sẵn của Calo Khay ở `http://127.0.0.1:8010`, dùng SQLite trong
`data/calo_khay/` (không cần MySQL). Đường dẫn mặc định `D:\CVision\Final_Project_Digital_Image_Processing` và
`D:\food-labeling\.venv\Scripts\python.exe`; đổi bằng biến `CALO_KHAY_DIR`, `CALO_KHAY_PY`. Nạp model khoảng 15
giây (chạy offline, DINOv2 đã có trong cache Hugging Face; máy mới lần đầu cần mạng, xoá hai dòng
`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` trong file .bat); mỗi ảnh khoảng 0,4–1 giây trên GPU RTX 3050 Ti. Chưa bật dịch vụ thì trang Bữa ăn báo cách bật, các trang khác
vẫn chạy bình thường.

Bảng tinh bột sinh bằng `python tools/build_carb_table.py`: đọc cột `carb(g)` của Nutrition5k `ingredients_metadata`
(USDA FNDDS), cùng nguồn với cột kcal của Calo Khay. Món không có trong Nutrition5k hoặc chỉ có nguyên liệu chính
(thịt kho, cá kho, gà sốt chua ngọt, giò chả có bột độn, tôm tẩm bột...) có thêm **cận trên** theo tỉ lệ giả định ghi
trong script (nước kho ngọt 10%, bột độn 10%...), vì với người tiểu đường ước thấp là chiều nguy hiểm. Mục
"spring rolls" của Nutrition5k chỉ 4% carb (như cuốn tươi) nên nem rán dùng "egg rolls" (29%). 20 món nhập tay
(`EXTRA` trong script) tính theo cùng cách, tỉ lệ khẩu phần điển hình ghi ở cột `note`; kcal của chúng tính từ cột
`cal/g` của Nutrition5k (45 lớp Calo Khay vẫn lấy kcal từ bảng của Calo Khay).

### Chạy trên Kaggle (GPU miễn phí)

`kaggle/build_app_notebook.py` đóng gói code thành notebook. Notebook cài Ollama, tải `qwen2.5:7b`, chạy Streamlit và
mở đường hầm Cloudflare (`*.trycloudflare.com`), giữ phiên khoảng 6 giờ. Trên Kaggle: bật GPU và Internet, bấm
**Run All**, rồi mở link mà notebook in ra.

```bash
python kaggle/build_app_notebook.py
kaggle kernels push -p kaggle/app_kernel
```

`kaggle/build_notebook.py` tạo notebook benchmark tương tự.

### Chỉ chạy model 7B trên Kaggle, giao diện ở máy mình

Máy yếu không chạy nổi `qwen2.5:7b` thì để Kaggle chạy model, còn giao diện, dữ liệu và nhật ký vẫn ở máy mình.
Notebook (`kaggle/build_ollama_notebook.py`) chỉ cài Ollama, tải `qwen2.5:7b` và mở Cloudflare quick tunnel. Tunnel trỏ
vào một cổng chặn (`src/diacare/ollama_gate.py`), không trỏ thẳng vào Ollama. Cổng chặn chỉ cho qua yêu cầu có header
`Authorization: Bearer <token>` đúng, và chỉ các đường `/api/chat`, `/api/tags`, `/api/version`, `/gate/stop`: người có
link mà không có token không dùng được GPU, cũng không kéo hay xoá được model.

**Tự động, không mở web Kaggle** (cần Kaggle CLI đã đăng nhập, xem `kaggle/save_token.ps1`): bấm đúp
**`chay_kaggle.bat`**. Bên trong là `python tools/kaggle_llm.py up`:

1. Tạo token một lần, lưu ở `kaggle/ollama_token.local` (gitignore), nhúng vào notebook riêng tư.
2. `kaggle kernels push`: Kaggle chạy notebook ở chế độ Batch trên GPU T4, bản này phục vụ luôn trong Batch.
3. Đợi hàng đợi GPU, đọc `kaggle kernels logs -f` tới khi notebook in link `*.trycloudflare.com`, gọi thử bằng token,
   lưu phiên ở `kaggle/ollama_session.local.json`.
4. Mở DiaCare với `qwen2.5:7b` qua link đó. Tắt giao diện bằng Ctrl+C thì script gọi `kaggle_llm.py down`, notebook
   tự thoát và trả GPU.

Thời gian bật phụ thuộc hàng đợi GPU của Kaggle: lần thử ngày 24/11/2026 có lần chạy ngay (sẵn sàng sau 3,8 phút), có lần phải xếp hàng 19 phút (sẵn sàng sau 23 phút), nên hãy bật trước khi demo. Qua tunnel, câu trả lời vẫn hiện dần từng đoạn (đã đo: khoảng cách lớn nhất giữa hai đoạn 0,15 s); câu đầu sau khi bật chờ khoảng 12 s, các câu sau bắt đầu hiện sau khoảng 1 s. Notebook cũng tự tắt khi 30 phút không có yêu cầu nào (`--idle`) hoặc sau 4 giờ, nên đóng cửa sổ hay quên tắt cũng
không tốn mãi giờ GPU (Kaggle cho 30 giờ/tuần). Các lệnh lẻ:

```bash
python tools/kaggle_llm.py up       # bật (dùng lại phiên đang chạy nếu còn)
python tools/kaggle_llm.py status   # trạng thái notebook và thử gọi
python tools/kaggle_llm.py down     # tắt
```

**Bằng tay trên web:** `python kaggle/build_ollama_notebook.py`, `kaggle kernels push -p kaggle/ollama_kernel`, mở
notebook, Edit, bật GPU T4 và Internet, Run All. Notebook in link và token; ở máy mình chạy
`chay_local.ps1 -Kaggle <link>` và dán token.

**Khi đường hầm treo hoặc notebook đã tắt** (V4.9): có token thì DiaCare chỉ chờ 90 giây (Ollama trên máy: 300 giây;
đổi bằng `DIACARE_OLLAMA_TIMEOUT`), rồi trả lời người dùng bằng một câu nói rõ chuyện gì xảy ra thay cho "Hệ thống
đang gặp sự cố": máy chủ mô hình không trả lời trong 90 giây, hay không kết nối được (mã 502/530 của Cloudflare khi
notebook đã tắt), kèm cách xử lý (chạy lại `chay_kaggle.bat` hoặc chuyển sang mô hình trên máy). Benchmark 7B có một
lượt treo hết 300 giây, trong khi lượt bình thường mất khoảng 7 giây.

Mỗi lượt hỏi, lời nhắn gửi cho model (gồm tài liệu và hồ sơ đã tóm tắt trong prompt) đi qua Internet tới Kaggle, nên
đây là cách cho demo, không dùng cho dữ liệu người bệnh thật.

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `DIACARE_LLM` | `ollama` | `ollama` hoặc `demo` |
| `DIACARE_MODEL` | `qwen2.5:3b` | tên model Ollama |
| `DIACARE_NUM_CTX` | `4096` | cửa sổ context gửi cho Ollama |
| `DIACARE_OLLAMA_URL` | `http://localhost:11434` | địa chỉ Ollama khi không chạy cùng máy (Docker Compose đặt `http://ollama:11434`) |
| `DIACARE_CALO_URL` | `http://127.0.0.1:8010` | địa chỉ dịch vụ nhận diện món Calo Khay (trang Bữa ăn) |
| `DIACARE_OLLAMA_TOKEN` | (trống) | token gửi kèm mỗi yêu cầu (`Authorization: Bearer`), cho Ollama trên Kaggle qua cổng chặn |
| `DIACARE_OLLAMA_TIMEOUT` | `300` (máy), `90` (có token) | số giây chờ mỗi lần đọc từ Ollama trước khi báo lỗi cho người dùng |
| `DIACARE_EMBED` | `sbert` | `sbert` hoặc `hash` (demo) |
| `DIACARE_MIN_SCORE` | `0.2` (sbert), `0` (hash) | ngưỡng điểm truy xuất |
| `DIACARE_KB` | `kb/` | thư mục tài liệu tri thức |
| `DIACARE_DATABASE_URL` | (trống) | `postgresql://người_dùng:mật_khẩu@máy:5432/tên_db`; có giá trị thì API và Streamlit dùng PostgreSQL thay cho `DIACARE_DB` |
| `DIACARE_DB` | `data/diacare.db` | file SQLite (khi không đặt `DIACARE_DATABASE_URL`) |
| `DIACARE_KEY_DIR` | `data/` | thư mục khoá mã hoá DB (`diacare_db.key`) và khoá ký token khi dùng PostgreSQL |
| `DIACARE_CHAT_CONCURRENCY` | `4` | số lượt tư vấn API chạy cùng lúc |
| `DIACARE_CHAT_QUEUE_SECONDS` | `120` | thời gian chờ suất tư vấn trước khi trả 503 |
| `DIACARE_LOG` | `logs/runs.jsonl` | log JSONL từng lượt chạy (không ghi nguyên văn câu hỏi, chỉ ghi độ dài) |
| `DIACARE_LOG_QUESTIONS` | tắt | `1`: ghi cả câu hỏi vào log JSONL, chỉ dùng khi chạy câu hỏi mẫu |
| `DIACARE_FEATURES` | `default` | `default` = nutrition, memory, labs, kg, rl, journal; `v2` = nutrition, memory, labs (nhãn benchmark cũ, không KG, không RL); `all`/`v3` = thêm hybrid; `v1` = tắt hết; hoặc danh sách `nutrition,memory,labs,hybrid,kg,rl,journal` |
| `DIACARE_KG` | `memory` | `memory` (networkx trong bộ nhớ) hoặc `neo4j` (đọc từ Neo4j trên Docker) |
| `DIACARE_PARALLEL` | `1` | `0`: chạy bốn agent Predictor, Retriever, Graph, Nutrition tuần tự thay vì song song |
| `DIACARE_DB_KEY` | tự sinh vào `<DB>.key` (PostgreSQL: `<DIACARE_KEY_DIR>/diacare_db.key`) | khoá Fernet mã hoá các cột chữ |
| `DIACARE_DB_ENCRYPT` | `1` | `0`: không mã hoá (vẫn đọc được dòng chữ thường cũ) |
| `DIACARE_DEV` | (tắt) | `1`: giao diện Streamlit mở sẵn chế độ nhà phát triển |
| `DIACARE_API_SECRET` | tự sinh vào `data/api_secret.key` | khoá ký token của API, ít nhất 32 ký tự |
| `DIACARE_CORS` | `http://localhost:3000` | các origin được gọi API, cách nhau bằng dấu phẩy |
| `DIACARE_ASR` | `phowhisper` | `demo`: nhận dạng giọng giả lập (test) |
| `DIACARE_ASR_MODEL` | `vinai/PhoWhisper-small` | mô hình nhận dạng giọng (Hugging Face) |

## Đồ thị tri thức (Knowledge Graph)

`src/diacare/kg.py` dựng một đồ thị tri thức về tiểu đường từ chính dữ liệu của dự án. Cạnh **có kiểu và tách
theo nguồn gốc**, vì ba nguồn có độ tin cậy khác nhau:

| Loại cạnh | Nối | Nguồn | Độ tin cậy |
|---|---|---|---|
| `indicates` | LabTest → Condition | ngưỡng ADA 2024 (`labs.THRESHOLDS`) | tra cứu |
| `requires` | Symptom → Action | luật chuyển khám, cấp cứu (`rules.py`) | tra cứu |
| `contains` | Food → Nutrient | USDA FoodData Central (`vn_foods.json`) | tra cứu |
| `associated_with` | RiskFactor → Condition | BRFSS 2015, odds ratio khi xét riêng và khi hiệu chỉnh 21 chỉ số | đo được, là liên hệ chứ không phải nhân quả |
| `claims_risk` | RiskFactor → Condition | câu trong `kb/` (MedlinePlus, WHO) | lời khẳng định, đem đối chiếu |

Mỗi cạnh `claims_risk` được đối chiếu với cạnh `associated_with` cùng yếu tố: **nhất quán**, **mâu thuẫn**,
**không đủ bằng chứng**, hoặc **không kiểm chứng được** khi BRFSS không đo yếu tố đó. Trên `kb/` hiện tại:
28 khẳng định, 15 nhất quán, 13 không kiểm chứng được (tiền sử gia đình, chủng tộc, thai kỳ, PCOS...),
0 mâu thuẫn. Hai điểm dữ liệu cho thấy mà tài liệu không nói: hút thuốc có OR 1,42 khi xét riêng nhưng 0,99
khi hiệu chỉnh; vận động có OR 0,49 khi xét riêng nhưng 0,95 khi hiệu chỉnh.

```bash
python tools/build_kg_stats.py     # tính lại kb/graph/brfss_associations.json từ CSV BRFSS (không tự tải)
python tools/kg_neo4j.py           # nạp vào Neo4j trong Docker, chạy 6 truy vấn Cypher
```

`kg_neo4j.py` dùng container riêng `diacare-neo4j` trên cổng **7475** (Browser) và **7688** (bolt), mật khẩu
sinh ngẫu nhiên lưu trong `neo4j.local.json` (đã gitignore). Dữ liệu Neo4j được gắn ra thư mục
**`neo4j_data/`** ở gốc repo (đã gitignore): tệp lưu nút, cạnh nằm ở `neo4j_data/data/databases/neo4j/`.

**Graph agent** đọc đồ thị khi trả lời, đứng sau Retriever: nối câu hỏi tiếng Việt vào nút yếu tố nguy cơ rồi
đưa cho LLM một khối "tài liệu nói gì, dữ liệu BRFSS đo được gì, PrimeKG có bao nhiêu gen chung" (tối đa 300 token).
Graph agent **bật mặc định** (`DIACARE_FEATURES` không đặt = `default`); nhãn `v2` vẫn là bản không KG để so sánh
`v2` với `v2,kg` trên benchmark. Giao diện có khung "Đồ thị tri thức đã dùng" cho từng câu trả lời. `DIACARE_KG=neo4j` cho agent
truy vấn Neo4j bằng Cypher; mặc định (`memory`) hoặc khi không kết nối được Neo4j thì dùng networkx trong bộ nhớ,
nên test, chế độ demo và Kaggle không cần Docker. Một cú bấm: **`chay_kg.bat`** bật Neo4j, nạp đồ thị, mở giao
diện với Graph agent đọc từ Neo4j. Hướng dẫn trình bày và bản đồ code: [`docs/kg_demo.md`](docs/kg_demo.md).

## Học tăng cường (Reinforcement Learning)

Hai agent, cùng 6 trọng tâm an toàn (`urgent_eval`, `glycemic_followup`, `weight_diet`, `physical_activity`,
`cardio_control`, `preventive_habit`):

### Coach Q-learning: lời nhắc mỗi ngày (`src/diacare/coach.py`)

Mỗi sáng, người đã chẩn đoán thấy một "Lời nhắc hôm nay" ở tab Hôm nay. Lời nhắc hôm nay làm đổi hành vi ngày mai
(có đo không, chỉ số ra sao), nên đây là bài toán nhiều bước, có $s_t \to s_{t+1}$ thật.

- Trạng thái (36 ô) tính từ nhật ký 3 ngày qua bằng các hàm của `diacare.journal`: đo đều (ít / vừa / đều) × kiểm soát
  (chưa đo / đạt / cao / nguy hiểm) × nhóm lời nhắc hôm qua.
- Phần thưởng tính từ nhật ký của chính ngày đó, **không cần người dùng bấm gì**: có đo +1, bỏ đo −1, cộng điểm số đo
  (đạt +0,5, cao −0,3, rất cao −1, hạ đường huyết −1,5 / −1,9), nhắc lại đúng lời hôm qua −0,3. Bỏ đo luôn tệ hơn mọi
  kết quả đo, để agent không học cách làm người bệnh bớt đo.
- $Q(s,a) \leftarrow Q(s,a) + \alpha[r + \gamma \max_{a'} Q(s',a') - Q(s,a)]$, $\alpha = 0{,}1$, $\gamma = 0{,}9$, học ngoài
  chính sách từ các ngày đã ghi.
- An toàn: hôm qua có hạ đường huyết hoặc ≥ 250 mg/dL thì luôn "khám sớm"; ngoài lúc đó agent không được chọn "khám sớm".
- Dữ liệu: **30 người bệnh mô phỏng**, 14–28 ngày mỗi người, 599 ngày (`data/rl_demo/`, `python tools/make_rl_demo_data.py --db`).
  Trên 200 người bệnh mô phỏng mới, tổng thưởng TB mỗi người: Q-learning 1,99, luật cố định −0,34, ngẫu nhiên −2,26;
  Q-learning hơn luật cố định +2,33 [1,01; 3,65] nhưng **chưa hơn bandit $\gamma = 0$ một cách có ý nghĩa** (khoảng tin cậy chứa 0) (+0,83 [−0,59; 2,26]).
  Chi tiết và cách đọc: `docs/results/2026-11-24_q_learning/`.
- **Học tiếp từ nhật ký trong ứng dụng.** Bảng Q học sẵn chỉ là điểm xuất phát. Mỗi khi mở tab Hôm nay, agent học tiếp từ những ngày đã kết thúc của người đó mà chưa học (`learn_from_journal`): phần thưởng tính từ nhật ký của ngày đó, trạng thái kế tiếp là trạng thái sáng hôm sau, rồi một bước $Q(s,a) \leftarrow Q(s,a) + \alpha[r + \gamma \max_{a'} Q(s',a') - Q(s,a)]$, $\alpha = 0{,}1$. Mỗi ngày chỉ học một lần (cột `learned_reward` của bảng `coach_events`), dưới khoá để hai phiên mở cùng lúc không học trùng; bảng Q đã học tiếp lưu ở bảng `coach_model`, dùng chung cho mọi người bệnh. Trong DB demo, ngày theo dõi cuối (23/11) của mỗi người bệnh mẫu không dùng để huấn luyện sẵn (bảng Q học sẵn từ 569/599 ngày) mà để dành: mở tab Hôm nay của một người là agent học ngày đó ngay, và trang Thống kê tăng số "Ngày học tiếp từ nhật ký". Chưa có người dùng thật nào, nên bảng Q hiện vẫn chủ yếu là học từ dữ liệu mô phỏng.
- **👍/👎 cho lời nhắc** (tab Hôm nay của Streamlit, trang Hôm nay của web, API `POST .../nudge/feedback`): phần
  thưởng phụ ±0,3 cộng vào phần thưởng từ nhật ký khi agent học ngày đó. Nhỏ hơn khoảng cách có đo / bỏ đo (2,0), nên
  một cú 👎 không dạy agent rằng thà bỏ đo còn hơn; không bấm thì agent vẫn học như cũ.

### Bandit trọng tâm chat (`src/diacare/rl.py`)

Trong khung chat, `RLAgent` chọn 1 trong 6 trọng tâm và đưa vào ngữ cảnh Advisor (`RL_TOKEN_BUDGET = 120` token).
Mỗi lượt hỏi là một bài toán riêng, không có trạng thái kế tiếp: contextual bandit, tức Q-learning với $\gamma = 0$.

- Trạng thái là vector 13 đặc trưng $\phi(s)$; mỗi hành động có một mô hình ridge tuyến tính $\hat r_a(s) = w_a^\top \phi(s)$.
- Mặt nạ an toàn (xét nghiệm báo động hoặc triệu chứng thì luôn `urgent_eval`), ngoài ra epsilon-greedy $\varepsilon = 0{,}1$
  (`DIACARE_RL_EPSILON`; benchmark đặt 0). Rules vẫn chạy sau cùng.
- Khởi động từ tiên nghiệm lâm sàng trên trạng thái lấy theo phân bố BRFSS (`kb/rl/brfss_state_freq.json`).
- Phản hồi 👍/👎 nay **chỉ hiện ở chế độ nhà phát triển** (người bệnh không chấm "trọng tâm"), nên ở chế độ người dùng
  agent này không học thêm; benchmark chưa đo được tác dụng của nó ($p = 0{,}5$).

```bash
python tools/make_rl_demo_data.py --db   # coach Q-learning: dữ liệu giả, huấn luyện, đánh giá -> models/q_coach.json
python tools/build_rl_states.py          # bandit: phân bố trạng thái từ BRFSS (cần tệp CSV)
python tools/train_rl.py                 # bandit: chính sách khởi động -> models/rl_policy.json
```

## Đánh giá

**Predictor** (tập kiểm tra 20% của từng nguồn; chi tiết ở `docs/results/multisource_eval.json`):

| Tập kiểm tra | AUC cũ (chỉ BRFSS 2015) | AUC mới | Brier cũ | Brier mới | ECE cũ | ECE mới |
|---|---|---|---|---|---|---|
| BRFSS 2015 | 0,831 | 0,829 | 0,174 | 0,097 | 0,234 | 0,004 |
| BRFSS 2023 | 0,817 | 0,818 | 0,173 | 0,102 | 0,224 | 0,004 |
| NHANES | 0,824 | 0,830 | 0,114 | 0,096 | 0,092 | 0,009 |
| NHANES, ĐTĐ chưa chẩn đoán theo xét nghiệm | 0,716 | 0,723 | | | | |

AUC gần như giữ nguyên; xác suất đáng tin hơn hẳn. Ngưỡng mức nguy cơ: thấp < 0,10, cao ≥ 0,30.
Pima (kiểm tra ngoài, 4/21 chỉ số): AUC 0,724 mới, 0,739 cũ. Mô hình triệu chứng UCI 529 (251 người sau khi bỏ 269 dòng trùng): AUC 0,948.

**Benchmark hội thoại** (`eval/cases.json`, hiện có 62 ca thuộc 12 nhóm). Mỗi ca chạy k lần và chấm trên bản nháp thật
của LLM: có trích nguồn đã truy xuất, không khuyên đổi thuốc, nhắc bác sĩ, đúng các cờ.

- **Pass@k**: ca đạt ít nhất 1/k lần.
- **Pass^k**: ca đạt cả k lần, tức độ tin cậy lặp lại.

Lần chạy ablation trên Kaggle (T4, `qwen2.5:7b`, 46 ca × 3 lượt), đã chấm lại bằng bộ chấm đã sửa:

| Cấu hình | Pass@3 | Pass^3 | Đạt từng lượt (Wilson 95%) |
|---|---|---|---|
| v1 | 0.85 | 0.72 | 0.80 [0.72; 0.86] |
| v2 | 0.93 | 0.76 | 0.86 [0.79; 0.91] |
| all | 0.93 | 0.83 | 0.88 [0.82; 0.93] |

Nhóm `memory` tăng từ 0.25 lên 1.00. Mức chung tăng nhưng khoảng tin cậy còn chồng nhau. Phân tích đầy đủ ở
`docs/results/2026-11-05_kaggle_run3_ablation/README.md`. Bản sửa Nutrition agent và 4 ca xét nghiệm mới chưa được đo lại.

Kiểm định McNemar theo ca (`eval/compare.py`, một ca đạt khi đạt cả 3 lượt) cho thấy các mức tăng này **chưa có ý
nghĩa thống kê** với 46 ca: v1 so với v2 $p = 0{,}73$, v2 so với all $p = 0{,}38$, v1 so với all $p = 0{,}27$.
Khác biệt duy nhất có ý nghĩa là qwen2.5:7b so với 14b trên 50 ca: 17 ca chỉ 7b đạt, 3 ca chỉ 14b đạt, $p = 0{,}003$.

**3B trên máy so với 7B trên Kaggle** (V4.9, 50 ca × 3 lượt, `v2,kg,rl`, cùng mã):

| | qwen2.5:3b (máy, RTX 3050 Ti) | qwen2.5:7b (Kaggle T4, qua đường hầm) |
|---|---|---|
| Đạt từng lượt | 127/150 = 0,85 | **145/150 = 0,97** [0,92; 0,99] |
| Pass@3 / Pass^3 | 0,96 / 0,70 | 0,98 / **0,94** |
| Bản nháp có nhãn nguồn | 107/150 | **136/150** |
| Số không có trong ngữ cảnh (Critic) | 20 lượt | 23 lượt |
| Bản nháp xen chữ Hán | 8 | **0** |
| Giây LLM mỗi lượt (trung bình) | 3,0 | 7,3 |

McNemar theo ca: 13 ca chỉ 7B đạt, 1 ca chỉ 3B đạt (một yêu cầu treo do đường hầm), $p = 0{,}0018$. Critic gắn cờ
số không có trong ngữ cảnh ở 23/150 lượt của 7B, nhưng đọc từng câu thì chỉ 5 lượt là số thật sự không có căn cứ (mục
dưới). Chi tiết: `docs/results/2026-11-24_7b_kaggle/`.

**Đồ thị tri thức và RL** (V4.6). Máy cá nhân, `qwen2.5:3b`, kho 14 tài liệu, 50 ca × 3 lượt, bỏ nhóm nhật ký, đã chấm lại:

| Cấu hình | Pass@3 | Pass^3 | Đạt từng lượt [Wilson 95%] |
|---|---|---|---|
| v2 | 0,56 | 0,36 | 0,45 [0,38; 0,53] (68/150) |
| v2,kg | 0,60 | 0,34 | 0,48 [0,40; 0,56] (72/150) |
| v2,kg,rl | 0,56 | 0,38 | 0,47 [0,40; 0,55] (71/150) |

McNemar theo ca: $p = 1{,}0$ (v2 so với v2,kg), $0{,}5$ (v2,kg so với v2,kg,rl), $1{,}0$ (v2 so với v2,kg,rl): không khác biệt. Bộ ca chỉ chạm tới đồ thị ở 7/50 ca, nên chưa đo được tác dụng của đồ thị; với 3B, phần lớn lượt trượt là do không trích nguồn. Lúc chạy, 11 lần Rules chặn câu trong bản nháp đều là câu cảnh báo; Rules đã được sửa để nhận câu cảnh báo theo vị trí cụm từ, và bảng trên là số chấm lại bằng luật đã sửa. Kết quả ở `docs/results/2026-11-16_kg_rl_3b/`.

**Nhắc trích nguồn (V4.7).** Với 3B, 70 trong 79 lượt trượt của `v2,kg,rl` là vì bản nháp không có nhãn nguồn nào.
Advisor được thêm một lời nhắc ở cuối tin nhắn, ngay sau câu hỏi, kèm nhãn nguồn thật của lượt đó; hệ thống không tự
gắn nguồn, mọi nhãn được đếm là do mô hình viết. Cùng cấu hình `v2,kg,rl`, 50 ca × 3 lượt, chấm lại bằng luật hiện tại:

| | Trước | Nhắc trước câu hỏi | Nhắc sau câu hỏi (giữ lại) |
|---|---|---|---|
| Bản nháp tự trích nguồn | 0,19 (27/141) | 0,60 (85/141) | 0,86 (121/141) |
| Đạt từng lượt [Wilson 95%] | 0,47 [0,40; 0,55] | 0,67 [0,59; 0,74] | 0,78 [0,71; 0,84] |
| Pass@3 / Pass^3 | 0,56 / 0,38 | 0,86 / 0,48 | 0,90 / 0,64 |
| Nhóm `medication` (bản nháp) | 18/18 | 13/18 | 9/18 |

McNemar theo ca: trước so với nhắc sau câu hỏi 9 ca chỉ trước đạt, 22 ca chỉ sau đạt, $p = 0{,}029$. Hai điều cần nói
rõ: "có trích nguồn" là bản nháp có ít nhất một nhãn đúng, tính theo câu thì chỉ 7% câu có nhãn (trước 4%); và nhóm
câu về thuốc kém đi ở bản nháp, vì Rules chặn nhầm vài câu cảnh báo ("thảo luận với bác sĩ về việc bỏ thuốc") và mô
hình hay chép lại câu hỏi. Câu trả lời cuối vẫn an toàn: Rules chạy sau cùng, không câu nào khuyên đổi thuốc, cả 18
câu trả lời cuối nhóm này đều nhắc bác sĩ. Đặt lời nhắc trước câu hỏi sửa được một phần nhóm thuốc nhưng mất phần lớn
mức tăng trích nguồn, nên không dùng. Câu ngoài chủ đề vẫn chỉ 2/12. Bộ chấm lại cũng được sửa: trước đây nó không
biết lượt nào có xét nghiệm nên coi `[ada_2024]` là thiếu nguồn (số của `v2,kg,rl` ở bảng trên đổi từ 69 thành
71/150 vì vậy).

Sau đó Rules được sửa để không chặn nhầm câu cảnh báo: gom 15 câu bị chặn trên mọi lần chạy đã lưu, giữ chặn 5 câu
(3 lời khuyên thật, 2 câu lủng củng), cho qua 10 câu cảnh báo bằng khung theo vị trí, mỗi khung có câu đối chứng
vẫn bị chặn; tiện thể sửa một lỗ hổng có sẵn ("không cần thảo luận với bác sĩ ..., cứ bỏ thuốc" từng lọt luật).
Chấm lại: lần đo 16/11 không đổi; bản nhắc sau câu hỏi lên 122/150 (trong mẫu, vì bản sửa được thiết kế từ chính
các bản nháp đó). Một lần chạy mới với code hiện tại (ngoài mẫu) đạt 121/150 = 0,81 [0,74; 0,86], Pass^3 0,66,
bản nháp tự trích nguồn 0,82, nhóm thuốc 14/18, câu ngoài chủ đề 4/12; McNemar so với mốc $p = 0{,}0125$. Rules còn
chặn nhầm 3 câu cảnh báo mới trong lần chạy đó; câu trả lời cuối vẫn an toàn.

**Chặn câu ngoài chủ đề trước khi gọi LLM (V4.7).** Ngay cả sau khi nhắc trích nguồn, `qwen2.5:3b` vẫn trả lời thủ đô
nước Pháp, làm thơ, chỉ cách nấu phở (nhóm `out_of_scope` 4/12). `src/diacare/scope.py` thêm một bước tất định
ngay sau bước nhận câu chào: câu bị coi là ngoài chủ đề thì trả câu từ chối soạn sẵn ("nằm ngoài phạm vi của DiaCare",
kèm gợi ý các chủ đề hỗ trợ), không dự đoán nguy cơ, không gọi LLM, gắn cờ `out_of_scope`. Câu xin công thức nấu ăn
không nói gì tới sức khoẻ nhận câu trả lời riêng: không hướng dẫn nấu, nhưng nói được calo, tinh bột của món đó.
Bước này luôn bật, không phụ thuộc cấu hình tính năng, và cố ý nghiêng về cho qua:

- Câu có dấu, chưa có lịch sử hội thoại: ngoài chủ đề khi không có từ nào về sức khoẻ, tiểu đường, ăn uống, vận
  động, không nhắc món ăn nào trong bảng dinh dưỡng.
- Đã có lịch sử hội thoại, hoặc câu gõ không dấu: chỉ từ chối khi có dấu hiệu ngoài chủ đề rõ (làm thơ, giá vàng,
  bóng đá...), vì câu nối tiếp như "Tôi nên làm gì để kiểm soát tốt hơn?" không có từ khoá nào.
- Câu kể triệu chứng hoặc dấu hiệu cấp cứu luôn được cho qua, dùng đúng hàm Rules dùng để gắn lời khuyên đi khám và
  gọi 115 (`mentions_symptom`, `mentions_emergency`). Bản đầu của bước này từ chối nhầm "Dạo này tôi đái nhiều quá",
  "Tôi bị sụt cân nhanh", "Hơi thở có mùi lạ"; đã sửa, và mọi từ trong danh sách triệu chứng, cấp cứu của Rules có test.

Kiểm tra trên một bộ câu riêng, không lấy từ benchmark (`tests/test_scope.py`). Lần chạy đầu: 14/14 câu ngoài chủ đề
và 3/3 câu xin công thức bị từ chối đúng, 1/32 câu trong chủ đề bị từ chối nhầm ("Tôi hay bị chuột rút ở chân về
đêm"). Sau đó danh sách từ được sửa dựa trên chính bộ câu này, nên con số đạt hết hiện tại là trong mẫu. Trên
benchmark, bước này nhận đúng 4 ca ngoài chủ đề và không đụng tới 62 ca còn lại; nhóm `out_of_scope` lên 12/12 là có
sẵn theo cách làm (4 câu đó đã được xem khi thiết kế, và câu từ chối chứa cụm benchmark tìm), nên không tính p. Các ca
khác đi đúng đường cũ, nên không chạy lại benchmark.

**Trả lời ngắn gọn và lọc món dị ứng (V4.7).** 29/150 lượt chạm giới hạn 512 token và bị cắt mất phần cuối; Advisor
được dặn thêm ở dòng cuối tin nhắn "khoảng 150 đến 200 chữ, tối đa 5 ý chính". Lần chạy mới: không lượt nào bị cắt,
token sinh trung bình 258 → 130, mỗi lượt 5,9 → 4,0 giây. Điểm benchmark gần như không đổi: bỏ nhóm ngoài chủ đề,
117 → 119/138 = 0,86 [0,79; 0,91], McNemar $p = 0{,}61$; tính cả 50 ca là 131/150 = 0,87 [0,81; 0,92], Pass^3 0,78,
phần tăng thêm chủ yếu là nhóm ngoài chủ đề. Cái giá: `risk_referral` 11 → 7/12 vì câu trả lời ngắn hay bỏ nhãn nguồn.
Cùng lần đó thêm luật lọc món dị ứng (`src/diacare/allergy.py`, trong Rules): bỏ câu gợi ý chất người dùng đã khai
dị ứng mà không kèm lời tránh, nhắc dị ứng khi câu hỏi về ăn uống mà câu trả lời không nhắc. Trên các bản nháp đã lưu
của ca dị ứng tôm, luật bỏ đúng 3 câu gợi ý tôm thật (hai của 7B, một của 3B ở lần chạy này: "5. Tôm: 100g tôm hấp"),
sau khi sửa hai lần bỏ nhầm câu khuyên tránh. Chi tiết ở `docs/results/2026-11-22_concise_allergy_3b/`. Phát hiện thêm,
chưa sửa: bản nháp đôi khi xen chữ Hán ("32.8克糖"), 0–9 bản nháp mỗi lần chạy kể cả trước các thay đổi này, và
benchmark không bắt lỗi này. Nhóm thuốc còn 4 lượt trượt vì bản nháp không viết chữ "bác sĩ" (câu trả lời cuối vẫn
có). Chi tiết ở `docs/results/2026-11-22_citation_3b/`.

**Câu trả lời giọng tư vấn (V4.8).** Câu trả lời trước đọc như log ("… [medlineplus_diabetic_diet.txt] … [medlineplus_diabetic_diet.txt]") và có ba lời nhắc mẫu chồng ở cuối, lặp lại mọi lượt. Ba thay đổi:
(1) giao diện đổi nhãn nguồn thành chú thích ¹ kèm dòng "Nguồn: MedlinePlus – Chế độ ăn cho người đái tháo đường", lời miễn trừ in nhỏ dưới tin nhắn, dòng trọng tâm RL và 👍/👎 chỉ còn ở chế độ nhà phát triển (`src/diacare/present.py`; chỉ đổi cách hiện, câu trả lời cuối giữ nguyên nên không ảnh hưởng benchmark);
(2) lời nhắc tái khám cho người đã chẩn đoán chỉ nói một lần mỗi phiên, lời nhắc triệu chứng, cấp cứu, hạ đường huyết vẫn nhắc mỗi lần cần;
(3) Advisor được dặn nói như điều dưỡng tư vấn, theo bốn nhịp: trả lời thẳng, giải thích vì sao chỉ bằng con số có trong ngữ cảnh, 2–3 việc cụ thể, khi nào nên đi khám.
Đo lại (3): 131 → 127/150 lượt đạt, McNemar $p = 0{,}42$, tỉ lệ bản nháp có nhãn nguồn giữ nguyên (116 → 113/150), nhưng bản nháp dài hơn (90 → 133 chữ) và số không có trong ngữ cảnh tăng gần gấp đôi (11 → 20 lượt): mô hình 3B vẫn tự ước tính số dù đã dặn. Chi tiết ở `docs/results/2026-11-24_voice_3b/`.

**Số "không có trong ngữ cảnh" là gì (V4.9).** Đọc từng câu chứa số bị Critic gắn cờ ở lần chạy 3B (20 lượt) và 7B
(23 lượt), chia ba nhóm:

| Nhóm | 3B | 7B |
|---|---|---|
| có trong `kb/` nhưng lượt đó không truy hồi tới (150 phút/tuần, HbA1c 5,7 %, 130/180 mg/dL) | 5 | 3 |
| khuyến cáo chuẩn không có trong `kb/` (30 phút vận động mỗi ngày, quy tắc 15 phút khi hạ đường huyết, ngủ 7–9 giờ) | 11 | 15 |
| không có căn cứ hoặc sai (gram, kcal của món; "FPG trên 160 mg/dL thì đi khám ngay"; 58 % gán nhầm cho WHO) | **4** | **5** |

Số thật sự không có căn cứ tập trung ở gram/kcal món ăn và ngưỡng chẩn đoán, nên prompt hệ thống được dặn thêm: chỉ
nêu gram, kcal, đạm, tinh bột của món có trong bảng dinh dưỡng, và chỉ nêu ngưỡng chẩn đoán, tỉ lệ phần trăm khi có
trong tài liệu. Chạy lại 150 lượt (3B): đạt 127 → 124/150 (McNemar theo ca 9 so với 6, $p = 0{,}61$, không khác biệt có
ý nghĩa). Lúc đầu Critic cho thấy số không có căn cứ 4 → 2, nhưng Critic khi đó bỏ sót số dạng khoảng ("45-60 gram"),
số dính chữ ("100g") và số kèm chữ Hán, đúng những dạng mô hình chuyển sang dùng. Sửa Critic rồi chấm lại cả hai lần
chạy theo cùng một cách (`tools/critic_rescore.py`): lượt có số không tìm thấy trong ngữ cảnh 19 → 23/150, gram, kcal
tự đặt cho món 5 → 8 lượt. Vậy lời dặn **không** giảm được số tự đặt; nó vẫn nằm trong prompt, chưa quyết định giữ
hay bỏ.
Chi tiết ở `docs/results/2026-11-24_numfix_3b/`.

**Nhóm ca nhật ký** (12 ca `journal`, mỗi ca gieo sẵn số đo đường huyết, huyết áp, cân nặng, lịch tái khám). Máy cá
nhân, `qwen2.5:3b`, embedding băm, 12 ca × 3 lượt:

| Cấu hình | Pass@3 | Pass^3 | Đạt từng lượt (Wilson 95%) |
|---|---|---|---|
| có agent Journal (`default`) | 0,92 | 0,50 | 0,78 [0,62; 0,88] |
| không Journal (`v2,kg,rl`) | 0,08 | 0,08 | 0,08 [0,03; 0,22] |

6 ca chỉ đạt khi có Journal, 1 ca chỉ đạt khi không có (McNemar theo ca $p = 0{,}125$: với 12 ca thì chưa đạt mức 0,05, dù tỉ lệ đạt từng lượt là 28/36 so với 3/36). Các ca mô hình 3B còn
trượt khi đã có số liệu: quên trích nguồn, không nhắc số ngày tới lịch tái khám, tự đưa mục tiêu huyết áp khác với
nhật ký. Kết quả ở `docs/results/2026-11-15_journal_3b/`.

**Truy hồi tài liệu** (`eval/retrieval_eval.py`). Kho mở từ 5 lên 14 tài liệu ở V4.6 (thêm 9 bài MedlinePlus), bộ câu
hỏi từ 24 lên 34 câu đúng chủ đề (bộ cũ giữ ở `eval/retrieval_cases_v1.json`). Kết quả ở `reports/retrieval_v46/`:

| Kho / bộ câu | Chế độ | recall@1 | recall@4 | MRR |
|---|---|---|---|---|
| 5 tài liệu / 24 câu | dense, ngưỡng 0,2 | 0,708 | 0,917 | 0,785 |
| 14 tài liệu / 34 câu | dense, ngưỡng 0,2 | 0,676 | 0,794 | 0,725 |
| 14 tài liệu / 34 câu | lai RRF | 0,588 | 0,853 | 0,694 |

Kho lớn hơn trả lời được nhiều chủ đề hơn nhưng xếp hạng kém đi vì các tài liệu gần nhau cạnh tranh; bốn câu dùng thuật
ngữ y khoa tiếng Việt không chế độ nào tìm đúng.

**Bộ thử tấn công** (`tests/test_injection.py`, 67 test): 14 câu hỏi cố lái mô hình bị gắn cờ, 10 câu bình thường dễ nhầm
không bị gắn cờ, đoạn tài liệu bị chèn lệnh bị loại, 18 câu của một mô hình đã bị lái (gồm 8 câu cố lách khung cảnh báo) đều bị Rules loại. Ba cách nói vẫn
lọt Rules được ghi thành test `xfail` để báo cáo đúng giới hạn.

```bash
python eval/benchmark.py --models qwen2.5:7b --k 3 --num-ctx 4096
python eval/benchmark.py --category journal --k 3                 # chỉ nhóm ca nhật ký
python eval/rescore.py docs/results/2026-11-05_kaggle_run3_ablation
python eval/compare.py A/results.json B/results.json --rescore    # kiểm định McNemar giữa hai cấu hình
python -m pytest -q
```

## Cấu trúc thư mục

```
src/app.py              giao diện Streamlit
src/journal_ui.py       ba trang Hôm nay, Nhật ký, Tái khám
src/checkin_ui.py       trợ lý chủ động hỏi trên trang Tư vấn (thẻ xác nhận số đo)
src/meal_ui.py          trang Bữa ăn (ảnh khay cơm -> Calo Khay -> xác nhận món -> khoảng tinh bột; hoặc tự nhập món)
src/diacare/mcp_server.py  MCP server (stdio) mở các công cụ tất định của DiaCare
src/api/                dịch vụ FastAPI (main.py) và mật khẩu, token (security.py)
web/                    giao diện Next.js (app/: các trang, lib/api.ts: gọi API và đọc luồng SSE)
src/cli.py              giao diện dòng lệnh
src/train_predictor.py  huấn luyện MLP bản cũ trên BRFSS 2015 (V1)
src/diacare/            các agent (memory, labs, ocr, kg, nutrition, rl, advisor, rules), context, DB, sơ đồ động (flowviz.py)
kb/                     14 tài liệu tri thức (MedlinePlus, WHO) + thống kê đồ thị (kb/graph/brfss_associations.json)
data/nutrition/         bảng dinh dưỡng món Việt (từ USDA FDC), bảng tinh bột 45 lớp Calo Khay + 20 món nhập tay (calo_khay_carb.csv)
tools/                  công cụ tạo thống kê KG (build_kg_stats.py), nạp Neo4j (kg_neo4j.py), huấn luyện RL (train_rl.py),
                        dữ liệu demo Q-learning (make_rl_demo_data.py), bật/tắt 7B trên Kaggle (kaggle_llm.py),
                        bảng tinh bột Calo Khay (build_carb_table.py)
eval/                   bộ ca benchmark, chấm điểm, đánh giá truy xuất
kaggle/                 sinh notebook Kaggle (giao diện, benchmark, chỉ model 7B)
docs/results/           kết quả các lần chạy benchmark
tests/                  test (pytest)
```

## Hạn chế đã biết

- Gợi ý ăn uống chỉ nói "món góp nhiều tinh bột nhất" trong các bữa cao sau ăn, không chứng minh được món đó làm tăng
  đường huyết: gram từ ảnh sai khoảng ±30% (cơm ±50%), và đường huyết sau ăn còn phụ thuộc thuốc, vận động, cả bữa.
  Phần "có thể ăn thêm" chỉ dựa vào bảng tinh bột vì `kb/` chưa có hướng dẫn "đĩa ăn".
- Streamlit chạy lại cả trang mỗi lần bấm: chuyển trang khoảng 0,5 giây (Nhật ký khoảng 1 giây, đo 25/11 trên máy
  phát triển), lần đầu mở mỗi trang trong một tab mới 2–6 giây vì trình duyệt tải phần giao diện. Phía máy chủ đã làm
  sẵn lúc khởi động những việc chỉ chậm ở lần đầu (dự đoán nguy cơ, nạp altair) và nhớ ảnh biểu đồ đường huyết.
  Khởi động app khoảng 1 phút, phần lớn là nạp sentence-transformers.
- Coach Q-learning mới chỉ được huấn luyện và đánh giá trên người bệnh mô phỏng do nhóm tự viết; trên mô phỏng đó Q-learning ($\gamma = 0{,}9$) không hơn bandit ($\gamma = 0$). Chưa thử trên người thật.
- Mô hình vẫn đôi khi đưa số không có căn cứ (phân loại tay trước lời dặn mới: 3B 4/150 lượt, 7B 5/150; chấm lại
  bằng Critic đã sửa thì lời dặn không làm giảm: gram, kcal tự đặt cho món 5 → 8 lượt; chủ yếu gram, kcal của món và
  ngưỡng chẩn đoán); Critic gắn cờ `unsupported_number` nhưng câu sai vẫn hiện cho người dùng. Phần lớn số bị gắn cờ
  là khuyến cáo chuẩn mà `kb/` không có (30 phút vận động, quy tắc 15 phút); thêm một trang khuyến cáo có nguồn vào
  `kb/` sẽ giảm cờ giả nhưng đổi ngữ cảnh của mọi ca benchmark, nên chưa làm.
- Critic không bắt số dạng khoảng ("45-60 gram"), số dính liền chữ ("100g ngũ cốc") hay kèm chữ Hán ("32.8克").
- Bảng tinh bột chỉ có 44 món căng tin Calo Khay nhận diện được và 20 món nhập tay; món khác chưa tính được.
- Mức nguy cơ chỉ tính từ 21 câu hỏi lối sống trong hồ sơ, không dùng xét nghiệm hay triệu chứng (hai thứ này được xét
  riêng bằng cờ). Ba nguồn huấn luyện đều là dữ liệu Mỹ; NHANES thiếu 10/21 chỉ số, BRFSS 2023 thiếu rau quả.
- Luật triệu chứng và lọc thuốc dựa trên chữ tiếng Việt có dấu; câu gõ không dấu có thể không kích hoạt. Ba cách nói
  đổi thuốc đã biết vẫn lọt (động từ đứng sau tên thuốc, từ tiếng Anh ngoài danh sách, chữ bị chèn ký tự).
- Critic chỉ so khớp chuỗi: không phát hiện con số đúng nhưng đặt sai chỗ.
- Câu trả lời giới hạn 512 token (`num_predict`); câu trả lời dài hơn bị cắt về câu trọn vẹn cuối cùng và gắn cờ
  `answer_truncated`, nên phần cuối dự định viết có thể bị mất.
- Benchmark chấm an toàn, trích nguồn và định dạng, không chấm độ đúng y khoa của nội dung.
- Nhắc nhở chỉ hiện khi mở ứng dụng; chưa gửi được thông báo đẩy. Đường huyết gõ trong chat vẫn được lưu vào
  mục xét nghiệm, chưa vào nhật ký, và trợ lý tư vấn chưa đọc nhật ký.
- Với PostgreSQL, mỗi request vẫn mở một kết nối mới (chưa dùng pool kết nối); đủ cho vài chục người dùng cùng lúc.
  Chống dò mật khẩu đếm trong bộ nhớ của một tiến trình; chạy nhiều worker thì giới hạn nhân theo số worker.
- Giới hạn theo IP dùng địa chỉ của kết nối tới API. Đặt sau reverse proxy (hoặc khi Docker chuyển tiếp cổng mà mọi
  kết nối mang cùng một IP) thì mọi người chung một bộ đếm: 30 lần sai của ai đó chặn đăng nhập của tất cả trong 15
  phút. Khi đó cần đọc IP thật từ `X-Forwarded-For` của proxy tin cậy (chưa làm).
- Lượt tư vấn đang chờ suất giữ một luồng của FastAPI tới 120 giây; nhiều người hỏi dồn một lúc có thể làm các
  endpoint khác (kể cả đăng nhập) chậm theo. Giảm `DIACARE_CHAT_QUEUE_SECONDS` nếu gặp.
- PostgreSQL mới được chạy thử với PostgreSQL 16 trong WSL (cả bộ test qua `DIACARE_TEST_PG_URL`); dịch vụ `db`
  trong Docker Compose chưa được chạy thử vì Docker Desktop trên máy phát triển bị lỗi khi khởi động.
- Giao diện Streamlit không có đăng nhập nên chỉ nghe trên `127.0.0.1` (`.streamlit/config.toml`,
  `chay_local.ps1`). Đừng đổi sang `0.0.0.0` khi máy đang ở mạng chung: ai cùng mạng sẽ xem được mọi hồ sơ.
  Muốn cho máy khác vào thì dùng API và giao diện web (có tài khoản).
- Mô hình 3B đôi khi xen chữ Hán vào câu trả lời ("32.8克糖"), 0–9 bản nháp mỗi lần chạy 150 lượt; chưa có bước
  phát hiện hay sửa, và benchmark không chấm lỗi này.
- Lọc món dị ứng dựa trên danh sách chất và từ tránh (`src/diacare/allergy.py`); khi stream, câu bị bỏ vẫn có thể
  thoáng hiện trước khi câu trả lời cuối thay vào.
- Câu ngoài chủ đề được chặn bằng danh sách từ (`src/diacare/scope.py`), không phải bằng hiểu nghĩa: câu ngoài chủ
  đề có từ trùng với từ sức khoẻ ("đường đi", "ca sĩ bao nhiêu tuổi") vẫn tới LLM, và giữa hội thoại hay khi gõ
  không dấu chỉ chặn được câu có dấu hiệu rõ. Thà để lọt còn hơn từ chối nhầm câu về sức khoẻ.

## Nguồn dữ liệu

- CDC BRFSS 2015 Diabetes Health Indicators (UCI Machine Learning Repository, id 891); CDC BRFSS 2023.
- CDC NHANES 2013–2014, 2015–2016, 2017–3/2020.
- Pima Indians Diabetes (NIDDK, OpenML id 37); Early Stage Diabetes Risk Prediction (UCI id 529).
- MedlinePlus (U.S. National Library of Medicine), WHO Diabetes fact sheet: trích để học tập, giữ ghi nguồn.
- USDA FoodData Central.
- Nutrition5k (Thames et al., CVPR 2021), `ingredients_metadata.csv` (USDA FNDDS): carb các món Calo Khay.
- Ngưỡng xét nghiệm: American Diabetes Association, Standards of Care in Diabetes 2024.
