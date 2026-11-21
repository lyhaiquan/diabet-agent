"""Mã hoá các cột chữ chứa thông tin sức khoẻ trong SQLite (Fernet: AES-128-CBC + HMAC-SHA256).

Phạm vi bảo vệ: ai đó lấy được riêng tệp .db (sao lưu, gửi nhầm, ổ đĩa bị sao chép) thì không đọc được hồ sơ, hội thoại,
trí nhớ. Khoá nằm cạnh tệp DB (hoặc trong biến môi trường), nên KHÔNG bảo vệ khi cả máy chủ bị chiếm quyền.

- Cột được mã hoá chỉ đọc theo id hoặc được so sánh trong Python sau khi giải mã (Fernet có thành phần ngẫu nhiên:
  cùng một chữ mã hoá hai lần ra hai chuỗi khác nhau, nên không dùng được trong WHERE ... = ?).
- Giá trị mã hoá mang tiền tố `enc1:`; dòng cũ chưa mã hoá vẫn đọc được như chữ thường (nâng cấp không cần chuyển DB).
- Số đo (đường huyết, huyết áp, cân nặng, xét nghiệm) giữ dạng số để còn sắp xếp và tính thống kê; không mã hoá.

Khoá: biến DIACARE_DB_KEY (khoá Fernet base64), nếu không có thì sinh một lần vào `<tên DB>.key` cạnh tệp DB.
Với PostgreSQL (DB là URL) tệp khoá là `diacare_db.key` trong thư mục DIACARE_KEY_DIR (mặc định data/), vì URL
không phải đường dẫn tệp (và chứa mật khẩu, không được thành tên tệp). DB trong bộ nhớ (":memory:") dùng khoá tạm.
Tắt mã hoá: DIACARE_DB_ENCRYPT=0.
"""
import getpass
import os
import subprocess
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


def restrict_to_owner(path):
    """Chỉ người dùng đang chạy chương trình đọc/ghi được tệp khoá.

    POSIX: chmod 600. Windows: os.chmod không đổi quyền đọc, nên bỏ quyền thừa kế từ thư mục cha
    (ví dụ C:\\DATA cho cả nhóm Users đọc) và chỉ cấp cho người dùng hiện tại, giống kaggle/save_token.ps1.
    Trả True nếu đặt được quyền. Lỗi không chặn chương trình: khoá vẫn dùng được, chỉ là quyền rộng hơn."""
    path = Path(path)
    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
            return True
        except OSError:
            return False
    user = os.environ.get("USERNAME") or getpass.getuser()
    domain = os.environ.get("USERDOMAIN")
    who = f"{domain}\\{user}" if domain else user
    try:
        proc = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{who}:(R,W)"],
                              capture_output=True, text=True, timeout=15)
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


DEFAULT_KEY_DIR = Path(__file__).resolve().parents[2] / "data"


def _is_url(db_path):
    return str(db_path).startswith(("postgresql://", "postgres://"))


def key_dir(db_path):
    """Thư mục chứa tệp khoá (khoá mã hoá DB, khoá ký token của API): cạnh tệp SQLite, hoặc DIACARE_KEY_DIR."""
    if _is_url(db_path) or str(db_path) == ":memory:":
        return Path(os.environ.get("DIACARE_KEY_DIR") or DEFAULT_KEY_DIR)
    return Path(str(db_path)).parent


def key_path(db_path):
    if _is_url(db_path):
        return key_dir(db_path) / "diacare_db.key"
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
    restrict_to_owner(kp)  # cả với tệp khoá tạo từ bản cũ, khi quyền còn thừa kế từ thư mục
    return FieldCipher(kp.read_bytes().strip())
