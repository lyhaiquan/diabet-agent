"""Nhớ câu trả lời của người ăn theo từng ảnh.

Người ăn đã xác nhận "đây là su su" hay đổi "su su" thành "bắp cải" cho một ảnh, thì quét lại đúng ảnh đó
(cùng thiết bị) không bị hỏi lại. Chỉ nhận ra ảnh giống hệt (cùng mã băm); ảnh chụp lại vẫn được hỏi như thường.
Mô hình không học từ đây: muốn mô hình đoán đúng hơn ở ảnh mới thì phải huấn luyện lại.
"""
from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import ImageAnswer, Scan, utcnow
from ..schemas import ItemIn
from . import calc
from .catalog import Catalog


def image_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def apply(db: Session, cat: Catalog, device: str | None, h: str, items: list[dict],
          rice_volume: float | None) -> list[dict]:
    """Áp câu trả lời cũ lên kết quả quét. Ghi `model_cls`, `model_flagged` vào mỗi món để /recalc biết
    mô hình đoán gì ban đầu (hai trường này không có trong ScanResponse nên frontend không thấy)."""
    for it in items:
        it.setdefault("model_cls", it["cls"])
        it.setdefault("model_flagged", bool(it["needs_confirm"]))
    if not device:
        return items
    rows = db.scalars(select(ImageAnswer).where(ImageAnswer.device_id == device, ImageAnswer.image_hash == h)).all()
    known = {r.model_cls: r.final_cls for r in rows}
    out = []
    for it in items:
        final = known.get(it["cls"])
        if final is None or final not in cat:
            out.append(it)
        elif final == it["cls"]:
            out.append({**it, "needs_confirm": False})
        elif any(o["cls"] == final for o in items):  # món đích đã có trên khay -> giữ nguyên, để người ăn tự chọn
            out.append(it)
        else:
            new = calc.recalc(cat, [ItemIn(**{**it, "cls": final, "orig_cls": it["cls"], "source": "renamed",
                                              "needs_confirm": False, "grams": None})], rice_volume)[0]
            new.pop("region_id", None); new.pop("confirmed", None)
            out.append(new)
    return out


def record(db: Session, sc: Scan, items: list[ItemIn]) -> None:
    """Lưu những món người ăn đã chốt: món mô hình hỏi lại mà người ăn xác nhận, hoặc món đã bị đổi tên."""
    h = sc.result_json.get("image_hash")
    if not h or not sc.device_id:
        return
    orig = {o["id"]: o for o in sc.result_json.get("items", [])}
    for it in items:
        o = orig.get(it.region_id if it.region_id is not None else it.id)
        if it.source == "manual" or o is None or it.needs_confirm:
            continue
        model_cls = o.get("model_cls", o["cls"])
        if it.cls == model_cls and not o.get("model_flagged", o.get("needs_confirm")):
            continue  # món mô hình chắc chắn, người ăn không đổi -> không cần nhớ
        row = db.scalar(select(ImageAnswer).where(ImageAnswer.device_id == sc.device_id,
                                                  ImageAnswer.image_hash == h, ImageAnswer.model_cls == model_cls))
        if row is None:
            db.add(ImageAnswer(device_id=sc.device_id, image_hash=h, model_cls=model_cls, final_cls=it.cls))
        elif row.final_cls != it.cls:
            row.final_cls, row.updated_at = it.cls, utcnow()
    db.commit()
