"""Best-effort checkpoint snapshot chain: Redis -> SQLite -> process memory."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class CheckpointStore:
    def __init__(self) -> None:
        path = Path(os.getenv("DATABASE_PATH", "./data/checkpoints.sqlite3"))
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.memory: dict[str, dict[str, Any]] = {}
        with sqlite3.connect(self.path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(graph_checkpoints)").fetchall()}
            legacy_rows = []
            if columns and "id" not in columns:
                legacy_rows = conn.execute("SELECT thread_id,node,body,created_at FROM graph_checkpoints ORDER BY created_at").fetchall()
                conn.execute("DROP TABLE graph_checkpoints")
            conn.execute("CREATE TABLE IF NOT EXISTS graph_checkpoints (id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL, node TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL)")
            if legacy_rows:
                conn.executemany("INSERT INTO graph_checkpoints(thread_id,node,body,created_at) VALUES(?,?,?,?)", legacy_rows)
        self.redis = None
        url = os.getenv("REDIS_URL", "").strip()
        if url:
            try:
                import redis
                self.redis = redis.Redis.from_url(url, decode_responses=True, socket_timeout=.5)
                self.redis.ping()
            except Exception:
                self.redis = None

    def save(self, thread_id: str, node: str, state: dict[str, Any]) -> str:
        body = json.dumps(state, ensure_ascii=False, default=str)
        key = f"thesis:checkpoint:{thread_id}:{node}"
        if self.redis:
            try:
                self.redis.setex(key, 60 * 60 * 24 * 7, body)
                self.redis.setex(f"thesis:checkpoint:{thread_id}:latest", 60 * 60 * 24 * 7, key)
                return "redis"
            except Exception:
                self.redis = None
        try:
            with sqlite3.connect(self.path, timeout=1) as conn:
                conn.execute("INSERT INTO graph_checkpoints(thread_id,node,body,created_at) VALUES(?,?,?,?)", (thread_id, node, body, datetime.now().isoformat(timespec="microseconds")))
            return "sqlite"
        except Exception:
            self.memory[key] = state
            return "memory"

    def latest(self, thread_id: str) -> dict[str, Any] | None:
        if self.redis:
            try:
                latest_key = self.redis.get(f"thesis:checkpoint:{thread_id}:latest")
                if latest_key:
                    body = self.redis.get(latest_key)
                    if body:
                        return json.loads(body)
            except Exception:
                self.redis = None
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT body FROM graph_checkpoints WHERE thread_id=? ORDER BY id DESC LIMIT 1", (thread_id,)).fetchone()
        if row:
            return json.loads(row[0])
        return next((v for k, v in self.memory.items() if k.startswith(f"thesis:checkpoint:{thread_id}:")), None)
