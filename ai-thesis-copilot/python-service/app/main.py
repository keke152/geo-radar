from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .checkpoint import CheckpointStore
from .behavior import BehaviorTracker
from .context import ContextManager
from .rag import DOCS, retrieve
from .skills import load_active_skills
from .workflow import run_workflow

ROOT = Path(__file__).resolve().parents[1]
POLICY = yaml.safe_load((Path(__file__).parent / "policy.yaml").read_text(encoding="utf-8"))
checkpoints = CheckpointStore()
behavior = BehaviorTracker(checkpoints.path)
contexts = ContextManager(checkpoints.path)
windows: dict[str, deque[float]] = defaultdict(deque)
app = FastAPI(title="学术同行 AI 论文辅助系统", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


class WorkflowRequest(BaseModel):
    title: str = Field(min_length=4, max_length=200)
    discipline: str = Field(default="", max_length=80)
    research_question: str = Field(default="", max_length=500)
    goal: str = Field(default="生成论文初稿", max_length=100)
    thread_id: str | None = None
    resume_from_checkpoint: bool = False


class FeedbackRequest(BaseModel):
    thread_id: str = Field(min_length=6, max_length=80)
    agent: str = Field(default="writing", pattern="^(topic|retrieval|outline|writing|format|review)$")
    helpful: bool
    note: str = Field(default="", max_length=500)


class CompactRequest(BaseModel):
    thread_id: str = Field(min_length=6, max_length=80)
    messages: list[dict[str, str]] = Field(min_length=1, max_length=200)
    max_tokens: int = Field(default=1800, ge=100, le=12000)


def check_access(role: str, scope: str, user_id: str = "demo-researcher") -> None:
    role = role if role in POLICY["roles"] else POLICY["defaults"]["demo_role"]
    allowed = POLICY["roles"][role]["allow"]
    if "*" not in allowed and scope not in allowed:
        raise HTTPException(403, "当前角色没有此操作权限")
    auth_url = os.getenv("JAVA_AUTH_URL", "").strip().rstrip("/")
    if auth_url:
        body = json.dumps({"userId": user_id, "role": role, "scope": scope}).encode()
        request = urllib.request.Request(f"{auth_url}/api/auth/authorize", data=body,
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=1.5) as response:
                if not json.loads(response.read().decode()).get("allowed"):
                    raise HTTPException(403, "Java 权限服务拒绝此操作")
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                raise HTTPException(403, "Java 权限服务拒绝此操作") from exc
        except HTTPException:
            raise
        except Exception:
            # The YAML policy remains the local fail-safe path for a demo without Java running.
            pass


def rate_limit(user: str) -> None:
    now = time.monotonic()
    bucket = windows[user]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= int(POLICY["defaults"]["rate_limit_per_minute"]):
        raise HTTPException(429, "请求过于频繁，请稍后重试")
    bucket.append(now)


def input_guard(payload: WorkflowRequest) -> None:
    maximum = int(POLICY["defaults"]["max_input_chars"])
    if len(payload.title) + len(payload.research_question) + len(payload.goal) > maximum:
        raise HTTPException(413, f"输入总长度不能超过 {maximum} 字符")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "mode": os.getenv("APP_MODE", "demo"), "graph": "LangGraph StateGraph", "checkpoint_fallback": ["Redis", "SQLite", "memory"], "rag_source_count": len(DOCS)}


@app.get("/api/library")
def library(q: str = "", discipline: str = "") -> list[dict[str, Any]]:
    return retrieve(q or "生成式人工智能 学术论文", discipline, 8)


@app.get("/api/skills")
def skills() -> list[dict[str, Any]]:
    return load_active_skills()


@app.get("/api/checkpoints/{thread_id}")
def get_checkpoint(thread_id: str) -> dict[str, Any]:
    state = checkpoints.latest(thread_id)
    if state is None:
        raise HTTPException(404, "未找到此工作流的检查点")
    return {"thread_id": thread_id, "checkpoint": state}


@app.post("/api/feedback")
def submit_feedback(payload: FeedbackRequest, x_role: str = Header(default="researcher")) -> dict[str, Any]:
    check_access(x_role, "drafts:write")
    proposal = behavior.record(payload.thread_id, payload.agent, payload.helpful, payload.note)
    return {"saved": True, "skill_proposal": proposal}


@app.post("/api/context/compact")
def compact_context(payload: CompactRequest, x_role: str = Header(default="researcher")) -> dict[str, Any]:
    check_access(x_role, "drafts:read")
    return contexts.compact(payload.thread_id, payload.messages, payload.max_tokens)


@app.post("/api/workflow/run")
async def workflow_run(payload: WorkflowRequest, x_user_id: str = Header(default="demo-researcher"), x_role: str = Header(default="researcher")) -> dict[str, Any]:
    check_access(x_role, "workflow:run", x_user_id)
    rate_limit(x_user_id)
    input_guard(payload)
    events: asyncio.Queue = asyncio.Queue()
    try:
        result = await run_workflow(payload.model_dump(), events, checkpoints)
        return result
    except Exception as exc:
        raise HTTPException(500, f"工作流执行失败：{exc}") from exc


@app.post("/api/workflow/stream")
async def workflow_stream(payload: WorkflowRequest, x_user_id: str = Header(default="demo-researcher"), x_role: str = Header(default="researcher")) -> StreamingResponse:
    check_access(x_role, "workflow:run", x_user_id)
    rate_limit(x_user_id)
    input_guard(payload)
    events: asyncio.Queue = asyncio.Queue()
    async def runner() -> None:
        try:
            result = await run_workflow(payload.model_dump(), events, checkpoints)
            await events.put({"type": "result", "result": result})
        except Exception as exc:
            await events.put({"type": "error", "message": str(exc)})
        finally:
            await events.put({"type": "done"})
    async def stream():
        task = asyncio.create_task(runner())
        try:
            while True:
                item = await events.get()
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if item.get("type") == "done":
                    break
        finally:
            if not task.done():
                task.cancel()
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
