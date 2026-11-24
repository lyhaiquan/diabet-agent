"""DiaCare dưới dạng MCP server (Model Context Protocol, stdio): trợ lý AI nào hỗ trợ MCP (Claude Desktop, Claude Code,
VS Code...) gọi được các công cụ đã kiểm thử của DiaCare.

    python -m diacare.mcp_server            # (chạy từ thư mục src, hoặc đặt PYTHONPATH=src)

Chỉ mở công cụ TẤT ĐỊNH, không cần lớp Rules canh:
  - check_lab            đối chiếu xét nghiệm (HbA1c, đường huyết) với ngưỡng ADA 2024
  - search_guidelines    tìm đoạn tài liệu MedlinePlus/WHO trong kho kb/, kèm tên nguồn
  - risk_factor_evidence tài liệu nói gì và dữ liệu BRFSS đo được gì về một yếu tố nguy cơ (đồ thị tri thức)
  - food_nutrition       carb/kcal món Việt trong câu (bảng USDA của Nutrition agent)
  - tray_carbs           khoảng tinh bột của một khay cơm (tên món Calo Khay + gram)
  - predict_risk         mức nguy cơ ĐTĐ típ 2 từ 21 chỉ số BRFSS
và tài liệu trong kb/ dưới dạng resource (kb://<tên tệp>).

KHÔNG mở: công cụ "tư vấn" chạy cả pipeline (LLM bên ngoài sẽ viết lại câu trả lời, bỏ qua lớp Rules an toàn), và dữ
liệu người bệnh (nhật ký, trí nhớ, hội thoại đang được mã hoá trong DB). Chạy qua stdio nên chỉ nằm trên máy, không mở
cổng mạng.

Giao thức viết bằng thư viện chuẩn (JSON-RPC 2.0, mỗi dòng một bản tin) nên không cần cài gói `mcp`. stdout chỉ dành
cho bản tin; mọi thứ khác (log, cảnh báo của thư viện) đi stderr.
"""
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "diacare", "title": "DiaCare – tự theo dõi đái tháo đường típ 2", "version": "4.8"}
NOTE = "Thông tin tham khảo, không phải chẩn đoán; quyết định điều trị cần hỏi bác sĩ."


class ToolError(ValueError):
    """Lỗi do đầu vào: trả về cho mô hình dưới dạng kết quả isError, không phải lỗi giao thức."""


class DiaCareTools:
    """Các phần nặng (embedding, mô hình dự đoán, đồ thị) chỉ nạp ở lần gọi đầu tiên."""

    def __init__(self, kb_dir=None):
        self.kb_dir = Path(kb_dir or os.environ.get("DIACARE_KB") or ROOT / "kb")
        self._retriever = self._predictor = self._graph = self._nutrition = self._carb = None

    # ---- công cụ ----
    def check_lab(self, text):
        from diacare.labs import classify, parse_lab_text
        rows = classify(parse_lab_text(text))
        if not rows:
            raise ToolError("Không đọc được kết quả xét nghiệm nào (cần HbA1c hoặc đường huyết kèm con số).")
        return {"results": [{k: r[k] for k in ("label", "value_std", "unit_std", "level", "level_text", "reference")}
                            for r in rows], "note": NOTE}

    def search_guidelines(self, question, k=3):
        if self._retriever is None:
            from diacare.factory import default_min_score, make_embed_fn
            from diacare.kb import load_kb
            from diacare.retriever import Retriever
            self._retriever = Retriever(make_embed_fn(), load_kb(self.kb_dir), min_score=default_min_score(),
                                        mode="hybrid")
        k = max(1, min(int(k), 8))
        hits = self._retriever.search(question, k=k)
        return {"passages": [{"source": h["source"], "text": h["text"], "score": round(float(h["score"]), 3)}
                             for h in hits], "note": "Trích tài liệu MedlinePlus/WHO; trích dẫn kèm tên nguồn."}

    def risk_factor_evidence(self, question):
        from diacare.kg import describe_factor, factor_facts, link_factors, load_default_graph
        if self._graph is None:
            self._graph = load_default_graph()
        fids = link_factors(question)
        if not fids:
            raise ToolError("Không nhận ra yếu tố nguy cơ nào trong câu (ví dụ: béo phì, hút thuốc, huyết áp cao, "
                            "ít vận động, uống rượu).")
        facts = [factor_facts(self._graph, f) for f in fids[:3]]
        return {"factors": [{"factor": f["factor"], "name": f["name"], "summary": describe_factor(f)} for f in facts],
                "note": "Số liệu BRFSS là liên hệ, không phải nhân quả."}

    def food_nutrition(self, text):
        from diacare.nutrition import NutritionAgent, load_foods
        if self._nutrition is None:
            self._nutrition = NutritionAgent(load_foods(ROOT / "data" / "nutrition" / "vn_foods.json"))
        res = self._nutrition.analyze(text)
        if res is None:
            raise ToolError("Không nhận ra món ăn nào trong câu (bảng có các món Việt phổ biến: phở, cơm, bánh mì...).")
        return dict(res, note="Số liệu USDA FoodData Central, khẩu phần ước chừng.")

    def tray_carbs(self, dishes):
        from diacare import meal_scan
        if self._carb is None:
            self._carb = meal_scan.load_table()
        by_name = {v["name"]: k for k, v in self._carb.items()}
        items, unknown = [], []
        for d in dishes or []:
            name = str(d.get("name", "")).strip()
            cls = name if name in self._carb else by_name.get(name)
            if cls is None:
                unknown.append(name)
                continue
            items.append({"cls": cls, "grams": float(d.get("grams") or 0), "gram_source": "user"})
        if not items:
            raise ToolError("Không có món nào trong bảng 45 món căng tin của Calo Khay. Tên món: "
                            + ", ".join(sorted(by_name)))
        total = meal_scan.meal_carbs(items, self._carb)
        return {"carb_g": total["carb_g"], "carb_low": total["carb_low"], "carb_high": total["carb_high"],
                "kcal": total["kcal"], "items": total["items"], "not_counted": total["uncounted"] + unknown,
                "summary": meal_scan.carb_text(total).replace("**", ""),
                "note": "Ước lượng để theo dõi (Nutrition5k/USDA), không dùng để tính liều insulin."}

    def predict_risk(self, profile):
        from diacare.rules import risk_band, validate_profile
        errors = validate_profile(profile or {})
        if errors:
            raise ToolError("Hồ sơ chưa hợp lệ: " + "; ".join(errors))
        if self._predictor is None:
            from diacare.predictor import Predictor
            self._predictor = Predictor(ROOT / "models")
        p = self._predictor.predict(profile)
        return {"probability": round(p, 3), "band": risk_band(p),
                "note": "Ước tính sàng lọc từ dữ liệu khảo sát (BRFSS/NHANES), không phải chẩn đoán. " + NOTE}

    # ---- resource: tài liệu kb/ ----
    def list_docs(self):
        return sorted(p.name for p in self.kb_dir.iterdir() if p.suffix.lower() in (".txt", ".md"))

    def read_doc(self, name):
        if name not in self.list_docs():  # chỉ tệp có trong danh sách: không cho đọc đường dẫn tuỳ ý
            raise KeyError(name)
        return (self.kb_dir / name).read_text(encoding="utf-8")


def _profile_schema():
    from diacare.rules import FEATURE_RANGES
    return {"type": "object", "required": sorted(FEATURE_RANGES),
            "properties": {k: {"type": "number", "minimum": lo, "maximum": hi} for k, (lo, hi) in FEATURE_RANGES.items()},
            "description": "21 chỉ số mã hoá theo BRFSS 2015 (0/1 cho câu có/không; BMI; GenHlth 1-5; MentHlth, "
                           "PhysHlth 0-30 ngày; Age nhóm 1-13; Education 1-6; Income 1-8)."}


TOOLS = [
    ("check_lab", "Đối chiếu kết quả xét nghiệm đái tháo đường (HbA1c %, đường huyết lúc đói, đường huyết bất kỳ, "
                  "nghiệm pháp dung nạp) với ngưỡng ADA 2024. Nhận văn bản tự do, ví dụ 'HbA1c 6,8%, glucose đói "
                  "7,2 mmol/L'. Không phải chẩn đoán.",
     {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}),
    ("search_guidelines", "Tìm đoạn tài liệu y khoa tiếng Việt/Anh (MedlinePlus, WHO) về đái tháo đường liên quan tới "
                          "câu hỏi, kèm tên tệp nguồn để trích dẫn.",
     {"type": "object", "required": ["question"],
      "properties": {"question": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 8}}}),
    ("risk_factor_evidence", "Với yếu tố nguy cơ nêu trong câu (béo phì, hút thuốc, huyết áp cao, ít vận động...): "
                             "tài liệu nói gì và dữ liệu BRFSS 2015 đo được gì (OR thô và hiệu chỉnh).",
     {"type": "object", "required": ["question"], "properties": {"question": {"type": "string"}}}),
    ("food_nutrition", "Carb, chất xơ, đường, kcal của các món Việt nêu trong câu (ví dụ '1 bát phở bò và 2 quả "
                       "chuối'), theo bảng USDA FoodData Central.",
     {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}),
    ("tray_carbs", "Khoảng tinh bột (g) và kcal của một khay cơm căng tin từ danh sách món (tên tiếng Việt hoặc mã "
                   "lớp Calo Khay) và số gram.",
     {"type": "object", "required": ["dishes"],
      "properties": {"dishes": {"type": "array", "items": {
          "type": "object", "required": ["name", "grams"],
          "properties": {"name": {"type": "string"}, "grams": {"type": "number", "minimum": 0}}}}}}),
    ("predict_risk", "Ước tính mức nguy cơ đái tháo đường típ 2 (thấp / trung bình / cao) từ 21 chỉ số BRFSS. "
                     "Sàng lọc, không phải chẩn đoán.",
     {"type": "object", "required": ["profile"], "properties": {"profile": None}}),
]


class Server:
    def __init__(self, tools=None):
        self.tools = tools or DiaCareTools()

    def _tool_list(self):
        out = []
        for name, desc, schema in TOOLS:
            if name == "predict_risk":
                schema = {"type": "object", "required": ["profile"], "properties": {"profile": _profile_schema()}}
            out.append({"name": name, "description": desc, "inputSchema": schema})
        return out

    def handle(self, msg):
        """Một bản tin JSON-RPC -> bản tin trả lời (None với notification)."""
        method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if mid is None:  # notification (notifications/initialized, notifications/cancelled...): không trả lời
            return None
        try:
            result = self._dispatch(method, params)
        except _RpcError as e:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": e.code, "message": str(e)}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _dispatch(self, method, params):
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {}, "resources": {}}, "serverInfo": SERVER_INFO,
                    "instructions": "Công cụ tất định của DiaCare. " + NOTE}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self._tool_list()}
        if method == "tools/call":
            return self._call(params.get("name"), params.get("arguments") or {})
        if method == "resources/list":
            return {"resources": [{"uri": f"kb://{n}", "name": n, "mimeType": "text/plain"}
                                  for n in self.tools.list_docs()]}
        if method == "resources/read":
            uri = params.get("uri", "")
            if not uri.startswith("kb://"):
                raise _RpcError(-32602, f"Không có resource {uri}")
            try:
                text = self.tools.read_doc(uri[len("kb://"):])
            except KeyError:
                raise _RpcError(-32602, f"Không có resource {uri}") from None
            return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": text}]}
        raise _RpcError(-32601, f"Không hỗ trợ phương thức {method}")

    def _call(self, name, args):
        if name not in {t[0] for t in TOOLS}:
            raise _RpcError(-32602, f"Không có công cụ {name}")
        try:
            out = getattr(self.tools, name)(**args)
        except (ToolError, TypeError) as e:  # TypeError: thiếu/thừa tham số
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                "structuredContent": out, "isError": False}


class _RpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def serve(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    out = stdout or sys.stdout
    server = Server()
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON không hợp lệ"}}
        else:
            with redirect_stdout(sys.stderr):  # thư viện in ra stdout thì không làm hỏng luồng bản tin
                reply = server.handle(msg) if isinstance(msg, dict) else {
                    "jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Bản tin không hợp lệ"}}
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()


def main():
    for s in (sys.stdin, sys.stdout):
        s.reconfigure(encoding="utf-8")
    serve()


if __name__ == "__main__":
    main()
