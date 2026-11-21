"""Mật khẩu và token cho dịch vụ API, chỉ dùng thư viện chuẩn của Python.

- Mật khẩu: scrypt (n=2^14, r=8, p=1), muối ngẫu nhiên 16 byte cho mỗi người; lưu dạng tự mô tả
  "scrypt$n$r$p$muối$băm" để sau này đổi tham số mà không làm hỏng mật khẩu cũ.
- Token: JWT HS256 (RFC 7519). Chỉ chấp nhận đúng alg HS256 (chặn "none"), so chữ ký thời gian hằng,
  bắt buộc có sub và exp.
- Khoá ký: biến DIACARE_API_SECRET, nếu không có thì sinh một lần vào data/api_secret.key (data/ không lên git).
"""
import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from diacare.crypto import restrict_to_owner

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
TOKEN_TTL_SECONDS = 7 * 24 * 3600
MIN_SECRET_BYTES = 32


class TokenError(Exception):
    pass


# ---- chống dò mật khẩu ----

class RateLimiter:
    """Cửa sổ trượt trong bộ nhớ: mỗi khoá được tối đa `limit` lần trong `window` giây.

    Không khoá cứng tài khoản (kẻ xấu có thể dùng việc đó để khoá người khác): hết cửa sổ là thử lại được.
    Bộ đếm nằm trong tiến trình: đúng khi API chạy một worker (Dockerfile chạy uvicorn một tiến trình);
    chạy nhiều worker thì mỗi worker đếm riêng, giới hạn thực tế nhân lên theo số worker."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._hits = {}
        self._lock = threading.Lock()

    def _window(self, key, window, now):
        q = self._hits.setdefault(key, deque())
        while q and q[0] <= now - window:
            q.popleft()
        return q

    def retry_after(self, key, limit, window):
        """Số giây phải chờ nếu khoá đã dùng hết lượt, hoặc 0."""
        with self._lock:
            now = self.clock()
            q = self._window(key, window, now)
            return max(1, math.ceil(q[0] + window - now)) if len(q) >= limit else 0

    def hit(self, key, window):
        with self._lock:
            now = self.clock()
            self._window(key, window, now).append(now)

    def reset(self, key):
        with self._lock:
            self._hits.pop(key, None)


# ---- mật khẩu ----

def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(got.hex(), digest)


# ---- khoá ký ----

def load_secret(path):
    env = os.environ.get("DIACARE_API_SECRET")
    if env:
        secret = env.encode("utf-8")
    else:
        path = Path(path)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        # ai đọc được khoá ký là giả được token của mọi tài khoản: chỉ người dùng chạy API được đọc
        restrict_to_owner(path)
        secret = path.read_text(encoding="utf-8").strip().encode("utf-8")
    if len(secret) < MIN_SECRET_BYTES:
        raise ValueError(f"Khoá ký token phải dài ít nhất {MIN_SECRET_BYTES} byte.")
    return secret


# ---- JWT HS256 ----

def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token(user_id, secret, ttl=TOKEN_TTL_SECONDS, now=None):
    now = int(now if now is not None else time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": str(user_id), "iat": now, "exp": now + int(ttl)},
                              separators=(",", ":")).encode())
    signing = f"{header}.{payload}".encode("ascii")
    return f"{header}.{payload}.{_b64(hmac.new(secret, signing, hashlib.sha256).digest())}"


def decode_token(token, secret, now=None):
    """Trả về user_id (int). Mọi lỗi đều ném TokenError với lý do chung, không lộ chi tiết."""
    try:
        header_b, payload_b, sig_b = token.split(".")
        header = json.loads(_unb64(header_b))
        if header.get("alg") != "HS256":
            raise TokenError("thuật toán không được chấp nhận")
        expected = hmac.new(secret, f"{header_b}.{payload_b}".encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig_b)):
            raise TokenError("chữ ký sai")
        payload = json.loads(_unb64(payload_b))
        exp, sub = int(payload["exp"]), int(payload["sub"])
    except TokenError:
        raise
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise TokenError("token hỏng") from exc
    if exp <= int(now if now is not None else time.time()):
        raise TokenError("token hết hạn")
    return sub
