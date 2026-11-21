"""Chuyển dữ liệu DiaCare từ tệp SQLite sang PostgreSQL, giữ nguyên id và dữ liệu đã mã hoá.

    python tools/sqlite_to_postgres.py data/diacare.db postgresql://diacare:...@127.0.0.1:5432/diacare --key-dir data

- Tạo bảng trên PostgreSQL nếu chưa có, chép từng bảng, giữ nguyên id, rồi đặt lại bộ đếm id để bản ghi mới
  không trùng id cũ.
- Các cột đã mã hoá được chép nguyên (chưa giải mã), nên PHẢI dùng cùng khoá: script chép `<db>.key` thành
  `<key-dir>/diacare_db.key` (tên tệp khoá khi DB là PostgreSQL), và `api_secret.key` nằm cạnh DB để token đăng nhập cũ
  vẫn dùng được. Nếu tệp đích đã có mà khác nội dung thì dừng, không ghi đè khoá.
- Bảng đích đã có dữ liệu thì dừng (tránh chép hai lần); thêm --replace để xoá dữ liệu cũ trên PostgreSQL trước.
- Không sửa tệp SQLite.
"""
import argparse
import re
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from diacare import pg  # noqa: E402
from diacare.crypto import NoCipher, key_path  # noqa: E402
from diacare.db import _SCHEMA, Store  # noqa: E402

TABLES = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", _SCHEMA)


def _copy_key(src, dst):
    if not src.exists():
        return f"không có {src.name} (bỏ qua)"
    if dst.exists():
        if dst.read_bytes().strip() != src.read_bytes().strip():
            raise SystemExit(f"{dst} đã có và KHÁC {src}: không ghi đè khoá. Kiểm tra lại trước khi chuyển.")
        return f"{dst.name} đã có, giống nhau"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    from diacare.crypto import restrict_to_owner
    restrict_to_owner(dst)
    return f"đã chép {src.name} -> {dst}"


def migrate(sqlite_path, pg_url, key_dir=None, replace=False, log=print):
    sqlite_path = Path(sqlite_path)
    if not sqlite_path.exists():
        raise SystemExit(f"Không thấy {sqlite_path}")
    if not pg.is_url(pg_url):
        raise SystemExit("Đích phải là URL postgresql://...")
    if key_dir is not None:  # khoá trước dữ liệu: lỗi khoá thì chưa chép gì
        key_dir = Path(key_dir)
        log(_copy_key(key_path(sqlite_path), key_dir / "diacare_db.key"))
        log(_copy_key(sqlite_path.parent / "api_secret.key", key_dir / "api_secret.key"))

    Store(pg_url, cipher=NoCipher()).close()  # tạo bảng, không sinh tệp khoá mới
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dst = pg.PgConnection(pg_url)
    counts = {}
    try:
        src_tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        busy = [t for t in TABLES if dst.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]]
        if busy and not replace:
            raise SystemExit(f"PostgreSQL đã có dữ liệu ở bảng {', '.join(busy)}. Thêm --replace để xoá và chép lại.")
        for t in TABLES:
            if replace:
                dst.execute(f"DELETE FROM {t}")
            if t not in src_tables:
                counts[t] = 0
                continue
            cols = [r["name"] for r in src.execute(f"PRAGMA table_info({t})")]
            cols = [c for c in cols if c in dst.columns(t)]
            rows = src.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall()
            if rows:
                marks = ", ".join(["%s"] * len(cols))
                with dst._conn.transaction(), dst._conn.cursor() as cur:
                    cur.executemany(f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({marks})",
                                    [tuple(r) for r in rows])
            if "id" in cols and t != "rl_model":
                dst.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'),"
                            f" (SELECT COALESCE(MAX(id), 0) + 1 FROM {t}), false)")
            counts[t] = len(rows)
    finally:
        src.close()
        dst.close()
    copied = ", ".join(f"{t} {n}" for t, n in counts.items() if n)
    log(f"Đã chép: {copied}" if copied else "SQLite không có dòng nào để chép.")
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sqlite_path")
    ap.add_argument("pg_url")
    ap.add_argument("--key-dir", help="thư mục khoá khi chạy với PostgreSQL (DIACARE_KEY_DIR); bỏ trống = không chép khoá")
    ap.add_argument("--replace", action="store_true", help="xoá dữ liệu đang có trên PostgreSQL trước khi chép")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # console Windows (cp1252) không in được tiếng Việt
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    migrate(args.sqlite_path, args.pg_url, args.key_dir, args.replace)
    print(f"Xong. Chạy API với DIACARE_DATABASE_URL={pg.redact(args.pg_url)}"
          + (f" và DIACARE_KEY_DIR={args.key_dir}" if args.key_dir else ""))


if __name__ == "__main__":
    main()
