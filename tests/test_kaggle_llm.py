import importlib.util
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kaggle_llm = _load("kaggle_llm", ROOT / "tools" / "kaggle_llm.py")


def test_only_current_run_url_is_accepted():
    rx = kaggle_llm.url_re("ab12cd34")
    old = "DIACARE_TUNNEL_URL=ffff0000 https://old-dead-link.trycloudflare.com"
    legacy = "DIACARE_TUNNEL_URL=https://legacy-link.trycloudflare.com"
    new = '{"data":"DIACARE_TUNNEL_URL=ab12cd34 https://fresh-link-here.trycloudflare.com\n"}'
    assert rx.search(old) is None and rx.search(legacy) is None
    assert rx.search(new).group(1) == "https://fresh-link-here.trycloudflare.com"


def test_serve_notebook_embeds_token_and_run_id(tmp_path, monkeypatch):
    nb_mod = _load("build_ollama_notebook", ROOT / "kaggle" / "build_ollama_notebook.py")
    monkeypatch.setattr(nb_mod, "OUT", tmp_path / "nb.ipynb")
    monkeypatch.setattr(nb_mod, "KERNEL_DIR", tmp_path / "kernel")
    nb_mod.build(serve_token="t" * 32, idle_minutes=17, run_id="ab12cd34")
    src = "\n".join(c.source for c in nbformat.read(tmp_path / "nb.ipynb", as_version=4).cells)
    assert "SERVE_IN_BATCH = True" in src and "RUN_ID = 'ab12cd34'" in src and "IDLE_MINUTES = 17" in src
    assert "EMBED_TOKEN = '" + "t" * 32 + "'" in src
    # cổng chặn trong notebook là đúng bản trong src (chỉ đổi kiểu nháy của docstring)
    gate = (ROOT / "src" / "diacare" / "ollama_gate.py").read_text(encoding="utf-8").replace('"""', "'''")
    assert gate in src
    for name in ("{idle}", "{serve}", "= {token}", "{run_id}", "{mark}", "{gate}", "{version}"):
        assert name not in src  # (cổng chặn có f"Bearer {token}" thật, nên kiểm "= {token}")


def test_plain_notebook_has_no_token(tmp_path, monkeypatch):
    nb_mod = _load("build_ollama_notebook2", ROOT / "kaggle" / "build_ollama_notebook.py")
    monkeypatch.setattr(nb_mod, "OUT", tmp_path / "nb.ipynb")
    monkeypatch.setattr(nb_mod, "KERNEL_DIR", tmp_path / "kernel")
    nb_mod.build()
    src = "\n".join(c.source for c in nbformat.read(tmp_path / "nb.ipynb", as_version=4).cells)
    assert "SERVE_IN_BATCH = False" in src and "EMBED_TOKEN = None" in src
