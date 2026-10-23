"""Small local retrieval corpus for the no-credentials demo."""
from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parents[1] / "data" / "library.json"
DOCS: list[dict[str, Any]] = json.loads(DATA.read_text(encoding="utf-8"))
TOKEN = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")


def tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(text or "")]


def sparse_score(query: list[str], doc: dict[str, Any]) -> float:
    text = " ".join([doc["title"], doc["abstract"], *doc.get("keywords", [])])
    counts = Counter(tokens(text))
    return sum(1.0 + math.log1p(counts[t]) for t in query)


def dense_score(query: list[str], doc: dict[str, Any]) -> float:
    """Hash-vector cosine proxy, deterministic for an offline showcase (not a learned embedding)."""
    q = Counter(query)
    d = Counter(tokens(" ".join([doc["title"], doc["abstract"], *doc.get("keywords", [])])))
    overlap = sum(min(q[t], d[t]) for t in q.keys() & d.keys())
    return overlap / max(1, math.sqrt(sum(q.values()) * sum(d.values())))


def retrieve_local(query: str, discipline: str = "", k: int = 5) -> list[dict[str, Any]]:
    terms = tokens(query)
    if not terms:
        terms = ["研究", "论文"]
    scored = []
    for doc in DOCS:
        lexical = sparse_score(terms, doc)
        semantic = dense_score(terms, doc)
        metadata_boost = .2 if discipline and discipline in doc.get("discipline", "") else 0
        # Three-stage demo: sparse+dense candidate scoring, metadata boost, compact rerank.
        score = .55 * min(1.0, lexical / 12) + .35 * semantic + metadata_boost
        scored.append((score, doc))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [{**doc, "score": round(score, 3)} for score, doc in scored[:k]]


def retrieve(query: str, discipline: str = "", k: int = 5) -> list[dict[str, Any]]:
    """Use RAGFlow when explicitly configured; fall back to local sample corpus on outage."""
    base = os.getenv("RAGFLOW_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("RAGFLOW_API_KEY", "").strip()
    dataset_ids = [item.strip() for item in os.getenv("RAGFLOW_DATASET_IDS", "").split(",") if item.strip()]
    if base and api_key and dataset_ids:
        for attempt in range(3):
            try:
                payload = {"question": query, "dataset_ids": dataset_ids, "page": 1, "page_size": k,
                           "similarity_threshold": .1, "vector_similarity_weight": .5,
                           "knn_top_k": max(10, k), "rerank_candidates_count": max(10, k)}
                request = urllib.request.Request(f"{base}/api/v1/retrieval", data=json.dumps(payload).encode(),
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=8) as response:
                    result = json.loads(response.read().decode("utf-8"))
                data = result.get("data") or {}
                chunks = data.get("chunks") or data.get("records") or []
                if result.get("code", 0) != 0:
                    raise ValueError("RAGFlow returned a non-success business code")
                mapped = []
                for i, chunk in enumerate(chunks[:k]):
                    mapped.append({"id": str(chunk.get("id") or f"RF-{i+1}"),
                        "title": str(chunk.get("doc_name") or chunk.get("document_name") or "RAGFlow 文档片段"),
                        "author": str((chunk.get("metadata") or {}).get("author") or "RAGFlow 语料"),
                        "year": int((chunk.get("metadata") or {}).get("year") or 0),
                        "source": str(chunk.get("doc_name") or "RAGFlow 文档"),
                        "abstract": str(chunk.get("content") or chunk.get("content_with_weight") or ""),
                        "keywords": [], "score": round(float(chunk.get("similarity") or chunk.get("score") or 0), 3)})
                if mapped:
                    return mapped
            except Exception:
                if attempt < 2:
                    import time
                    time.sleep(.2 * (2 ** attempt))
    return retrieve_local(query, discipline, k)
