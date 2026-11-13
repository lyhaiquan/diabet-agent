"""Sơ đồ động luồng agent: phát lại một lượt chạy từ log (state.trace) bằng SVG + JS thuần.

Trả về một chuỗi HTML tự chứa (không tải thư viện ngoài), nhúng vào Streamlit bằng st.html.
"""
import json
import uuid

# id, tên, mô tả, biểu tượng, tài nguyên dùng, toạ độ (x, y) góc trên trái
NODES = [
    ("Memory", "Memory", "Nhớ thông tin bệnh nhân", "🧠", "SQLite", (215, 40)),
    ("Lab", "Lab", "Đối chiếu ngưỡng xét nghiệm", "🧪", "ADA 2024 · OCR", (415, 40)),
    ("Predictor", "Predictor", "Dự đoán nguy cơ", "📈", "5 bộ dữ liệu · đã hiệu chỉnh", (615, 40)),
    ("Retriever", "Retriever", "Tìm tài liệu (RAG)", "🔎", "KB · sbert", (815, 40)),
    ("Graph", "Graph", "Tra đồ thị tri thức", "🕸️", "Neo4j · KG", (1015, 40)),
    ("Nutrition", "Nutrition", "Tra dinh dưỡng món ăn", "🥗", "USDA FDC", (215, 470)),
    ("RL", "RL", "Chọn trọng tâm tư vấn", "🎯", "học từ 👍/👎", (405, 470)),
    ("Context", "Context", "Cắt ngữ cảnh từng agent", "🧩", "ngân sách token", (595, 470)),
    ("Advisor", "Advisor", "LLM viết bản nháp", "💬", "Ollama qwen2.5:7b", (785, 470)),
    ("Rules", "Rules", "Lọc an toàn, gắn cờ", "🛡️", "luật y khoa", (975, 470)),
]
NODE_W, NODE_H = 170, 92


def _box(node_id, title, sub, icon, tag, x, y, w=NODE_W, h=NODE_H, cls="node"):
    return (
        f'<g class="{cls}" id="{{uid}}-{node_id}" transform="translate({x},{y})">'
        f'<rect class="card" width="{w}" height="{h}" rx="12"/>'
        f'<text class="ico" x="16" y="34">{icon}</text>'
        f'<text class="ttl" x="46" y="30">{title}</text>'
        f'<text class="sub" x="14" y="54">{sub}</text>'
        f'<text class="tag" x="14" y="76">{tag}</text>'
        f'<text class="ms" x="{w - 10}" y="22" text-anchor="end"></text>'
        f'<text class="chk" x="{w - 12}" y="{h - 10}" text-anchor="end">✓</text>'
        f'</g>'
    )


def _svg():
    parts = ['<svg viewBox="0 0 1200 590" xmlns="http://www.w3.org/2000/svg" role="img" '
             'aria-label="Sơ đồ luồng agent DiaCare">']
    # vùng nhóm (nét đứt) giống sơ đồ kiến trúc
    parts.append('<rect class="zone" x="200" y="18" width="995" height="138" rx="16"/>'
                 '<text class="zlabel" x="214" y="34">AGENT CHUYÊN TRÁCH · TRƯỚC LLM</text>')
    parts.append('<rect class="zone" x="200" y="448" width="965" height="134" rx="16"/>'
                 '<text class="zlabel" x="214" y="577">CHÍNH SÁCH RL · LLM VÀ KIỂM TRA AN TOÀN</text>')
    # cạnh orchestrator <-> agent (vẽ trước để nằm dưới các hộp)
    ox, oy = 570, 305
    for node_id, *_rest, (x, y) in NODES:
        cx, cy = x + NODE_W / 2, y + NODE_H / 2
        parts.append(f'<line class="edge" id="{{uid}}-e-{node_id}" x1="{ox}" y1="{oy}" x2="{cx}" y2="{cy}"/>')
    parts.append(f'<line class="edge" id="{{uid}}-e-in" x1="180" y1="305" x2="{ox}" y2="{oy}"/>')
    parts.append(f'<line class="edge" id="{{uid}}-e-out" x1="{ox}" y1="{oy}" x2="1010" y2="250"/>')
    parts.append('<line class="edge" id="{uid}-e-done" x1="1090" y1="300" x2="1090" y2="380"/>')
    # hộp
    parts.append(_box("User", "Câu hỏi", "Người dùng gửi", "🙋", "giao diện chat", 20, 259, 160, 92))
    parts.append(_box("Orchestrator", "Orchestrator", "Điều phối tuần tự các agent", "🧭",
                      "chỉ đưa mỗi agent lát ngữ cảnh của nó", 440, 250, 260, 110, cls="node hub"))
    for node_id, title, sub, icon, tag, (x, y) in NODES:
        parts.append(_box(node_id, title, sub, icon, tag, x, y))
    parts.append(_box("Final", "Trả lời cuối", "Bản nháp + ghi chú Rules", "✅", "kèm lời nhắc bác sĩ",
                      1010, 200, 170, 100, cls="node final"))
    parts.append(_box("Done", "Hoàn tất", "Lưu log + lịch sử", "🏁", "runs · trace_json",
                      1010, 380, 170, 92, cls="node final"))
    parts.append('<circle class="dot" id="{uid}-dot" r="7" cx="-50" cy="-50"/>')
    # chú thích nằm dưới hộp Câu hỏi; góc trên phải giờ là hộp Graph
    parts.append('<text class="note" x="20" y="384">Orchestrator gọi từng agent</text>'
                 '<text class="note" x="20" y="402">theo thứ tự, nhận kết quả về,</text>'
                 '<text class="note" x="20" y="420">rồi mới gọi agent kế tiếp.</text>')
    parts.append('</svg>')
    return "".join(parts)


_CSS = """
#{uid}{--bg:#f6f2ea;--card:#fffdf9;--ink:#2b2622;--muted:#7a6f66;--line:#c9bfb4;--accent:#c0562f;
 --ok:#2f8f5b;--skip:#b9b1a8;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);
 border-radius:14px;padding:14px;color:var(--ink)}
#{uid} svg{width:100%;height:auto;display:block}
#{uid} .zone{fill:none;stroke:var(--line);stroke-dasharray:6 5}
#{uid} .zlabel{font-size:11px;font-weight:700;letter-spacing:.06em;fill:var(--muted)}
#{uid} .edge{stroke:var(--line);stroke-width:2;stroke-dasharray:5 6}
#{uid} .edge.on{stroke:var(--accent);stroke-width:3;stroke-dasharray:none}
#{uid} .edge.used{stroke:var(--accent);opacity:.45;stroke-dasharray:none}
#{uid} .card{fill:var(--card);stroke:#d8cfc5;stroke-width:1.5;transition:all .25s}
#{uid} .hub .card{stroke:var(--accent);stroke-width:2}
#{uid} .ico{font-size:22px}
#{uid} .ttl{font-size:15px;font-weight:700;fill:var(--ink)}
#{uid} .sub{font-size:11.5px;fill:var(--muted)}
#{uid} .tag{font-size:10.5px;fill:var(--accent);font-family:ui-monospace,Consolas,monospace}
#{uid} .ms{font-size:11px;font-family:ui-monospace,Consolas,monospace;fill:var(--ok);font-weight:700}
#{uid} .chk{font-size:16px;fill:var(--ok);opacity:0;font-weight:700}
#{uid} .node.active .card{stroke:var(--accent);stroke-width:3.5;fill:#fff1e8}
#{uid} .node.done .card{stroke:var(--ok);stroke-width:2}
#{uid} .node.done .chk{opacity:1}
#{uid} .node.skip{opacity:.38}
#{uid} .node.active{animation:{uid}-pulse 1s ease-in-out infinite}
@keyframes {uid}-pulse{50%{opacity:.82}}
#{uid} .dot{fill:var(--accent);filter:drop-shadow(0 0 6px var(--accent))}
#{uid} .note{font-size:11px;fill:var(--muted);font-style:italic}
#{uid} .bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 10px}
#{uid} button,#{uid} select{font:inherit;font-size:13px;border-radius:8px;border:1px solid #d8cfc5;
 background:var(--card);color:var(--ink);padding:5px 12px;cursor:pointer}
#{uid} button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
#{uid} .status{font-size:13px;color:var(--muted)}
#{uid} .panes{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
#{uid} .pane{background:var(--card);border:1px solid #e3dad0;border-radius:10px;padding:10px;height:170px;
 box-sizing:border-box;overflow:auto;font-size:12.5px;line-height:1.5}
#{uid} .pane h4{margin:0 0 6px;font-size:12px;letter-spacing:.05em;color:var(--muted)}
#{uid} .log div{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;padding:2px 0;
 border-bottom:1px dashed #eee4da}
#{uid} .log b{color:var(--accent)}
#{uid} .log .t{color:var(--muted)}
#{uid} .flag{display:inline-block;background:#fde7da;color:#9a3f1d;border-radius:10px;padding:1px 8px;
 margin:2px 4px 0 0;font-size:11px;font-family:ui-monospace,Consolas,monospace}
#{uid} .caret{display:inline-block;width:7px;height:14px;background:var(--accent);vertical-align:-2px;
 animation:{uid}-blink 1s steps(1) infinite}
@keyframes {uid}-blink{50%{opacity:0}}
@media (max-width:700px){#{uid} .panes{grid-template-columns:1fr}}
"""

_JS = r"""
(function(){
const U = "{uid}", D = {data};
const root = document.getElementById(U);
if (!root) return;
const $ = id => document.getElementById(U + "-" + id);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const dot = $("dot"), logEl = root.querySelector(".log"), draftEl = root.querySelector(".draft");
const statusEl = root.querySelector(".st"), speedEl = root.querySelector("select");
const ALL = ["Memory","Lab","Predictor","Retriever","Graph","Nutrition","RL","Context","Advisor","Rules"];
let token = 0;
const center = id => { const g = $(id); const r = g.querySelector("rect"); const t = g.transform.baseVal[0].matrix;
  return [t.e + (+r.getAttribute("width"))/2, t.f + (+r.getAttribute("height"))/2]; };
const speed = () => +speedEl.value;
async function move(a, b, ms, my){
  const [x1,y1] = center(a), [x2,y2] = center(b), t0 = performance.now(), dur = ms / speed();
  while (true){ if (my !== token) return; const k = Math.min(1,(performance.now()-t0)/dur);
    const e = k<.5 ? 2*k*k : 1-Math.pow(-2*k+2,2)/2;
    dot.setAttribute("cx", x1+(x2-x1)*e); dot.setAttribute("cy", y1+(y2-y1)*e);
    if (k>=1) break; await new Promise(requestAnimationFrame); }
}
const edge = id => $("e-" + id);
function setEdge(id, cls){ const e = edge(id); if (e){ e.classList.remove("on","used"); if (cls) e.classList.add(cls);} }
function log(agent, text, ms){
  const d = document.createElement("div");
  d.innerHTML = `<span class="t">${(elapsed/1000).toFixed(3)}s</span> <b></b> · <span class="x"></span>` +
    (ms != null ? ` <span class="t">(${ms.toFixed(0)} ms)</span>` : "");
  d.querySelector("b").textContent = agent; d.querySelector(".x").textContent = text;
  logEl.appendChild(d); logEl.scrollTop = logEl.scrollHeight;
}
let elapsed = 0;
function reset(){
  root.querySelectorAll(".node").forEach(n => n.classList.remove("active","done","skip"));
  root.querySelectorAll(".ms").forEach(n => n.textContent = "");
  root.querySelectorAll(".edge").forEach(e => e.classList.remove("on","used"));
  logEl.innerHTML = ""; draftEl.innerHTML = '<span class="status">(chưa có)</span>';
  dot.setAttribute("cx",-50); dot.setAttribute("cy",-50); elapsed = 0;
  const ran = new Set(D.trace.map(e => e.agent));
  ALL.forEach(a => { if (!ran.has(a)) $(a).classList.add("skip"); });
}
async function typeDraft(text, ms, my){
  draftEl.textContent = ""; const caret = document.createElement("span"); caret.className = "caret";
  const words = text.split(/(\s+)/); const per = Math.max(8, ms / Math.max(words.length,1));
  const span = document.createElement("span"); draftEl.appendChild(span); draftEl.appendChild(caret);
  for (const w of words){ if (my !== token) return; span.textContent += w; draftEl.scrollTop = draftEl.scrollHeight;
    await sleep(per / speed()); }
  caret.remove();
}
async function play(){
  const my = ++token; reset();
  statusEl.textContent = "Đang phát lại…";
  const U_ = "User", O = "Orchestrator";
  $(U_).classList.add("active"); log("Người dùng", D.question || "(trống)");
  setEdge("in","on"); await move(U_, O, 700, my); if (my!==token) return;
  setEdge("in","used"); $(U_).classList.replace("active","done"); $(O).classList.add("active");
  await sleep(350/speed());
  for (const [i, e] of D.trace.entries()){
    if (my !== token) return;
    statusEl.textContent = `Bước ${i+1}/${D.trace.length}: ${e.agent}`;
    const hop = Math.min(1100, 450 + 160*Math.log10(1 + e.ms));
    if (e.agent === O || !$(e.agent)){
      log(e.agent, e.detail, e.ms); await sleep(hop/speed()); elapsed += e.ms; continue;
    }
    setEdge(e.agent, "on"); await move(O, e.agent, hop*0.45, my); if (my!==token) return;
    const n = $(e.agent); n.classList.add("active");
    if (e.agent === "Advisor" && D.draft){ await typeDraft(D.draft, Math.min(2600, 900 + e.ms/4), my); }
    else { await sleep(hop*0.6/speed()); }
    if (my!==token) return;
    elapsed += e.ms;
    n.classList.replace("active","done"); n.querySelector(".ms").textContent = `${e.ms.toFixed(0)} ms`;
    log(e.agent, e.detail, e.ms);
    if (e.agent === "Rules" && D.flags.length){
      const f = document.createElement("div"); f.innerHTML = "<b>Cờ:</b> ";
      D.flags.forEach(x => { const s = document.createElement("span"); s.className = "flag"; s.textContent = x; f.appendChild(s); });
      draftEl.appendChild(f);
    }
    await move(e.agent, O, hop*0.35, my); setEdge(e.agent, "used");
  }
  if (my!==token) return;
  $(O).classList.replace("active","done");
  setEdge("out","on"); await move(O, "Final", 700, my); if (my!==token) return;
  setEdge("out","used"); $("Final").classList.add("done");
  log("Trả lời", (D.final || "").slice(0, 140) + ((D.final||"").length > 140 ? "…" : ""));
  setEdge("done","on"); await move("Final", "Done", 450, my); setEdge("done","used"); $("Done").classList.add("done");
  dot.setAttribute("cx",-50);
  statusEl.textContent = `Xong: ${D.trace.length} bước · ${(elapsed/1000).toFixed(2)} s thời gian thật`;
}
root.querySelector("button.primary").addEventListener("click", play);
root.querySelector("button.stop").addEventListener("click", () => { token++; statusEl.textContent = "Đã dừng"; });
play();
})();
"""


def _safe_json(obj):
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def flow_html(trace, question="", draft="", final="", flags=(), uid=None, page=False):
    """HTML tự chứa phát lại các bước agent của một lượt chạy (trace: [{agent, detail, ms}])."""
    uid = uid or "dcflow" + uuid.uuid4().hex[:8]
    data = {"trace": [{"agent": e["agent"], "detail": e["detail"], "ms": float(e["ms"])} for e in trace or []],
            "question": question or "", "draft": draft or "", "final": final or "", "flags": list(flags or [])}
    svg = _svg().replace("{uid}", uid)
    body = (
        f'<div id="{uid}" class="notranslate" translate="no"><style>{_CSS.replace("{uid}", uid)}</style>'
        f'<div class="bar"><button class="primary" type="button">▶ Phát lại</button>'
        f'<button class="stop" type="button">■ Dừng</button>'
        f'<label class="status">Tốc độ <select><option value="0.5">0.5×</option>'
        f'<option value="1" selected>1×</option><option value="2">2×</option></select></label>'
        f'<span class="status st"></span></div>{svg}'
        f'<div class="panes"><div class="pane"><h4>LOG TỪNG BƯỚC</h4><div class="log"></div></div>'
        f'<div class="pane"><h4>ADVISOR ĐANG VIẾT → RULES</h4><div class="draft"></div></div></div>'
        f'<script>{_JS.replace("{uid}", uid).replace("{data}", _safe_json(data))}</script></div>'
    )
    if not page:
        return body
    # trang riêng cho iframe
    return ('<!doctype html><html lang="vi" translate="no"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<style>html,body{margin:0;background:transparent}</style></head>'
            f'<body>{body}</body></html>')
