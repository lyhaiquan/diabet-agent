# Calo Khay trong DiaCare-MAS

Thư mục này là **mã của Calo Khay**, đồ án Xử lý ảnh số của nhóm: nhận diện 44 món căng tin trên ảnh khay cơm
(YOLO26s-seg + DINOv2), ước lượng gram từng món theo diện tích so với đĩa. DiaCare gọi nó qua HTTP
(`POST /api/scan`) cho trang Bữa ăn; xem `src/diacare/meal_scan.py`.

**Nguồn.** Chép ngày 25/11/2026 từ repo `Final_Project_Digital_Image_Processing` (thư mục làm việc ở máy phát triển,
gồm cả các thay đổi chưa commit lên GitHub lúc đó, như đầu phân loại DINOv2 `models/dino_head.npz` mới), để chạy
DiaCare không cần clone thêm repo. Chỉ lấy phần chạy được: `backend/`, `calo_khay/` (pipeline), `models/`, `tools/`,
`examples/`, các tệp requirements và README gốc. Không lấy giao diện riêng của Calo Khay (`frontend/`), phần nghiên
cứu (`research/`), tài liệu (`docs/`) và kết quả chạy thử; các phần đó vẫn ở repo gốc. README.md trong thư mục này là
README gốc của Calo Khay, có nhắc tới các thư mục không được chép.

**Vì sao vẫn chạy riêng.** Calo Khay cần torch, ultralytics, transformers (vài GB), DiaCare thì không. Hai bên chạy
hai tiến trình, hai môi trường Python, nói chuyện qua HTTP ở cổng 8010; Calo Khay tắt thì chỉ trang Bữa ăn báo lỗi.
Mã của Calo Khay không import gì của DiaCare và ngược lại; test của nó (`backend/tests`) không nằm trong bộ test của
DiaCare (`pytest.ini`: `testpaths = tests`).

## Cài môi trường (một lần)

Python 3.10–3.12, cài PyTorch trước (bản GPU nếu có), rồi:

```powershell
cd services\calo_khay
python -m venv .venv
.venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121   # hoặc bản CPU
.venv\Scripts\pip install -r requirements.txt -r requirements-backend.txt
```

`chay_calo_khay.bat` ở thư mục gốc DiaCare tự dùng `services\calo_khay\.venv` nếu có; không thì dùng
`D:\food-labeling\.venv` (máy phát triển), hoặc đường dẫn đặt trong biến `CALO_KHAY_PY`. Lần chạy đầu cần mạng để tải
DINOv2 về cache Hugging Face (xoá hai dòng `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` trong tệp .bat).

## Chạy

Bấm đúp `chay_calo_khay.bat` ở thư mục gốc DiaCare: dịch vụ chạy ở `http://127.0.0.1:8010`, dữ liệu tạm (SQLite, ảnh
quét) ở `data\calo_khay` của DiaCare, không cần MySQL. Đổi cổng bằng `CALO_KHAY_PORT` (khi đó đặt `DIACARE_CALO_URL`
cho DiaCare).
