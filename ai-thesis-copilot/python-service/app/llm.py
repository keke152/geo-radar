"""Optional OpenAI-compatible model adapter with a deterministic offline fallback."""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from typing import Any


def demo_draft(title: str, question: str, discipline: str, sources: list[dict[str, Any]]) -> str:
    cited = sources[:3]
    if not cited:
        return f"# {title}\n\n## 摘要\n本文围绕“{question}”展开，尝试从{discipline or '相关学科'}视角梳理问题背景、研究脉络与分析路径。此处为本地离线模板草稿，尚无可引用来源，请补充真实文献后再形成论证。\n\n## 1 研究背景与问题提出\n研究问题的提出需要结合现实情境与已有证据。明确问题边界有助于后续选择合适的方法和证据来源。\n\n## 2 相关研究\n请在此补充经核验的研究成果、研究对象与结论。\n\n## 3 研究设计\n说明样本、资料来源、筛选标准、分析步骤和伦理安排。\n\n## 4 讨论与结论\n将结果与研究问题对应，报告证据限制，避免超出数据范围的结论。"
    literature = "；".join(f"{s['author']}（{s['year']}）在《{s['title']}》中讨论了{str(s['abstract'])[:75]}" for s in cited)
    return f"# {title}\n\n## 摘要\n本文围绕“{question}”展开，拟从{discipline or '相关学科'}视角梳理问题背景、相关研究与可能的分析路径。已有研究提示，研究过程需要明确资料来源、评价标准与人工复核环节（{cited[0]['author']}，{cited[0]['year']}）。本文草稿由本地演示生成器提供结构示例，研究结论、数据和引文均需作者核验。\n\n## 1 研究背景与问题提出\n研究问题的提出需要结合现实情境与已有证据。当前相关讨论集中在研究对象、使用场景和影响机制等方面。对研究者而言，明确问题边界有助于后续选择合适的方法和证据来源。\n\n## 2 相关研究与理论基础\n现有文献从不同角度讨论了这一主题。{literature}。跨研究比较时，应区分研究设计与结论适用范围，不能仅依据检索相关度判断证据强度。\n\n## 3 研究设计与分析框架\n后续研究可围绕研究问题定义核心概念，说明样本、资料来源、筛选标准和分析步骤，并建立可复核的记录。若采用访谈、问卷或实验，应补充伦理审查与数据保护说明。\n\n## 4 讨论\n研究结果需要回到研究问题进行解释，并与既有研究比较。对证据不足或相互矛盾的部分，应明确报告不确定性，避免把相关关系直接写成因果结论。\n\n## 5 结论与局限\n本文提供了一个论文结构草稿。当前演示语料规模有限，不能替代正式文献检索、数据分析和学术判断。作者应核验所有引用，补充真实研究材料，并按院校规范披露 AI 工具使用情况。"


def _openai_compatible_call(title: str, question: str, discipline: str, sources: list[dict[str, Any]], skill_rules: list[str]) -> str:
    base = os.getenv("LLM_API_BASE", "https://api.openai.com/v1").rstrip("/")
    key = os.environ["LLM_API_KEY"]
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    source_text = "\n".join(f"[{s['id']}] {s['author']} ({s['year']}). {s['title']}. 摘要：{s['abstract']}" for s in sources)
    payload = {"model": model, "temperature": .3, "messages": [
        {"role": "system", "content": "你是论文写作辅助工具。只基于提供的来源生成研究草稿。不得编造来源、数据或结论；不确定处用【待核验】标记。输出中文 Markdown，并在可支持的表述后标注来源 ID。明确说明这是待作者审阅的草稿。经审核启用的工作技能规则：\n" + "\n".join(f"- {rule}" for rule in skill_rules)},
        {"role": "user", "content": f"题目：{title}\n学科：{discipline}\n研究问题：{question}\n检索来源：\n{source_text}\n请生成约 700 至 1000 字的结构化初稿。"}
    ]}
    request = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(payload, ensure_ascii=False).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=35) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result["choices"][0]["message"]["content"].strip()


async def generate_draft(title: str, question: str, discipline: str, sources: list[dict[str, Any]], skill_rules: list[str]) -> tuple[str, str]:
    if os.getenv("LLM_API_KEY"):
        for attempt in range(3):
            try:
                text = await asyncio.to_thread(_openai_compatible_call, title, question, discipline, sources, skill_rules)
                return text, "openai-compatible"
            except Exception:
                if attempt < 2:
                    await asyncio.sleep(.25 * (2 ** attempt))
        return demo_draft(title, question, discipline, sources), "offline-fallback"
    return demo_draft(title, question, discipline, sources), "offline-demo"
