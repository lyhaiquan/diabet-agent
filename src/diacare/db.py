import json
import sqlite3
import unicodedata
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER REFERENCES patients(id),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    ts TEXT NOT NULL,
    question TEXT,
    risk REAL,
    flags_json TEXT,
    sources_json TEXT,
    draft TEXT,
    final TEXT,
    usage_json TEXT,
    error TEXT,
    trace_json TEXT
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'rule',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_memories_patient ON memories(patient_id);
CREATE TABLE IF NOT EXISTS labs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    test TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    source TEXT NOT NULL DEFAULT 'import',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    upto_message_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rl_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    run_id INTEGER,
    ts TEXT NOT NULL,
    state_json TEXT NOT NULL,
    action TEXT NOT NULL,
    propensity REAL NOT NULL,
    explored INTEGER NOT NULL DEFAULT 0,
    mode TEXT,
    policy_version TEXT,
    reward REAL,
    rated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_rl_events_session ON rl_events(session_id);
CREATE TABLE IF NOT EXISTS rl_model (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    model_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    value REAL NOT NULL,
    value2 REAL,
    unit TEXT,
    context TEXT,
    measured_at TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_patient ON readings(patient_id, measured_at);
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    place TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS doctor_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _dumps(value):
    return json.dumps(value, ensure_ascii=False)


def _key(text):
    return unicodedata.normalize("NFC", text).casefold().strip()


class Store:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(runs)")}
        if "trace_json" not in cols:  # DB tạo từ bản cũ
            self.conn.execute("ALTER TABLE runs ADD COLUMN trace_json TEXT")
        scols = {r["name"] for r in self.conn.execute("PRAGMA table_info(summaries)")}
        if "anchor" not in scols:  # dấu nhận dạng đoạn lịch sử đã tóm tắt
            self.conn.execute("ALTER TABLE summaries ADD COLUMN anchor TEXT")
        mcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(messages)")}
        if "rl_event_id" not in mcols:  # trước khi có agent RL học từ phản hồi
            self.conn.execute("ALTER TABLE messages ADD COLUMN rl_event_id INTEGER")
        self.conn.commit()

    def close(self):
        self.conn.close()

    def save_patient(self, name, profile):
        cur = self.conn.execute(
            "INSERT INTO patients (name, profile_json, created_at) VALUES (?, ?, ?)",
            (name, _dumps(profile), _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    @staticmethod
    def _patient(row):
        return {
            "id": row["id"],
            "name": row["name"],
            "profile": json.loads(row["profile_json"]),
            "created_at": row["created_at"],
        }

    def get_patient(self, patient_id):
        row = self.conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        return self._patient(row) if row else None

    def list_patients(self):
        rows = self.conn.execute("SELECT * FROM patients ORDER BY id DESC").fetchall()
        return [self._patient(r) for r in rows]

    def start_session(self, patient_id=None):
        cur = self.conn.execute(
            "INSERT INTO sessions (patient_id, created_at) VALUES (?, ?)", (patient_id, _now())
        )
        self.conn.commit()
        return cur.lastrowid

    def add_message(self, session_id, role, content, rl_event_id=None):
        self.conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at, rl_event_id) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, _now(), rl_event_id),
        )
        self.conn.commit()

    def get_history(self, session_id, limit=50):
        """Tin nhắn trả lời có trọng tâm RL thì kèm `rl_action`, `rl_event_id` (để phạt lặp và để chấm)."""
        rows = self.conn.execute(
            "SELECT m.role, m.content, m.rl_event_id, e.action FROM messages m"
            " LEFT JOIN rl_events e ON e.id = m.rl_event_id"
            " WHERE m.session_id = ? ORDER BY m.id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        out = []
        for r in reversed(rows):
            m = {"role": r["role"], "content": r["content"]}
            if r["rl_event_id"] is not None:
                m["rl_event_id"], m["rl_action"] = r["rl_event_id"], r["action"]
            out.append(m)
        return out

    # ---- học tăng cường: quyết định, phản hồi và mô hình trực tuyến ----
    def add_rl_event(self, session_id, run_id, rl):
        cur = self.conn.execute(
            "INSERT INTO rl_events (session_id, run_id, ts, state_json, action, propensity, explored, mode,"
            " policy_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, run_id, _now(), _dumps(rl["state"]), rl["action"], rl["propensity"],
             int(bool(rl.get("explored"))), rl.get("mode"), rl.get("policy_version")),
        )
        self.conn.commit()
        return cur.lastrowid

    @staticmethod
    def _rl_event(row):
        return {"id": row["id"], "session_id": row["session_id"], "run_id": row["run_id"], "ts": row["ts"],
                "state": json.loads(row["state_json"]), "action": row["action"], "propensity": row["propensity"],
                "explored": bool(row["explored"]), "mode": row["mode"], "policy_version": row["policy_version"],
                "reward": row["reward"], "rated_at": row["rated_at"]}

    def get_rl_event(self, event_id):
        row = self.conn.execute("SELECT * FROM rl_events WHERE id = ?", (event_id,)).fetchone()
        return self._rl_event(row) if row else None

    def rate_rl_event(self, event_id, reward):
        """Ghi phần thưởng một lần duy nhất. Trả về sự kiện nếu vừa ghi, None nếu không có hoặc đã chấm."""
        cur = self.conn.execute("UPDATE rl_events SET reward = ?, rated_at = ? WHERE id = ? AND reward IS NULL",
                                (float(reward), _now(), event_id))
        self.conn.commit()
        return self.get_rl_event(event_id) if cur.rowcount == 1 else None

    def rl_events(self, limit=None):
        sql = "SELECT * FROM rl_events ORDER BY id"
        rows = self.conn.execute(sql + (f" DESC LIMIT {int(limit)}" if limit else "")).fetchall()
        return [self._rl_event(r) for r in rows]

    def save_rl_model(self, model):
        self.conn.execute("INSERT INTO rl_model (id, model_json, updated_at) VALUES (1, ?, ?)"
                          " ON CONFLICT(id) DO UPDATE SET model_json = excluded.model_json,"
                          " updated_at = excluded.updated_at", (_dumps(model), _now()))
        self.conn.commit()

    def load_rl_model(self):
        row = self.conn.execute("SELECT model_json FROM rl_model WHERE id = 1").fetchone()
        return json.loads(row["model_json"]) if row else None

    # ---- trí nhớ dài hạn & tóm tắt hội thoại ----
    def add_memory(self, patient_id, kind, content, source="rule"):
        content = unicodedata.normalize("NFC", content).strip()
        rows = self.conn.execute(
            "SELECT id, content FROM memories WHERE patient_id = ? AND kind = ?", (patient_id, kind)
        ).fetchall()
        for r in rows:
            if _key(r["content"]) == _key(content):
                self.conn.execute(
                    "UPDATE memories SET updated_at = ?, active = 1 WHERE id = ?", (_now(), r["id"]))
                self.conn.commit()
                return r["id"]
        now = _now()
        cur = self.conn.execute(
            "INSERT INTO memories (patient_id, kind, content, source, created_at, updated_at, active)"
            " VALUES (?, ?, ?, ?, ?, ?, 1)",
            (patient_id, kind, content, source, now, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def deactivate_memory_by_content(self, patient_id, kind, content):
        """Tắt thông tin đang bật có cùng loại và nội dung (so không phân biệt hoa thường). Trả về số dòng tắt."""
        n = 0
        for r in self.conn.execute("SELECT id, content FROM memories WHERE patient_id = ? AND kind = ? AND active = 1",
                                   (patient_id, kind)).fetchall():
            if _key(r["content"]) == _key(content):
                self.conn.execute("UPDATE memories SET active = 0, updated_at = ? WHERE id = ?", (_now(), r["id"]))
                n += 1
        self.conn.commit()
        return n

    def list_memories(self, patient_id, active_only=True):
        sql = "SELECT * FROM memories WHERE patient_id = ?"
        if active_only:
            sql += " AND active = 1"
        rows = self.conn.execute(sql + " ORDER BY id ASC", (patient_id,)).fetchall()
        return [{**dict(r), "active": bool(r["active"])} for r in rows]

    def deactivate_memory(self, memory_id):
        self.conn.execute(
            "UPDATE memories SET active = 0, updated_at = ? WHERE id = ?", (_now(), memory_id))
        self.conn.commit()

    # ---------- kết quả xét nghiệm ----------
    def add_lab(self, patient_id, test, value, unit=None, source="import"):
        cur = self.conn.execute(
            "INSERT INTO labs (patient_id, test, value, unit, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (patient_id, test, float(value), unit, source, _now()))
        self.conn.commit()
        return cur.lastrowid

    def list_labs(self, patient_id):
        rows = self.conn.execute(
            "SELECT * FROM labs WHERE patient_id = ? ORDER BY id ASC", (patient_id,)).fetchall()
        return [dict(r) for r in rows]

    def latest_labs(self, patient_id):
        """Giá trị mới nhất của mỗi loại xét nghiệm, theo thứ tự nhập."""
        latest = {}
        for r in self.list_labs(patient_id):
            latest.pop(r["test"], None)
            latest[r["test"]] = r
        return list(latest.values())

    def clear_labs(self, patient_id):
        self.conn.execute("DELETE FROM labs WHERE patient_id = ?", (patient_id,))
        self.conn.commit()

    # ---------- nhật ký tự theo dõi (đường huyết mg/dL, huyết áp, cân nặng) ----------
    def add_reading(self, patient_id, kind, value, measured_at, value2=None, unit=None, context=None, note=None):
        """measured_at: thời điểm đo (người dùng có thể ghi bù), chuỗi ISO có múi giờ."""
        if hasattr(measured_at, "isoformat"):
            measured_at = measured_at.isoformat()
        cur = self.conn.execute(
            "INSERT INTO readings (patient_id, kind, value, value2, unit, context, measured_at, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (patient_id, kind, float(value), None if value2 is None else float(value2), unit, context,
             measured_at, note, _now()))
        self.conn.commit()
        return cur.lastrowid

    def list_readings(self, patient_id, kind=None):
        sql, args = "SELECT * FROM readings WHERE patient_id = ?", [patient_id]
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        rows = self.conn.execute(sql + " ORDER BY measured_at ASC, id ASC", args).fetchall()
        return [dict(r) for r in rows]

    def delete_reading(self, reading_id, patient_id):
        self.conn.execute("DELETE FROM readings WHERE id = ? AND patient_id = ?", (reading_id, patient_id))
        self.conn.commit()

    def set_appointment(self, patient_id, date, place=None, note=None):
        """Lịch tái khám sắp tới; lịch mới thay lịch cũ (giữ lại trong bảng để xem lại)."""
        cur = self.conn.execute(
            "INSERT INTO appointments (patient_id, date, place, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (patient_id, str(date), place, note, _now()))
        self.conn.commit()
        return cur.lastrowid

    def get_appointment(self, patient_id):
        row = self.conn.execute(
            "SELECT * FROM appointments WHERE patient_id = ? ORDER BY id DESC LIMIT 1", (patient_id,)).fetchone()
        return dict(row) if row else None

    def add_doctor_question(self, patient_id, text):
        cur = self.conn.execute(
            "INSERT INTO doctor_questions (patient_id, text, created_at) VALUES (?, ?, ?)",
            (patient_id, text.strip(), _now()))
        self.conn.commit()
        return cur.lastrowid

    def list_doctor_questions(self, patient_id, include_done=False):
        sql = "SELECT * FROM doctor_questions WHERE patient_id = ?" + ("" if include_done else " AND done = 0")
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY id ASC", (patient_id,)).fetchall()]

    def mark_doctor_question(self, question_id, done=True):
        self.conn.execute("UPDATE doctor_questions SET done = ? WHERE id = ?", (int(done), question_id))
        self.conn.commit()

    def save_summary(self, session_id, upto_message_index, content, anchor=None):
        cur = self.conn.execute(
            "INSERT INTO summaries (session_id, upto_message_index, content, created_at, anchor)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_id, upto_message_index, content, _now(), anchor),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_summary(self, session_id):
        row = self.conn.execute(
            "SELECT * FROM summaries WHERE session_id = ? ORDER BY id DESC LIMIT 1", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def log_run(self, session_id, state, error=None):
        cur = self.conn.execute(
            "INSERT INTO runs (session_id, ts, question, risk, flags_json, sources_json, draft, final, usage_json, error,"
            " trace_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                _now(),
                state.question,
                state.risk,
                _dumps(state.flags),
                _dumps([d["source"] for d in state.docs]),
                state.draft,
                state.final,
                _dumps(state.usage),
                error,
                _dumps(getattr(state, "trace", [])),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def runs(self, limit=100):
        rows = self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "ts": r["ts"],
                "question": r["question"],
                "risk": r["risk"],
                "flags": json.loads(r["flags_json"] or "[]"),
                "sources": json.loads(r["sources_json"] or "[]"),
                "draft": r["draft"],
                "final": r["final"],
                "usage": json.loads(r["usage_json"] or "{}"),
                "error": r["error"],
                "trace": json.loads(r["trace_json"] or "[]"),
            }
            for r in rows
        ]

    def run_stats(self):
        rows = self.conn.execute("SELECT flags_json, usage_json, error FROM runs").fetchall()
        flag_counts = {}
        sums = {"prompt_tokens": [], "completion_tokens": [], "seconds": []}
        errors = 0
        for r in rows:
            if r["error"]:
                errors += 1
            for flag in json.loads(r["flags_json"] or "[]"):
                flag_counts[flag] = flag_counts.get(flag, 0) + 1
            usage = json.loads(r["usage_json"] or "{}")
            if usage:
                for key, values in sums.items():
                    if usage.get(key) is not None:
                        values.append(usage[key])

        def avg(values):
            return sum(values) / len(values) if values else None

        return {
            "runs": len(rows),
            "errors": errors,
            "avg_prompt_tokens": avg(sums["prompt_tokens"]),
            "avg_completion_tokens": avg(sums["completion_tokens"]),
            "avg_seconds": avg(sums["seconds"]),
            "flag_counts": flag_counts,
        }
