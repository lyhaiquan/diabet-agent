"""Phần thuần Python của giao diện Streamlit (không gọi st.*), để test import được mà không chạy app.py."""
import threading


class SerialStore:
    """Store dùng chung cho mọi phiên Streamlit (st.cache_resource), nhưng mỗi phiên chạy trên một luồng riêng. Một
    kết nối sqlite3 bị hai luồng dùng cùng lúc thì con trỏ của luồng này đọc nhầm kết quả của luồng kia ("IndexError:
    tuple index out of range", "InterfaceError: bad parameter or other API misuse"), gặp khi mở app ở hai tab cùng
    lúc. Lớp này cho mỗi lời gọi phương thức của Store chạy trọn dưới một khoá chung."""

    def __init__(self, store):
        self._store = store
        self._lock = threading.RLock()

    def __getattr__(self, name):
        attr = getattr(self._store, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            with self._lock:
                return attr(*args, **kwargs)
        return call


def chat_parts(raw):
    """Giá trị của st.chat_input -> (chữ, ảnh đầu tiên, ghi âm). Chuỗi khi không có tệp; ChatInputValue khi có."""
    if raw is None:
        return None, None, None
    if isinstance(raw, str):
        return raw, None, None
    files = list(raw.get("files") or [])
    return (raw.get("text") or "").strip() or None, files[0] if files else None, raw.get("audio")


def photo_labs(store, patient_id, photo):
    """Ảnh đính kèm ở ô chat: nếu đọc (OCR) ra chỉ số xét nghiệm thì lưu và trả danh sách đã lưu, không thì None
    (coi là ảnh bữa ăn). Trước đây mọi ảnh đều sang nhận diện món ăn, ảnh phiếu xét nghiệm không được lưu.
    OCR một ảnh khoảng 1 giây trên máy phát triển."""
    from diacare.labs import LabAgent, parse_lab_file
    try:
        results = parse_lab_file(getattr(photo, "name", None) or "anh.png", photo.getvalue())
    except Exception:  # không đọc được chữ: để phần nhận diện món ăn xử lý
        return None
    saved = LabAgent(store).import_results(patient_id, results, source="import") if results else []
    return saved or None
