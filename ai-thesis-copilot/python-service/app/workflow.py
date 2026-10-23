from __future__ import annotations

import asyncio
import re
import uuid
from operator import add
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from .checkpoint import CheckpointStore
from .llm import generate_draft
from .rag import retrieve
from .skills import load_active_skills


class ThesisState(TypedDict, total=False):
    thread_id: str
    title: str
    discipline: str
    research_question: str
    goal: str
    keywords: list[str]
    sources: list[dict[str, Any]]
    outline: list[str]
    draft: str
    formatted: str
    review: dict[str, Any]
    generation_mode: str
    checkpoint_node: str
    trace: Annotated[list[dict[str, Any]], add]


AGENTS = [
    ("topic", "选题 Agent", "明确研究问题"),
    ("retrieval", "文献 Agent", "三阶段 RAG 检索"),
    ("outline", "提纲 Agent", "生成章节结构"),
    ("writing", "写作 Agent", "基于证据撰写草稿"),
    ("format", "格式 Agent", "整理引用与格式"),
    ("review", "审校 Agent", "检查完整性与风险"),
]


def build_graph(events: asyncio.Queue, checkpoints: CheckpointStore):
    async def record(node: str, state: ThesisState, update: dict[str, Any]) -> dict[str, Any]:
        trace_item = {"node": node, "label": dict((x[0], x[1]) for x in AGENTS)[node], "status": "completed"}
        update = {**update, "trace": [trace_item], "checkpoint_node": node}
        snapshot = {**state, **update, "trace": [*state.get("trace", []), trace_item]}
        store = checkpoints.save(state["thread_id"], node, snapshot)
        await events.put({"type": "agent", "node": node, "label": trace_item["label"], "status": "completed", "checkpoint": store})
        return update

    async def topic_agent(state: ThesisState) -> dict[str, Any]:
        title = state["title"].strip()
        question = state.get("research_question", "").strip() or f"{title}的现状、影响因素与改进路径是什么？"
        words = [w for w in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", f"{title} {question}")]
        await asyncio.sleep(.04)
        return await record("topic", state, {"research_question": question, "keywords": list(dict.fromkeys(words))[:8]})

    async def retrieval_agent(state: ThesisState) -> dict[str, Any]:
        query = " ".join([state["title"], state["research_question"], *state.get("keywords", [])])
        sources = await asyncio.to_thread(retrieve, query, state.get("discipline", ""), 5)
        await asyncio.sleep(.08)
        await events.put({"type": "sources", "items": [{"id": s["id"], "title": s["title"], "author": s["author"], "year": s["year"], "score": s["score"]} for s in sources]})
        return await record("retrieval", state, {"sources": sources})

    async def outline_agent(state: ThesisState) -> dict[str, Any]:
        outline = ["研究背景与问题提出", "相关研究与理论基础", "研究设计与分析框架", "结果分析与讨论", "结论、局限与展望"]
        await asyncio.sleep(.04)
        await events.put({"type": "outline", "items": outline})
        return await record("outline", state, {"outline": outline})

    async def writing_agent(state: ThesisState) -> dict[str, Any]:
        sources = state.get("sources", [])
        skill_rules = [rule for skill in load_active_skills() for rule in skill.get("instructions", [])]
        draft, mode = await generate_draft(state["title"], state["research_question"], state.get("discipline", ""), sources, skill_rules)
        for token in re.findall(r"\S+\s*", draft):
            await events.put({"type": "token", "text": token})
            await asyncio.sleep(.008)
        return await record("writing", state, {"draft": draft, "generation_mode": mode})

    async def format_agent(state: ThesisState) -> dict[str, Any]:
        refs = "\n".join(f"- {s['author']}（{s['year']}）. {s['title']}. *{s['source']}*. [演示语料 {s['id']}]" for s in state.get("sources", [])[:5])
        formatted = state.get("draft", "") + "\n\n## 参考文献（待人工核验）\n" + refs
        await asyncio.sleep(.04)
        return await record("format", state, {"formatted": formatted})

    async def review_agent(state: ThesisState) -> dict[str, Any]:
        draft = state.get("draft", "")
        review = {"word_count": len(re.sub(r"\s", "", draft)),
                  "citation_count": len(re.findall(r"（[^）]+，\d{4}）", draft)),
                  "missing_citations": not bool(state.get("sources")),
                  "risk_level": "需人工核验", "checks": ["检查研究问题是否明确", "核对引文与原文是否一致", "补充真实数据和方法", "按学校规范披露 AI 使用"],
                  "notice": f"生成模式：{state.get('generation_mode', 'offline-demo')}。本系统不执行真实查重，也不判断文本是否由 AI 生成。"}
        await asyncio.sleep(.04)
        return await record("review", state, {"review": review})

    builder = StateGraph(ThesisState)
    builder.add_node("topic", topic_agent)
    builder.add_node("retrieval", retrieval_agent)
    builder.add_node("outline_step", outline_agent)
    builder.add_node("writing", writing_agent)
    builder.add_node("format", format_agent)
    builder.add_node("review_step", review_agent)
    def next_after_checkpoint(state: ThesisState) -> str:
        return {"topic": "retrieval", "retrieval": "outline_step", "outline": "writing",
                "writing": "format", "format": "review_step", "review": "review_step"}.get(state.get("checkpoint_node", ""), "topic")
    builder.add_conditional_edges(START, next_after_checkpoint)
    builder.add_edge("topic", "retrieval")
    builder.add_edge("retrieval", "outline_step")
    builder.add_edge("outline_step", "writing")
    builder.add_edge("writing", "format")
    builder.add_edge("format", "review_step")
    builder.add_edge("review_step", END)
    return builder.compile(checkpointer=InMemorySaver())


async def run_workflow(payload: dict[str, Any], events: asyncio.Queue, checkpoints: CheckpointStore) -> dict[str, Any]:
    thread_id = payload.get("thread_id") or str(uuid.uuid4())
    await events.put({"type": "started", "thread_id": thread_id})
    saved = checkpoints.latest(thread_id) if payload.get("resume_from_checkpoint") and payload.get("thread_id") else None
    if payload.get("resume_from_checkpoint") and saved is None:
        raise ValueError("未找到可恢复的检查点")
    initial: ThesisState = {**(saved or {}), "thread_id": thread_id, "title": payload["title"], "discipline": payload.get("discipline", "").strip(),
                            "research_question": payload.get("research_question", "").strip() or (saved or {}).get("research_question", ""), "goal": payload.get("goal", "") or (saved or {}).get("goal", "")}
    graph = build_graph(events, checkpoints)
    result = await graph.ainvoke(initial, {"configurable": {"thread_id": thread_id}})
    output = {"thread_id": thread_id, "title": result["title"], "research_question": result["research_question"],
              "outline": result["outline"], "sources": [{k: s[k] for k in ("id", "title", "author", "year", "source", "score")} for s in result["sources"]],
              "draft": result["formatted"], "review": result["review"], "trace": result["trace"],
              "generation_mode": result.get("generation_mode", "offline-demo")}
    return output
