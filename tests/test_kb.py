from diacare.kb import load_kb


def test_load_kb_reads_txt_and_md(tmp_path):
    (tmp_path / "a.txt").write_text("glucose cao", encoding="utf-8")
    (tmp_path / "b.md").write_text("ăn nhiều rau", encoding="utf-8")
    (tmp_path / "ignore.bin").write_bytes(b"\x00")
    docs = dict(load_kb(tmp_path))
    assert docs == {"a.txt": "glucose cao", "b.md": "ăn nhiều rau"}


def test_load_kb_extension_case_insensitive(tmp_path):
    (tmp_path / "A.TXT").write_text("glucose", encoding="utf-8")
    assert dict(load_kb(tmp_path)) == {"A.TXT": "glucose"}


def test_load_kb_missing_dir_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError, match="nope"):
        load_kb(tmp_path / "nope")


def test_load_kb_empty_dir(tmp_path):
    assert load_kb(tmp_path) == []
