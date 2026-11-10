from dataclasses import dataclass, field


@dataclass
class State:
    question: str
    profile: dict
    history: list = field(default_factory=list)
    risk: float | None = None
    docs: list = field(default_factory=list)
    draft: str = ""
    final: str = ""
    flags: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    nutrition: dict | None = None
    patient_id: int | None = None
    memory: list = field(default_factory=list)
    labs: list = field(default_factory=list)
    kg: dict | None = None  # kết quả GraphAgent: {backend, factors, lines}
    rl: dict | None = None  # kết quả RLAgent: {action, label, guidance, q_value, ranking, state_key}
    request_id: str = ""  # mã định danh yêu cầu chuẩn Mục 5.3 & 6.1 (vd: req_a1b2c3d4)
    pre_rules: dict | None = None  # kết quả suy diễn luật trước Advisor: {review_flags, needs_human_review, notes}
    messages: list = field(default_factory=list)  # danh sách bản tin chuẩn Mục 6.1: [{request_id, agent, status, ...}]
    report: dict | None = None  # Báo cáo hỗ trợ quyết định có cấu trúc (Mục 5.3 Bước 12)
    trace: list = field(default_factory=list)  # [{agent, detail, ms}] theo thứ tự chạy
