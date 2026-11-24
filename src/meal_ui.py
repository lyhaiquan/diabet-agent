"""Trang Bữa ăn: chụp/tải ảnh khay cơm -> Calo Khay nhận diện món và gram -> người dùng xác nhận/sửa -> DiaCare tính
khoảng tinh bột và lưu bữa. Phần tính toán nằm ở diacare.meal_scan; ở đây chỉ vẽ giao diện."""
from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as st

from diacare import journal, meal_scan

SCAN = "meal_scan"
SLOTS = {"breakfast": "Bữa sáng", "lunch": "Bữa trưa", "dinner": "Bữa tối", "snack": "Bữa phụ"}
DISCLAIMER = ("Số tinh bột là **ước lượng để theo dõi** (sai số gram khoảng ±30% mỗi món), không dùng để tính liều "
              "insulin.")
WARNINGS = {
    "no_plate": "Không thấy đĩa/khay trong ảnh, nên gram chỉ là mức trung bình. Hãy kiểm tra lại từng món.",
    "no_food": "Không nhận ra món nào trong ảnh. Bạn có thể tự thêm món ở bảng dưới.",
    "blurry": "Ảnh hơi mờ, nhận diện có thể sai. Chụp lại thẳng từ trên xuống sẽ tốt hơn.",
}


@st.cache_data
def _table():
    return meal_scan.load_table()


def _slot_for(now):
    h = now.hour
    return "breakfast" if 4 <= h < 10 else "lunch" if 10 <= h < 15 else "dinner" if 17 <= h < 22 else "snack"


def _hint(it, table):
    if it.get("needs_confirm"):
        alts = [table[s]["name"] for s in it.get("suggestions", [])][:3]
        return "cần xác nhận" + (f" (có thể là: {', '.join(alts)})" if alts else "")
    return f"tin cậy {it['conf']:.0%}" if it.get("conf") is not None else ""


def to_frame(items, table):
    # kiểu cột ghi rõ: bảng rỗng (tự nhập món) thì pandas đoán "object" và data_editor từ chối cột checkbox
    return pd.DataFrame({
        "Món": pd.Series([it["name"] for it in items], dtype="object"),
        "Gram": pd.Series([int(it["grams"]) for it in items], dtype="int64"),
        "Đúng món": pd.Series([not it.get("needs_confirm") for it in items], dtype="bool"),
        "Ghi chú": pd.Series([_hint(it, table) for it in items], dtype="object"),
    })


def rows_to_items(df, original, table):
    """Bảng người dùng đã sửa -> danh sách món. Món đổi tên hoặc gram đổi so với mô hình thì tính là người dùng nhập
    (sai số gram nhỏ hơn). Trả về (items, số món chưa xác nhận, tên món không có trong bảng).

    Ghép với món gốc theo NHÃN dòng (data_editor giữ nhãn dòng cũ khi xoá dòng, dòng thêm có nhãn mới), không theo
    thứ tự: xoá một món nhận nhầm không được làm các dòng sau "đổi gram". Chỉ gram quyết định nguồn gram; đổi tên món
    giữ nguyên gram của mô hình thì vẫn là sai số của mô hình."""
    by_name = {v["name"]: k for k, v in table.items()}
    items, pending, unknown = [], 0, []
    for i, row in df.iterrows():
        name = row.get("Món")
        if not isinstance(name, str) or not name.strip():
            continue
        cls = by_name.get(name)
        if cls is None:
            unknown.append(name)
            continue
        try:
            grams = max(0, int(row.get("Gram") or 0))
        except (TypeError, ValueError):
            grams = 0
        orig = original[i] if isinstance(i, int) and 0 <= i < len(original) else None
        same = orig is not None and int(orig["grams"]) == grams
        if orig is not None and not bool(row.get("Đúng món")):  # dòng người dùng tự thêm thì đã là món họ chọn
            pending += 1
        items.append({"cls": cls, "name": name, "grams": grams, "gram_source": "model" if same else "user",
                      "gram_method": orig.get("gram_method") if same else None})
    return items, pending, unknown


def _scan_upload(table):
    src = st.radio("Ảnh khay cơm", ["Tải ảnh lên", "Chụp bằng camera"], horizontal=True, key="meal_src")
    if src == "Tải ảnh lên":
        f = st.file_uploader("Ảnh khay cơm (JPG/PNG), chụp thẳng từ trên xuống, thấy trọn đĩa",
                             type=["jpg", "jpeg", "png", "webp"], key="meal_file")
    else:
        f = st.camera_input("Chụp khay cơm", key="meal_cam")
    if f is None:
        return
    if st.button("Nhận diện món", type="primary", key="meal_scan_btn"):
        with st.spinner("Đang nhận diện món..."):
            try:
                res = meal_scan.scan(f.getvalue(), f.name or "khay.jpg", f.type or "image/jpeg")
            except meal_scan.CaloKhayError as e:
                st.error(str(e))
                return
        n = st.session_state.get("meal_scan_n", 0) + 1
        st.session_state["meal_scan_n"] = n
        st.session_state[SCAN] = {"n": n, "items": meal_scan.items_from_scan(res, table),
                                  "warnings": res.get("warnings", []), "image": f.getvalue()}
        st.rerun()  # ẩn ô tải ảnh, chỉ còn thẻ xác nhận


def _confirm(store, patient_id, table):
    scan = st.session_state.get(SCAN)
    if not scan:
        return
    n, items = scan["n"], scan["items"]
    with st.container(border=True):
        st.markdown("**Kiểm tra lại các món trước khi lưu**")
        if scan.get("image"):
            st.image(scan["image"], width=320)
        elif not items:
            st.caption("Bấm dấu **+** ở cuối bảng để thêm món, chọn tên món rồi nhập số gram cả phần bạn ăn "
                       "(cả bát phở gồm nước, cả ổ bánh mì).")
        for w in scan.get("warnings", []):
            if w in WARNINGS:
                st.warning(WARNINGS[w])
        if any(it["cls"] == "rice" and it.get("gram_method") in ("rice_mean", "class_mean") for it in items):
            st.info("Mô hình chưa đo được lượng **cơm** từ ảnh nên đang để mức trung bình. Cơm là phần nhiều tinh bột "
                    "nhất bữa: hãy sửa cột Gram theo lượng bạn thực sự ăn.")
        names = sorted(v["name"] for v in table.values())
        df = st.data_editor(
            to_frame(items, table), key=f"meal_edit_{n}", num_rows="dynamic", hide_index=True,
            use_container_width=True,
            column_config={
                "Món": st.column_config.SelectboxColumn("Món", options=names, required=True),
                "Gram": st.column_config.NumberColumn("Gram", min_value=0, max_value=2000, step=5, required=True),
                "Đúng món": st.column_config.CheckboxColumn("Đúng món", help="Tích khi bạn đã kiểm tra món này"),
                "Ghi chú": st.column_config.TextColumn("Ghi chú", disabled=True),
            })
        edited, pending, unknown = rows_to_items(df, items, table)
        total = meal_scan.meal_carbs(edited, table)
        st.markdown(meal_scan.carb_text(total))
        st.caption(DISCLAIMER)
        now = journal.now_vn()
        c1, c2, c3 = st.columns(3)
        slot = c1.selectbox("Bữa", list(SLOTS), index=list(SLOTS).index(_slot_for(now)), format_func=SLOTS.get,
                            key=f"meal_slot_{n}")
        d = c2.date_input("Ngày ăn", value=now.date(), max_value=now.date(), key=f"meal_date_{n}", format="DD/MM/YYYY")
        t = c3.time_input("Giờ ăn", value=time(now.hour, now.minute), key=f"meal_time_{n}", step=300)
        if pending:
            st.caption(f"Còn {pending} món chưa tích **Đúng món**: kiểm tra (đổi tên nếu sai) rồi tích để lưu.")
        b1, b2 = st.columns(2)
        if b1.button("Lưu bữa ăn", type="primary", key=f"meal_save_{n}", disabled=bool(pending) or not edited):
            when = min(datetime.combine(d, t, tzinfo=journal.VN_TZ), now)
            store.add_meal(patient_id, when, slot, total["items"] + [{"name": u, "uncounted": True}
                                                                     for u in total["uncounted"]],
                           total["carb_g"], total["carb_low"], total["carb_high"], total["kcal"])
            st.session_state.pop(SCAN, None)
            st.session_state["meal_saved"] = True
            st.rerun()
        if b2.button("Bỏ ảnh này" if scan.get("image") else "Huỷ", key=f"meal_drop_{n}"):
            st.session_state.pop(SCAN, None)
            st.rerun()


def _history(store, patient_id):
    meals = store.list_meals(patient_id)
    if not meals:
        return
    now = journal.now_vn()
    recent = [m for m in meals if journal.to_vn(m["eaten_at"]) >= now - timedelta(days=7)]
    st.markdown("**Các bữa đã ghi (7 ngày)**")
    if not recent:
        st.caption("Chưa có bữa nào trong 7 ngày qua.")
        return
    today = [m for m in recent if journal.to_vn(m["eaten_at"]).date() == now.date()]
    if today:
        lo, hi = sum(m["carb_low"] for m in today), sum(m["carb_high"] for m in today)
        st.caption(f"Hôm nay: {len(today)} bữa, khoảng {lo:.0f}–{hi:.0f} g tinh bột.")
    targets = journal.resolve_targets(store.get_targets(patient_id))
    pairs = meal_scan.pair_after_meal(recent, store.list_readings(patient_id), targets)
    rows = []
    for p in reversed(pairs):
        m = p["meal"]
        when = journal.to_vn(m["eaten_at"])
        dishes = ", ".join(f"{it['name']} {it['grams']:.0f} g" if not it.get("uncounted") else f"{it['name']} (chưa tính)"
                           for it in m["items"])
        rows.append({"Lúc": f"{when:%d/%m %H:%M}", "Bữa": SLOTS.get(m["slot"], m["slot"] or ""),
                     "Tinh bột (g)": f"{m['carb_low']:.0f}–{m['carb_high']:.0f}",
                     "Đường huyết sau ăn": meal_scan.after_meal_text(p, targets), "Món": dishes})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    waiting = [p for p in pairs if p["reading"] is None
               and timedelta(minutes=meal_scan.AFTER_MIN) <= now - journal.to_vn(p["meal"]["eaten_at"])
               <= timedelta(minutes=meal_scan.AFTER_MAX)]
    if waiting:
        st.info("Bây giờ là lúc đo đường huyết sau bữa vừa ghi (1–2 giờ sau ăn). Ghi số đo ở tab **Hôm nay** hoặc "
                "**Nhật ký** với thời điểm \"1–2 giờ sau ăn\", bảng này sẽ tự ghép vào bữa.")
    st.caption("Đường huyết sau ăn: lần đo đầu tiên trong khoảng 45 phút đến 3 giờ sau giờ ăn đã ghi.")
    with st.expander("Xoá một bữa ghi nhầm"):
        opts = {m["id"]: f"{journal.to_vn(m['eaten_at']):%d/%m %H:%M} · {SLOTS.get(m['slot'], '')}"
                for m in reversed(recent)}
        mid = st.selectbox("Bữa", list(opts), format_func=opts.get, key="meal_del_pick")
        if st.button("Xoá bữa này", key="meal_del_btn"):
            store.delete_meal(mid, patient_id)
            st.rerun()


def render_meal(store, patient_id):
    if patient_id is None:
        st.info("Hãy tạo hồ sơ ở thanh bên để bắt đầu.")
        return
    st.subheader("Bữa ăn")
    st.caption("Chụp ảnh khay cơm: DiaCare nhận diện món (Calo Khay), ước lượng gram và lượng tinh bột của bữa. "
               "Bạn kiểm tra lại từng món rồi mới lưu. Bữa không phải khay cơm (phở, bún, bánh mì, trái cây) thì "
               "tự nhập món.")
    if st.session_state.pop("meal_saved", False):
        st.success("Đã lưu bữa ăn. Nhớ đo đường huyết 1–2 giờ sau ăn để biết bữa này ảnh hưởng thế nào nhé.")
    table = _table()
    if not st.session_state.get(SCAN):
        _scan_upload(table)
        if st.button("Tự nhập món (không có ảnh)", key="meal_manual_btn",
                     help="Cho bữa không phải khay cơm (phở, bún, bánh mì, trái cây...): chọn món và gram ở bảng"):
            n = st.session_state.get("meal_scan_n", 0) + 1
            st.session_state["meal_scan_n"] = n
            st.session_state[SCAN] = {"n": n, "items": [], "warnings": [], "image": None}
            st.rerun()
    _confirm(store, patient_id, table)
    _history(store, patient_id)
