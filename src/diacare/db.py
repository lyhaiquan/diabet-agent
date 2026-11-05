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
    error TEXT
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
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    upto_message_index INTEGER NOT NULL,
    content TEXT NOT NULL,
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

    def add_message(self, session_id, role, content):
        self.conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, _now()),
        )
        self.conn.commit()

    def get_history(self, session_id, limit=50):
        rows = self.conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

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

    def save_summary(self, session_id, upto_message_index, content):
        cur = self.conn.execute(
            "INSERT INTO summaries (session_id, upto_message_index, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, upto_message_index, content, _now()),
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
            "INSERT INTO runs (session_id, ts, question, risk, flags_json, sources_json, draft, final, usage_json, error)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
