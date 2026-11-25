"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ErrorText, Notice } from "@/components/Notice";
import { MealAdviceCard } from "@/components/MealAdviceCard";
import { api, fmtTime, MEAL_SCAN_KEY, nowLocalVN, SLOTS, vnIso,
         type Dish, type Meal, type MealItemIn, type MealScan, type MealTotal, type Slot } from "@/lib/api";
import { usePatient } from "@/lib/session";

const WARNINGS: Record<string, string> = {
  no_plate: "Không thấy đĩa/khay trong ảnh, nên gram chỉ là mức trung bình. Hãy kiểm tra lại từng món.",
  no_food: "Không nhận ra món nào trong ảnh. Bạn có thể tự thêm món ở bảng dưới.",
  blurry: "Ảnh hơi mờ, nhận diện có thể sai. Chụp lại thẳng từ trên xuống sẽ tốt hơn.",
};

/** Một dòng trên bảng xác nhận. model_grams: gram mô hình đưa ra (null = người dùng tự thêm món). */
type Row = {
  key: number; no: number | null; cls: string; grams: number; model_grams: number | null; gram_method: string | null;
  confirmed: boolean; hint: string;
};

function slotFor(local: string): Slot {
  const h = Number(local.slice(11, 13));
  return h >= 4 && h < 10 ? "breakfast" : h >= 10 && h < 15 ? "lunch" : h >= 17 && h < 22 ? "dinner" : "snack";
}

let nextKey = 1;
// cùng bảng màu với meal_scan.OVERLAY_COLORS, để số trên ảnh và số ở danh sách cùng màu
const OVERLAY = ["#e6194b", "#3cb44b", "#0082c8", "#f58230", "#911eb4", "#46f0f0", "#f032e6", "#d2f53c", "#fabed4", "#008080", "#aa6e28", "#800000"];

export default function MealsPage() {
  const patient = usePatient();
  const [dishes, setDishes] = useState<Dish[]>([]);
  const [rows, setRows] = useState<Row[] | null>(null); // null: chưa mở thẻ xác nhận
  const [warnings, setWarnings] = useState<string[]>([]);
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [annotated, setAnnotated] = useState<string | null>(null); // ảnh có vùng món đánh số (data URL)
  const [total, setTotal] = useState<MealTotal | null>(null);
  const [when, setWhen] = useState(nowLocalVN());
  const [slot, setSlot] = useState<Slot>(slotFor(nowLocalVN()));
  const [meals, setMeals] = useState<Meal[]>([]);
  const [adviceVersion, setAdviceVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const names = useMemo(() => Object.fromEntries(dishes.map((d) => [d.cls, d.name])), [dishes]);
  const loadMeals = useCallback(() => {
    api.meals(patient.id).then(setMeals).catch((e) => setError(e.message));
    setAdviceVersion((v) => v + 1);
  }, [patient.id]);

  useEffect(() => {
    api.mealDishes().then((d) => setDishes([...d].sort((a, b) => a.name.localeCompare(b.name, "vi"))))
      .catch((e) => setError(e.message));
    loadMeals();
  }, [loadMeals]);

  useEffect(() => {
    if (!photo) return setPreview(null);
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  const items: MealItemIn[] = useMemo(
    () => (rows ?? []).filter((r) => r.cls).map((r) => ({ cls: r.cls, grams: r.grams, model_grams: r.model_grams, gram_method: r.gram_method })),
    [rows]);

  // khoảng tinh bột tính ở máy chủ (cùng bảng, cùng sai số với Streamlit), cập nhật khi sửa món/gram
  useEffect(() => {
    if (!rows) return;
    if (!items.length) return setTotal(null);
    const t = setTimeout(() => api.mealEstimate(patient.id, items).then(setTotal).catch((e) => setError(e.message)), 300);
    return () => clearTimeout(t);
  }, [items, rows, patient.id]);

  function open(newRows: Row[], w: string[] = []) {
    setRows(newRows);
    setWarnings(w);
    setSaved(null);
    setError(null);
    const now = nowLocalVN();
    setWhen(now);
    setSlot(slotFor(now));
  }

  function openScan(res: MealScan) {
      setAnnotated(res.annotated_png ? `data:image/png;base64,${res.annotated_png}` : null);
      open(res.items.map((it) => ({
        key: nextKey++, no: it.no, cls: it.cls ?? "", grams: it.grams, model_grams: it.grams, gram_method: it.gram_method,
        confirmed: !it.needs_confirm,
        hint: it.needs_confirm
          ? "cần xác nhận" + (it.suggestions.length ? ` (có thể là: ${it.suggestions.slice(0, 3).map((s) => names[s] ?? s).join(", ")})` : "")
          : it.conf != null ? `tin cậy ${Math.round(it.conf * 100)}%` : "",
      })), res.warnings);
  }

  // ảnh bữa ăn gửi từ ô chat trang Tư vấn: kết quả nhận diện đã có sẵn, mở thẻ xác nhận luôn
  useEffect(() => {
    if (!dishes.length) return;
    const raw = sessionStorage.getItem(MEAL_SCAN_KEY);
    if (!raw) return;
    sessionStorage.removeItem(MEAL_SCAN_KEY);
    try { openScan(JSON.parse(raw)); } catch { /* bỏ qua dữ liệu hỏng */ }
  }, [dishes]);  // eslint-disable-line react-hooks/exhaustive-deps

  async function scan() {
    if (!photo) return;
    setBusy(true);
    setError(null);
    try {
      openScan(await api.mealScan(photo, photo.name || "khay.jpg"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function patch(key: number, p: Partial<Row>) {
    setRows((rs) => rs && rs.map((r) => (r.key === key ? { ...r, ...p } : r)));
  }

  function addRow() {
    setRows((rs) => [...(rs ?? []), { key: nextKey++, no: null, cls: "", grams: 100, model_grams: null, gram_method: null, confirmed: true, hint: "bạn tự thêm" }]);
  }

  function close() {
    setRows(null);
    setTotal(null);
    setPhoto(null);
    setAnnotated(null);
    setWarnings([]);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const t = await api.addMeal(patient.id, { items, eaten_at: vnIso(when)!, slot });
      setSaved(`Đã lưu bữa ăn (khoảng ${t.carb_low}–${t.carb_high} g tinh bột). Nhớ đo đường huyết 1–2 giờ sau ăn để biết bữa này ảnh hưởng thế nào nhé.`);
      close();
      loadMeals();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const pending = (rows ?? []).filter((r) => !r.confirmed || !r.cls).length;
  const riceMean = (rows ?? []).some((r) => r.cls === "rice" && r.model_grams === r.grams &&
                                       (r.gram_method === "rice_mean" || r.gram_method === "class_mean"));
  const today = meals.filter((m) => m.eaten_at.slice(0, 10) === nowLocalVN().slice(0, 10));

  return (
    <>
      <div className="page-title">
        <h1>Bữa ăn</h1>
        <p className="small">
          Chụp ảnh khay cơm: DiaCare nhận diện món, ước lượng gram và lượng tinh bột của bữa. Bạn kiểm tra lại từng món
          rồi mới lưu. Bữa không phải khay cơm (phở, bún, bánh mì, trái cây) thì tự nhập món.
        </p>
      </div>
      {saved && <Notice level="success">{saved}</Notice>}

      {rows === null ? (
        <section className="card stack">
          <h2>Ghi bữa ăn</h2>
          {/* hai ô: "capture" mở thẳng camera sau trên điện thoại (không chọn được ảnh cũ), ô kia chọn ảnh có sẵn */}
          <p className="small muted">Ảnh khay cơm chụp thẳng từ trên xuống, thấy trọn đĩa.</p>
          <div className="row">
            <label>
              Chụp ảnh
              <input type="file" accept="image/*" capture="environment"
                     onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
            </label>
            <label>
              Hoặc chọn ảnh có sẵn
              <input type="file" accept="image/jpeg,image/png,image/webp"
                     onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
            </label>
          </div>
          {preview && <img src={preview} alt="Ảnh khay cơm vừa chọn" style={{ maxWidth: 320, borderRadius: 8 }} />}
          <div className="row">
            <button className="btn-primary" disabled={!photo || busy} onClick={scan}>{busy ? "Đang nhận diện..." : "Nhận diện món"}</button>
            <button disabled={busy} onClick={() => { open([]); addRow(); }}>Tự nhập món (không có ảnh)</button>
          </div>
        </section>
      ) : (
        <section className="card stack" aria-label="Kiểm tra lại các món">
          <h2>Kiểm tra lại các món trước khi lưu</h2>
          {(annotated || preview) && (
            <figure style={{ margin: 0 }}>
              <img src={annotated ?? preview!} alt="Ảnh khay cơm, vùng từng món được tô màu và đánh số"
                   style={{ maxWidth: "100%", width: 420, borderRadius: 8 }} />
              {annotated && <figcaption className="small muted">Số trên ảnh trùng với số của từng món bên dưới.</figcaption>}
            </figure>
          )}
          {warnings.map((w) => WARNINGS[w] && <Notice key={w} level="warning">{WARNINGS[w]}</Notice>)}
          {riceMean && (
            <Notice level="info">
              Mô hình chưa đo được lượng <b>cơm</b> từ ảnh nên đang để mức trung bình. Cơm là phần nhiều tinh bột nhất
              bữa: hãy sửa gram theo lượng bạn thực sự ăn.
            </Notice>
          )}
          {/* mỗi món một khung (không dùng bảng): trên điện thoại ô chọn tên món cần cả chiều ngang */}
          <div className="stack" role="list" aria-label="Các món">
            {rows.map((r) => (
              <div key={r.key} role="listitem" className="meal-row">
                {r.no != null && <span className="meal-no" style={{ background: OVERLAY[(r.no - 1) % OVERLAY.length] }} aria-label={`Món số ${r.no}`}>{r.no}</span>}
                <select aria-label="Món" value={r.cls} onChange={(e) => patch(r.key, { cls: e.target.value })}>
                  <option value="">— chọn món —</option>
                  {dishes.map((d) => <option key={d.cls} value={d.cls}>{d.name}</option>)}
                </select>
                <div className="meal-row-line">
                  <label className="meal-gram">
                    <input aria-label="Gram" type="number" min={0} max={2000} step={5} value={r.grams}
                           onChange={(e) => patch(r.key, { grams: Math.max(0, Number(e.target.value) || 0) })} /> g
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={r.confirmed} onChange={(e) => patch(r.key, { confirmed: e.target.checked })} />
                    Đúng món
                  </label>
                  <button className="btn-ghost btn-small" aria-label="Bỏ món này"
                          onClick={() => setRows((rs) => rs && rs.filter((x) => x.key !== r.key))}>✕</button>
                </div>
                {r.hint && <div className="small muted">{r.hint}</div>}
              </div>
            ))}
          </div>
          <div>
            <button className="btn-small" onClick={addRow}>+ Thêm món</button>
            <span className="small muted"> Món tự thêm: nhập gram cả phần bạn ăn (cả bát phở gồm nước, cả ổ bánh mì).</span>
          </div>
          <div><b>{total ? total.text : "Chưa có món nào để tính tinh bột."}</b></div>
          <p className="small muted">
            Số tinh bột là ước lượng để theo dõi (sai số gram khoảng ±30% mỗi món), không dùng để tính liều insulin.
          </p>
          <div className="row">
            <label>
              Bữa
              <select value={slot} onChange={(e) => setSlot(e.target.value as Slot)}>
                {(Object.keys(SLOTS) as Slot[]).map((s) => <option key={s} value={s}>{SLOTS[s]}</option>)}
              </select>
            </label>
            <label>
              Giờ ăn
              <input type="datetime-local" value={when} max={nowLocalVN()} onChange={(e) => setWhen(e.target.value)} />
            </label>
          </div>
          {pending > 0 && <p className="small">Còn {pending} món chưa chọn tên hoặc chưa tích <b>Đúng món</b>.</p>}
          <div className="row">
            <button className="btn-primary" disabled={busy || pending > 0 || !items.length || !when} onClick={save}>Lưu bữa ăn</button>
            <button className="btn-ghost" disabled={busy} onClick={close}>{preview ? "Bỏ ảnh này" : "Huỷ"}</button>
          </div>
        </section>
      )}
      <ErrorText error={error} />

      <MealAdviceCard patientId={patient.id} version={adviceVersion} hideEmpty={true} />

      <section className="card stack">
        <h2>Các bữa đã ghi (7 ngày)</h2>
        {today.length > 0 && (
          <p className="small">
            Hôm nay: {today.length} bữa, khoảng {today.reduce((a, m) => a + m.carb_low, 0)}–{today.reduce((a, m) => a + m.carb_high, 0)} g tinh bột.
          </p>
        )}
        {meals.some((m) => m.measure_now) && (
          <Notice level="info">
            Bây giờ là lúc đo đường huyết sau bữa vừa ghi (1–2 giờ sau ăn). Ghi số đo ở trang Hôm nay hoặc Nhật ký với
            thời điểm “1–2 giờ sau ăn”, bảng này sẽ tự ghép vào bữa.
          </Notice>
        )}
        {meals.length === 0 ? (
          <p className="muted">Chưa có bữa nào trong 7 ngày qua.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Lúc</th><th>Bữa</th><th>Tinh bột (g)</th><th>Đường huyết sau ăn</th><th>Món</th><th /></tr>
              </thead>
              <tbody>
                {meals.map((m) => (
                  <tr key={m.id}>
                    <td>{fmtTime(m.eaten_at)}</td>
                    <td>{m.slot ? SLOTS[m.slot] : ""}</td>
                    <td>{m.carb_low}–{m.carb_high}</td>
                    <td>{m.after_meal}</td>
                    <td className="small">
                      {m.items.map((it) => (it.uncounted ? `${it.name} (chưa tính)` : `${it.name} ${Math.round(it.grams ?? 0)} g`)).join(", ")}
                    </td>
                    <td>
                      <button className="btn-ghost btn-small" aria-label="Xoá bữa ghi nhầm"
                              onClick={() => { if (confirm("Xoá bữa này?")) api.deleteMeal(patient.id, m.id).then(loadMeals).catch((e) => setError(e.message)); }}>
                        Xoá
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="small muted">Đường huyết sau ăn: lần đo đầu tiên trong khoảng 45 phút đến 3 giờ sau giờ ăn đã ghi.</p>
      </section>
    </>
  );
}
