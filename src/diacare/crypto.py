"""Mã hoá các cột chữ chứa thông tin sức khoẻ trong SQLite (Fernet: AES-128-CBC + HMAC-SHA256).

Phạm vi bảo vệ: ai đó lấy được riêng tệp .db (sao lưu, gửi nhầm, ổ đĩa bị sao chép) thì không đọc được hồ sơ, hội thoại,
trí nhớ. Khoá nằm cạnh tệp DB (hoặc trong biến môi trường), nên KHÔNG bảo vệ khi cả máy chủ bị chiếm quyền.

- Cột được mã hoá chỉ đọc theo id hoặc được so sánh trong Python sau khi giải mã (Fernet có thành phần ngẫu nhiên:
  cùng một chữ mã hoá hai lần ra hai chuỗi khác nhau, nên không dùng được trong WHERE ... = ?).
- Giá trị mã hoá mang tiền tố `enc1:`; dòng cũ chưa mã hoá vẫn đọc được như chữ thường (nâng cấp không cần chuyển DB).
- Số đo (đường huyết, huyết áp, cân nặng, xét nghiệm) giữ dạng số để còn sắp xếp và tính thống kê; không mã hoá.

Khoá: biến DIACARE_DB_KEY (khoá Fernet base64), nếu không có thì sinh một lần vào `<tên DB>.key` cạnh tệp DB.
DB trong bộ nhớ (":memory:") dùng khoá tạm. Tắt mã hoá: DIACARE_DB_ENCRYPT=0.
"""
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc1:"


class FieldCipher:
    def __init__(self, key):
        self._f = Fernet(key)

    def enc(self, text):
        if text is None:
            return None
        return PREFIX + self._f.encrypt(str(text).encode("utf-8")).decode("ascii")

    def dec(self, value):
        if not isinstance(value, str) or not value.startswith(PREFIX):
            return value  # None, số, hoặc dòng cũ chưa mã hoá
        try:
            return self._f.decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("không giải mã được dữ liệu: sai khoá DIACARE_DB_KEY hoặc tệp khoá") from exc


class NoCipher:
    """Không mã hoá (DIACARE_DB_ENCRYPT=0); vẫn đọc được dòng chữ thường."""

    @staticmethod
    def enc(text):
        return text

    @staticmethod
    def dec(value):
        if isinstance(value, str) and value.startswith(PREFIX):
            raise ValueError("DB có dữ liệu đã mã hoá nhưng DIACARE_DB_ENCRYPT=0")
        return value


def key_path(db_path):
    p = Path(str(db_path))
    return p.with_name(p.name + ".key")


def cipher_for(db_path):
    if os.environ.get("DIACARE_DB_ENCRYPT", "1") == "0":
        return NoCipher()
    env = os.environ.get("DIACARE_DB_KEY")
    if env:
        return FieldCipher(env.encode("ascii"))
    if str(db_path) == ":memory:":
        return FieldCipher(Fernet.generate_key())
    kp = key_path(db_path)
    if not kp.exists():
        kp.parent.mkdir(parents=True, exist_ok=True)
        kp.write_bytes(Fernet.generate_key())
        try:
            os.chmod(kp, 0o600)
        except OSError:  # Windows: quyền tệp theo ACL của thư mục người dùng
            pass
    return FieldCipher(kp.read_bytes().strip())
