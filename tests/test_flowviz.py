import re

from diacare.flowviz import NODES, flow_html

TRACE = [{"agent": "Memory", "detail": "nhớ 0", "ms": 0.5},
         {"agent": "Predictor", "detail": "0.5% → thấp", "ms": 3},
         {"agent": "Advisor", "detail": "566 vào", "ms": 1200},
         {"agent": "Rules", "detail": "cờ", "ms": 1}]


def test_flow_html_embeds_trace_and_all_nodes():
    html = flow_html(TRACE, "HbA1c 8.5%?", "Bản nháp", "Trả lời", ["lab_diabetes_range"], uid="dcflowT")
    assert html.startswith('<div id="dcflowT"')
    for node_id, *_ in NODES:
        assert f'id="dcflowT-{node_id}"' in html
    assert '"agent": "Advisor"' in html and "lab_diabetes_range" in html
    assert "{uid}" not in html and "{data}" not in html


def test_flow_html_escapes_script_breakout():
    html = flow_html([{"agent": "Rules", "detail": "</script><b>x", "ms": 1}], "</script>", uid="dcflowX")
    script = html.split("<script>", 1)[1]
    assert script.count("</script>") == 1  # chỉ thẻ đóng thật


def test_flow_html_unique_ids_by_default():
    a, b = flow_html(TRACE), flow_html(TRACE)
    assert re.match(r'<div id="(dcflow\w+)"', a).group(1) != re.match(r'<div id="(dcflow\w+)"', b).group(1)
