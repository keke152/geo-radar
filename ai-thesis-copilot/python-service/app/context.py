"""Four-pass deterministic context compaction with durable archive of dropped messages."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


def estimate_tokens(text: str) -> int:
    # A lightweight display estimate, not a model tokenizer.
    return max(1, round(len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+|[^\s]", text)) * .72))


def extractive_summary(text: str, budget: int) -> str:
    sentences = re.split(r"(?<=[。！？.!?])\s*", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return text[:max(1, budget * 2)]
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text.lower())
    freq: dict[str, int] = {}
    for token in tokens:
        freq[token] = freq.get(token, 0) + 1
    ranked = sorted(enumerate(sentences), key=lambda item: (sum(freq.get(t, 0) for t in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", item[1].lower())) / max(1, len(item[1])), -item[0]), reverse=True)
    keep: list[tuple[int, str]] = []
    used = 0
    for index, sentence in ranked:
        cost = estimate_tokens(sentence)
        if used + cost <= budget or not keep:
            keep.append((index, sentence)); used += cost
    return " ".join(sentence for _, sentence in sorted(keep))


class ContextManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS context_archive (id INTEGER PRIMARY KEY, thread_id TEXT, role TEXT, content TEXT, archived_at TEXT)")

    def compact(self, thread_id: str, messages: list[dict[str, str]], max_tokens: int = 1800) -> dict[str, Any]:
        original_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
        if original_tokens <= max_tokens:
            return {"messages": messages, "strategy": ["完整保留"], "original_tokens": original_tokens,
                    "compressed_tokens": original_tokens, "ratio": 1.0, "archived_count": 0}
        # Level 1: retain system messages and a recent conversational window.
        system = [m for m in messages if m.get("role") == "system"][:2]
        recent: list[dict[str, str]] = []
        used = sum(estimate_tokens(m.get("content", "")) for m in system)
        for message in reversed([m for m in messages if m.get("role") != "system"]):
            cost = estimate_tokens(message.get("content", ""))
            if used + cost > max_tokens:
                break
            recent.insert(0, message); used += cost
        retained = [*system, *recent]
        strategy = ["窗口裁剪"]
        # Level 2: collapse adjacent messages from the same role.
        merged: list[dict[str, str]] = []
        for message in retained:
            if merged and merged[-1].get("role") == message.get("role") and message.get("role") != "system":
                merged[-1] = {"role": message["role"], "content": merged[-1]["content"] + "\n" + message.get("content", "")}
            else:
                merged.append(dict(message))
        if len(merged) != len(retained):
            strategy.append("相邻轮次合并")
        retained = merged
        # Level 3: extract the most information-dense sentences under the budget.
        if sum(estimate_tokens(m["content"]) for m in retained) > max_tokens:
            target = max(120, max_tokens // max(1, len(retained)))
            for message in retained:
                if message.get("role") != "system":
                    message["content"] = extractive_summary(message["content"], target)
            strategy.append("抽取式摘要")
        # Level 4: archive omitted history and preserve a compact long-term summary.
        kept_contents = {m.get("content") for m in retained}
        archived = [m for m in messages if m.get("content") not in kept_contents]
        if archived:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany("INSERT INTO context_archive(thread_id,role,content,archived_at) VALUES(?,?,?,?)",
                                 [(thread_id, m.get("role", "user"), m.get("content", ""), datetime.now().isoformat(timespec="seconds")) for m in archived])
            strategy.append("归档旧上下文")
        final_tokens = sum(estimate_tokens(m.get("content", "")) for m in retained)
        return {"messages": retained, "strategy": strategy, "original_tokens": original_tokens,
                "compressed_tokens": final_tokens, "ratio": round(final_tokens / max(1, original_tokens), 3),
                "archived_count": len(archived), "summary": " ".join(m["content"] for m in retained[-3:])[:1200]}
