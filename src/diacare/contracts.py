"""DiaCare Multi-Agent System - Communication Contracts & Decision Report Standards.

Cài đặt đầy đủ các chuẩn giao tiếp và báo cáo theo tài liệu đặc tả PTIT
(Mục 3.1, 4.1, 5.3, 6.1, 6.2, 6.3, 10).
"""
from __future__ import annotations

import unicodedata
import uuid
from typing import Any

from diacare.rules import (
    DISCLAIMER,
    EMERGENCY_TERMS,
    FEATURE_RANGES,
    HIGH_RISK_THRESHOLD,
    LOW_RISK_THRESHOLD,
    SYMPTOM_TERMS,
    _SYMPTOM_PATTERN,
    risk_band,
    validate_profile,
)

MODEL_VERSION = "diabetes_dl_v1"
SYSTEM_VERSION = "diacare_mas_v3"
UNCERTAIN_MARGIN = 0.05

HUMAN_REVIEW_FLAGS = (
    "high_risk_referral",
    "symptom_referral",
    "emergency_referral",
    "lab_diabetes_range",
    "lab_low_glucose",
    "conflicting_results_review",
    "uncertain_prediction_review",
    "unsafe_advice_blocked",
)

LIMITATIONS = (
    "Đầu ra dự đoán của mô hình chỉ mang tính hỗ trợ quyết định, không phải chẩn đoán lâm sàng xác nhận.",
    "Hệ thống tuyệt đối không kê đơn thuốc hoặc hướng dẫn thay đổi liều thuốc/insulin.",
    "Tác tử học tăng cường (RL Agent) chỉ hoạt động trên môi trường mô phỏng để gợi ý trọng tâm tư vấn lối sống/theo dõi.",
    "Các luật lâm sàng cần được bác sĩ chuyên khoa thẩm định trước khi áp dụng thực tế.",
    "Hệ thống sử dụng dữ liệu công khai đã ẩn danh (CDC BRFSS 2015, USDA, ADA 2024, MedlinePlus, WHO).",
    "Mọi nội dung truy xuất từ Đồ thị tri thức (KG) và RAG đều gắn nhãn nguồn gốc để truy vết.",
    "Các kết quả không chắc chắn hoặc mâu thuẫn giữa các nguồn đều được gắn cờ (uncertain_prediction_review, conflicting_results_review) để chuyển chuyên gia y tế xem xét.",
)


def new_request_id() -> str:
    """Tạo mã yêu cầu duy nhất cho mỗi lượt tương tác theo chuẩn Mục 6.1."""
    return "req_" + uuid.uuid4().hex[:8]


def make_message(
    request_id: str,
    agent: str,
    status: str,
    payload: Any,
    evidence: list | None = None,
    model_version: str = SYSTEM_VERSION,
) -> dict:
    """Tạo cấu trúc tin nhắn chuẩn trao đổi giữa các tác tử (Mục 6.1 & 6.2)."""
    return {
        "request_id": request_id,
        "agent": agent,
        "status": status,
        "payload": payload,
        "evidence": list(evidence or []),
        "model_version": model_version,
    }


class PatientDataAgent:
    """Tác tử tiền xử lý và xác thực hồ sơ bệnh nhân (21 chỉ số BRFSS)."""

    def validate(self, profile: dict | None) -> dict:
        raw = dict(profile or {})
        errors = validate_profile(raw)
        if errors:
            return {
                "valid": False,
                "errors": errors,
                "profile": raw,
            }

        normalized = {}
        for k, v in raw.items():
            if k == "BMI":
                normalized[k] = float(v)
            elif k in FEATURE_RANGES:
                normalized[k] = int(v)
            else:
                normalized[k] = v

        return {
            "valid": True,
            "errors": [],
            "profile": normalized,
        }


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").lower()


def evaluate_pre_rules(
    risk: float | None,
    profile: dict | None,
    question: str = "",
    diagnosed: bool = False,
    labs: list | None = None,
) -> dict:
    """Thực thi suy diễn luật TRƯỚC khi gọi Explanation Agent (Mục 5.3 Bước 7).

    - Cờ `uncertain_prediction_review`: dự đoán rơi vào vùng không chắc chắn quanh 0.5 (0.45 - 0.55).
    - Cờ `conflicting_results_review`: risk < 0.2 (thấp) nhưng có xét nghiệm đái tháo đường / hạ đường huyết,
      hoặc câu hỏi chứa triệu chứng / dấu hiệu cấp cứu.
    """
    flags: list[str] = []
    notes: list[str] = []

    if risk is not None and abs(risk - HIGH_RISK_THRESHOLD) <= UNCERTAIN_MARGIN:
        flags.append("uncertain_prediction_review")
        notes.append(
            f"Dự đoán nguy cơ ({risk:.4f}) nằm trong vùng không chắc chắn "
            f"[{HIGH_RISK_THRESHOLD - UNCERTAIN_MARGIN:.2f}, {HIGH_RISK_THRESHOLD + UNCERTAIN_MARGIN:.2f}]: "
            "cần chuyển chuyên gia y tế thẩm định."
        )

    q = _norm(question)
    has_symptoms = any(t in q for t in SYMPTOM_TERMS) or bool(_SYMPTOM_PATTERN.search(q))
    has_emergency = any(t in q for t in EMERGENCY_TERMS)
    has_clinical_signs = has_symptoms or has_emergency

    lab_levels = {
        r.get("level")
        for r in (labs or [])
        if isinstance(r, dict) and "level" in r
    }
    has_conflicting_labs = bool(lab_levels.intersection({"diabetes", "low"}))

    if risk is not None and risk < LOW_RISK_THRESHOLD and (has_conflicting_labs or has_clinical_signs):
        flags.append("conflicting_results_review")
        reasons = []
        if has_conflicting_labs:
            reasons.append("xét nghiệm mức bất thường (đái tháo đường hoặc hạ đường huyết)")
        if has_clinical_signs:
            reasons.append("triệu chứng hoặc dấu hiệu cảnh báo lâm sàng trong câu hỏi")
        notes.append(
            f"Mâu thuẫn kết quả: Nguy cơ mô hình ước tính thấp ({risk:.4f} < {LOW_RISK_THRESHOLD}) "
            f"nhưng có {', '.join(reasons)}: cần chuyên gia y tế đánh giá."
        )

    return {
        "review_flags": flags,
        "needs_human_review": bool(flags),
        "notes": notes,
    }


class _DictWrapper:
    """Bọc dictionary để cho phép truy cập theo thuộc tính `state.attr`."""

    def __init__(self, d: dict):
        self._d = d

    def __getattr__(self, name: str) -> Any:
        return self._d.get(name)


def build_decision_report(state: Any, request_id: str | None = None) -> dict:
    """Tổng hợp Structured Decision-Support Report (Mục 1.2, Hình 1, Mục 4.2, Mục 5.3 Bước 12).

    Giữ tách biệt rõ ràng giữa dự đoán DL, kết quả luật, bằng chứng KG/RAG,
    mô phỏng RL và giải thích của LLM.
    """
    if isinstance(state, dict):
        state = _DictWrapper(state)

    req_id = request_id or getattr(state, "request_id", None) or new_request_id()
    risk = getattr(state, "risk", None)
    base_flags = list(getattr(state, "flags", None) or [])
    pre_rules = getattr(state, "pre_rules", None) or {}
    review_flags = list(pre_rules.get("review_flags", []))
    merged_flags = list(dict.fromkeys(base_flags + review_flags))

    docs = list(getattr(state, "docs", None) or [])
    labs = list(getattr(state, "labs", None) or [])
    kg = getattr(state, "kg", None) or {}
    nutrition = getattr(state, "nutrition", None) or {}
    rl = getattr(state, "rl", None)
    draft = getattr(state, "draft", "") or ""
    final = getattr(state, "final", "") or ""

    needs_human_review = any(f in merged_flags for f in HUMAN_REVIEW_FLAGS)

    return {
        "request_id": req_id,
        "model_version": MODEL_VERSION,
        "system_version": SYSTEM_VERSION,
        "prediction": {
            "prediction": (1 if risk >= HIGH_RISK_THRESHOLD else 0) if risk is not None else None,
            "score": round(float(risk), 4) if risk is not None else None,
            "risk_band": risk_band(risk) if risk is not None else None,
            "model_version": MODEL_VERSION,
        },
        "rules": {
            "flags": merged_flags,
            "review_flags": review_flags,
            "notes": list(pre_rules.get("notes", [])),
            "needs_human_review": needs_human_review,
        },
        "evidence": {
            "sources": [d["source"] for d in docs if isinstance(d, dict) and "source" in d],
            "rag_documents": [
                {"source": d.get("source"), "score": d.get("score")}
                for d in docs
                if isinstance(d, dict)
            ],
            "kg_factors": list(kg.get("factors", [])),
            "kg_lines": list(kg.get("lines", [])),
            "labs": [
                {
                    "test": r.get("test"),
                    "label": r.get("label"),
                    "value_std": r.get("value_std"),
                    "unit_std": r.get("unit_std"),
                    "level": r.get("level"),
                }
                for r in labs
                if isinstance(r, dict)
            ],
            "nutrition_items": [
                i.get("name")
                for i in nutrition.get("items", [])
                if isinstance(i, dict) and "name" in i
            ],
        },
        "rl_simulation": (
            {**rl, "simulation_only": True} if rl else None
        ),
        "explanation": {
            "draft": draft,
            "final": final,
        },
        "audit": {
            "trace": list(getattr(state, "trace", None) or []),
            "messages_count": len(getattr(state, "messages", None) or []),
        },
        "limitations": list(LIMITATIONS),
        "disclaimer": DISCLAIMER,
    }
