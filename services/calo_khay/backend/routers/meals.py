"""Nhật ký bữa ăn (UC-B04, UC-B05) + thu thập chỉnh sửa khi người ăn đồng ý (BE-F5)."""
from __future__ import annotations

import logging
import shutil
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from ..db import Correction, Meal, MealItem
from ..deps import CtxDep, DbDep, DeviceDep, live_scan
from ..errors import ApiError
from ..schemas import DayMeals, Error, MealCreate, MealCreated
from ..services import calc

router = APIRouter(prefix="/meals", tags=["meals"])
log = logging.getLogger("calo_khay")


def _to_utc(dt: datetime, tz: ZoneInfo) -> datetime:
    if dt.tzinfo is None:  # không có múi giờ -> coi là giờ Việt Nam
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@router.post("", response_model=MealCreated, status_code=201, responses={400: {"model": Error}, 422: {"model": Error}},
             summary="Lưu bữa ăn vào nhật ký (lưu lại cùng bữa thì cập nhật, không tạo bữa trùng)")
def create_meal(body: MealCreate, ctx: CtxDep, db: DbDep, device: DeviceDep, response: Response):
    s, tz = ctx.settings, ZoneInfo(ctx.settings.timezone)
    sc = live_scan(db, body.scan_id)  # hết hạn vẫn cho lưu bữa ăn, chỉ không góp ảnh được
    items = calc.recalc(ctx.catalog, body.items, sc.result_json.get("rice_volume") if sc else None)
    tot = calc.total(items, s.daily_kcal, s.error_pct)

    # Lưu xong rồi sửa và bấm lưu lại -> cập nhật đúng bữa đó, không cộng đôi calo trong ngày.
    meal = None
    if body.meal_id is not None:
        meal = db.get(Meal, body.meal_id)
        if meal is None or meal.device_id != device:
            raise ApiError(404, "meal_not_found")
    elif body.scan_id:
        meal = db.scalar(select(Meal).where(Meal.device_id == device, Meal.scan_id == body.scan_id))
    updated = meal is not None
    rows = [MealItem(region_id=i["region_id"], cls=i["cls"], grams=i["grams"], kcal=i["kcal"],
                     source=i["source"], orig_cls=i["orig_cls"], conf=i["conf"], confirmed=i["confirmed"])
            for i in items]
    if meal is None:
        meal = Meal(device_id=device, items=rows)
        db.add(meal)
    else:
        meal.items = rows  # cascade delete-orphan xoá các món cũ
    meal.scan_id = sc.scan_id if sc else meal.scan_id
    meal.model_version = sc.model_version if sc else meal.model_version
    meal.eaten_at, meal.total_g, meal.total_kcal = _to_utc(body.eaten_at, tz), tot["grams"], tot["kcal"]
    db.flush()

    saved, dropped_img = False, None
    if body.share_corrections and sc is not None and sc.image_path and Path(sc.image_path).exists():
        s.corrections_dir.mkdir(parents=True, exist_ok=True)
        dst = s.corrections_dir / f"meal_{meal.meal_id}.jpg"
        shutil.copyfile(sc.image_path, dst)
        if meal.correction is None:
            db.add(Correction(meal_id=meal.meal_id, image_path=str(dst), original_json=sc.result_json,
                              corrected_json=items))
        else:
            meal.correction.image_path, meal.correction.original_json = str(dst), sc.result_json
            meal.correction.corrected_json = items
        saved = True
    elif meal.correction is not None and not body.share_corrections:
        dropped_img, meal.correction = meal.correction.image_path, None  # người ăn bỏ tick góp ảnh ở lần lưu sau -> xoá bản đã góp
    db.commit()
    if dropped_img:
        Path(dropped_img).unlink(missing_ok=True)
    if updated:
        response.status_code = 200
    log.info("meal %s %s items=%d kcal=%d share=%s", meal.meal_id, "updated" if updated else "created",
             len(items), tot["kcal"], saved)
    return dict(meal_id=meal.meal_id, total=tot, correction_saved=saved, updated=updated)


@router.get("", response_model=DayMeals, responses={400: {"model": Error}}, summary="Bữa ăn trong một ngày + tổng ngày")
def list_meals(ctx: CtxDep, db: DbDep, device: DeviceDep,
               day: Annotated[date, Query(alias="date", description="YYYY-MM-DD theo giờ Việt Nam")]):
    tz = ZoneInfo(ctx.settings.timezone)
    start = _to_utc(datetime.combine(day, time.min, tz), tz)
    meals = db.scalars(select(Meal).where(Meal.device_id == device, Meal.eaten_at >= start,
                                          Meal.eaten_at < start + timedelta(days=1)).order_by(Meal.eaten_at)).all()
    s = ctx.settings

    def tot(g: int, k: int) -> dict:
        return dict(grams=g, kcal=k, error_pct=s.error_pct, daily_pct=round(100 * k / s.daily_kcal))

    out = []
    for m in meals:
        out.append(dict(
            meal_id=m.meal_id, total_g=m.total_g, total_kcal=m.total_kcal, total=tot(m.total_g, m.total_kcal),
            model_version=m.model_version, eaten_at=m.eaten_at.replace(tzinfo=timezone.utc).astimezone(tz),
            items=[dict(cls=i.cls, name=ctx.catalog.name(i.cls), grams=i.grams, kcal=i.kcal, source=i.source,
                        orig_cls=i.orig_cls, confirmed=i.confirmed, needs_confirm=not i.confirmed) for i in m.items]))
    day_tot = tot(sum(m.total_g for m in meals), sum(m.total_kcal for m in meals))
    return dict(date=day, meals=out, total_kcal=day_tot["kcal"], daily_pct=day_tot["daily_pct"], total=day_tot)


@router.delete("/{meal_id}", status_code=204, responses={404: {"model": Error}}, summary="Xoá bữa ăn")
def delete_meal(meal_id: int, db: DbDep, device: DeviceDep):
    m = db.get(Meal, meal_id)
    if m is None or m.device_id != device:
        raise ApiError(404, "meal_not_found")
    img = m.correction.image_path if m.correction else None
    db.delete(m)
    db.commit()
    if img:  # người ăn xoá bữa -> xoá luôn ảnh đã góp
        Path(img).unlink(missing_ok=True)
    return Response(status_code=204)
