"""Chạy cả bộ test trên PostgreSQL thay cho SQLite.

    $env:DIACARE_TEST_PG_URL = "postgresql://diacare:...@localhost:55432/diacare_test"; python -m pytest

Khi biến này có giá trị, mọi Store(tệp SQLite hoặc ":memory:") trong test được chuyển sang một schema PostgreSQL
riêng (cùng tệp thì cùng schema, nên test mở lại DB vẫn thấy dữ liệu cũ). Tệp khoá mã hoá vẫn nằm cạnh đường dẫn
tệp gốc, như với SQLite. Test đọc thẳng tệp SQLite (sqlite3.connect) được đánh dấu `sqlite_only` và bị bỏ qua.
"""
import os
import uuid

import pytest

PG_URL = os.environ.get("DIACARE_TEST_PG_URL")


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch):
    """Máy đang đặt DIACARE_DATABASE_URL (PostgreSQL thật) thì test không được ghi vào đó."""
    for name in ("DIACARE_DATABASE_URL", "DIACARE_KEY_DIR"):
        monkeypatch.delenv(name, raising=False)


def pytest_configure(config):
    config.addinivalue_line("markers", "sqlite_only: test đọc/ghi thẳng tệp SQLite, bỏ qua khi chạy trên PostgreSQL")


def pytest_collection_modifyitems(config, items):
    if PG_URL:
        skip = pytest.mark.skip(reason="đọc thẳng tệp SQLite; không áp dụng khi chạy trên PostgreSQL")
        for item in items:
            if "sqlite_only" in item.keywords:
                item.add_marker(skip)


if PG_URL:
    import psycopg

    from diacare import pg
    from diacare.crypto import cipher_for
    from diacare.db import Store

    def _with_schema(url, schema):
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}options=-csearch_path%3D{schema}"

    @pytest.fixture(autouse=True)
    def _postgres_backend(monkeypatch):
        schemas = {}
        admin = psycopg.connect(PG_URL, autocommit=True)
        original = Store.__init__

        def init(self, path=":memory:", *args, **kwargs):
            if not pg.is_url(path):
                key = f"mem-{uuid.uuid4().hex}" if str(path) == ":memory:" else str(path)
                if key not in schemas:
                    schemas[key] = f"t_{uuid.uuid4().hex[:16]}"
                    admin.execute(f"CREATE SCHEMA {schemas[key]}")
                if kwargs.get("cipher") is None and (len(args) < 3 or args[2] is None):
                    kwargs["cipher"] = cipher_for(path)
                path = _with_schema(PG_URL, schemas[key])
            original(self, path, *args, **kwargs)

        monkeypatch.setattr(Store, "__init__", init)
        try:
            yield
        finally:
            for schema in schemas.values():
                admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            admin.close()
