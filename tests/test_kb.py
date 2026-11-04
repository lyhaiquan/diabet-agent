from diacare.kb import load_kb


def test_load_kb_reads_txt_and_md(tmp_path):
    (tmp_path / "a.txt").write_text("glucose cao", encoding="utf-8")
    (tmp_path / "b.md").write_text("ăn nhiều rau", encoding="utf-8")
    (tmp_path / "ignore.bin").write_bytes(b"\x00")
    docs = dict(load_kb(tmp_path))
    assert docs == {"a.txt": "glucose cao", "b.md": "ăn nhiều rau"}
