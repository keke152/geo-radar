"""Track explicit quality feedback and draft a skill proposal after repeated failures."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import yaml


class BehaviorTracker:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS agent_feedback (id INTEGER PRIMARY KEY, thread_id TEXT, agent TEXT, helpful INTEGER, note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")

    def record(self, thread_id: str, agent: str, helpful: bool, note: str) -> dict[str, str] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT INTO agent_feedback(thread_id,agent,helpful,note) VALUES(?,?,?,?)", (thread_id, agent, int(helpful), note[:500]))
            recent = conn.execute("SELECT helpful,note FROM agent_feedback WHERE agent=? ORDER BY id DESC LIMIT 3", (agent,)).fetchall()
        if helpful or len(recent) < 3 or any(row[0] for row in recent):
            return None
        seed = re.sub(r"[^a-z0-9-]+", "-", (note.lower() or "needs-review"))[:32].strip("-") or "needs-review"
        name = f"proposal-{agent}-{seed}"
        folder = Path(__file__).resolve().parents[1] / "skills" / "proposals"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}.yaml"
        record = {"name": name, "status": "pending-human-review", "source": "three consecutive negative user ratings",
                  "instructions": ["Review the recent agent feedback before activating this skill.",
                                   "Add a concrete quality rule that addresses the reported issue.",
                                   "Run a human review on generated output before approval."],
                  "sample_feedback": [row[1] for row in reversed(recent) if row[1]]}
        path.write_text(yaml.safe_dump(record, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return {"name": name, "path": str(path), "status": "pending-human-review"}
