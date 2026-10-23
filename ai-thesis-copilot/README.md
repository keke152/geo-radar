# 学术同行｜多智能体 AI 论文辅助系统

根据需求图片复现的本地演示项目，覆盖论文辅助流程、检索增强生成、异步状态流、RBAC、限流、审计和行为反馈。项目开箱使用虚构样例语料与离线草稿生成器；配置 OpenAI 兼容模型和 RAGFlow 后，可切换到外部服务。

## 快速启动

环境：Windows 10/11、Python 3.10+、Node.js 20+、Java 17+、Maven 3.9+。项目当前没有捆绑或启动 RAGFlow；本地 Redis 可选，未启动时检查点落到 SQLite。

1. 双击 `run-demo.bat`，首次运行会自动安装 Python 和前端依赖，并分别打开 Python API、Java 服务、TypeScript 前端三个终端。
2. 等前端终端显示 Vite 地址后，打开 `http://127.0.0.1:5173`。
3. 题目和研究问题已有演示内容，点击“开始协同研究”。右侧会显示检索来源、各 Agent 状态、草稿和审校提示。
4. 可导出 Markdown、复制草稿，或提交“需要调整”反馈。对同一 Agent 连续 3 次负反馈后，系统会在 `python-service/skills/proposals/` 生成一份待人工审核的 Skill 建议。

如果不需要 Java 服务，可单独运行 `start-python.bat` 和 `start-frontend.bat`；Python 会使用 YAML 本地权限策略。Java 服务连接 Redis 失败时使用本地滑动窗口限流。

## 面试演示建议（约 5 分钟）

1. 说明论文全流程被拆为选题、文献、提纲、写作、格式、审校六个节点，LangGraph 在节点边界传递共享状态。
2. 输入研究题目，观察 SSE 事件把节点完成状态和生成片段推送到页面。
3. 展示来源列表，说明本地语料的检索流程由关键词候选、向量候选近似分数、元数据加权重排组成；所有分数只是演示排序分，不能代表学术证据质量。
4. 展示草稿和审校清单，强调不编造查重或 AI 生成检测结果，所有引文需要回到来源原文逐条核对。
5. 展示 Java `/api/auth/authorize` 的 RBAC 和审计日志、Redis Lua 滑动窗口限流，以及 Python 的 Redis → SQLite → 进程内检查点降级链。
6. 连续提交负反馈，查看 Skill 建议进入人工审核目录。建议讨论为什么生成的规则先进入待审状态，再由管理员审查后启用。

## 架构

```text
TypeScript + Vite 工作台
        │ SSE / JSON
        ▼
Python FastAPI ─── LangGraph StateGraph（6 个研究 Agent）
        │                       │
        │                       ├─ RAGFlow HTTP API（可选）
        │                       ├─ 本地离线演示语料（回退）
        │                       └─ OpenAI 兼容模型（可选，失败后离线回退）
        ├─ YAML 本地 RBAC 策略
        ├─ 行为反馈 / Skill 建议
        └─ 检查点：Redis → SQLite → 进程内存

Java Spring Boot
        ├─ 用户角色演示注册表与授权接口
        ├─ 操作审计日志
        └─ Redis Lua 滑动窗口限流（Redis 不可用时进程内降级）
```

### 六个 Agent

| 节点 | 作用 |
| --- | --- |
| 选题 Agent | 补出研究问题并提取关键词 |
| 文献 Agent | 调用 RAG 检索，保留来源 ID 与相关度 |
| 提纲 Agent | 生成常见论文结构 |
| 写作 Agent | 基于检索来源生成 Markdown 草稿；配置模型则调用 OpenAI 兼容 API |
| 格式 Agent | 生成参考文献清单 |
| 审校 Agent | 检查结构、引用数量并提示人工复核 |

节点完成后保存一份流程状态。若流程中断，可在页面选择“从检查点恢复”，从最近完成的节点继续。Python LangGraph 的运行时 checkpointer 使用进程内 saver；应用层快照按 Redis、SQLite、进程内存顺序降级。演示快照用于恢复未完成的流程，不包含多租户隔离和生产级加密。

## 可选服务配置

启动 Redis（可选）：

```powershell
docker compose up -d redis
```

为 Python 服务设置外部服务变量后启动：

```powershell
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
$env:RAGFLOW_BASE_URL = "http://127.0.0.1"
$env:RAGFLOW_API_KEY = "你的 RAGFlow API Key"
$env:RAGFLOW_DATASET_IDS = "你的数据集 ID"
$env:LLM_API_BASE = "https://api.openai.com/v1"
$env:LLM_API_KEY = "你的 API Key"
$env:LLM_MODEL = "gpt-4o-mini"
```

变量未配置时不会请求外部服务。RAGFlow 使用 `POST /api/v1/retrieval`；检索失败后回退到本地 JSON 语料。RAGFlow 当前官方 API 说明：[HTTP API](https://ragflow.io/docs/v1.0.0-rc1/http_api_reference)。LangGraph StateGraph 的状态、节点、边与编译流程见[官方 Graph API 文档](https://docs.langchain.com/oss/python/langgraph/graph-api)。

## 目录结构

```text
frontend/                       TypeScript + Vite 工作台
python-service/app/main.py      FastAPI、SSE、YAML RBAC、行为反馈接口
python-service/app/workflow.py LangGraph 六节点流程
python-service/app/rag.py       RAGFlow 适配和本地检索回退
python-service/app/checkpoint.py Redis / SQLite / 内存快照
python-service/app/llm.py       OpenAI 兼容模型适配和离线生成
python-service/app/behavior.py  反馈统计与 Skill 建议生成
python-service/app/context.py   四级上下文压缩与历史归档
python-service/data/library.json 虚构演示文献元数据
python-service/requirements-lock.txt 固定的 Python 依赖版本
java-service/                   Spring Boot RBAC、审计和 Redis 限流
```

## API

- `GET http://127.0.0.1:8000/api/health`：Python 服务信息
- `GET http://127.0.0.1:8000/api/library?q=...`：本地或 RAGFlow 检索
- `POST http://127.0.0.1:8000/api/workflow/stream`：SSE 工作流，输入含 `title`、`discipline`、`research_question`、`goal`
- `POST http://127.0.0.1:8000/api/workflow/run`：非流式运行；设置 `thread_id` 与 `resume_from_checkpoint=true` 可尝试恢复最近快照
- `GET http://127.0.0.1:8000/api/checkpoints/{thread_id}`：查看最近状态快照
- `POST http://127.0.0.1:8000/api/context/compact`：四级上下文整理（窗口裁剪、相邻合并、抽取摘要、归档）
- `GET http://127.0.0.1:8000/api/skills`：列出已审核启用的工作技能
- `POST http://127.0.0.1:8000/api/feedback`：记录帮助度反馈
- `POST http://127.0.0.1:8081/api/auth/authorize`：Java RBAC 授权与审计
- `GET http://127.0.0.1:8081/api/users`：演示用户列表
- `GET http://127.0.0.1:8081/api/audit`：最近审计记录
- `POST http://127.0.0.1:8081/api/rate-limit/check?key=demo`：Redis/本地滑动窗口限流演示

## 关键边界与升级方向

- 本地语料是为演示检索界面准备的合成样例，不构成真实文献数据库。论文中的样例来源不能直接用于正式投稿。
- 当前本地检索使用词项重叠和确定性分数近似，不是神经向量 embedding。启用 RAGFlow 后才由其配置的 embedding 与 reranker 提供实际检索。
- 复现项目没有真实查重服务，也不会判断文本是否由 AI 生成。`审校 Agent` 只做结构提示和引文计数。
- 图片提到的 Recall@5 91.2% 与“压缩到原始 30%”属于原始简历描述；本复现未建立相同评测集，也没有验证这些数值。
- Java 示例用户注册表仅用于演示，HTTP Header 不是身份认证。生产环境须接入可信身份提供方、数据库用户表、权限审计、租户隔离、密钥托管和传输加密。
- 真实使用需确认学校、数据主体和文献服务的授权范围，保护未发表研究、访谈记录和个人信息。正式发布前应加入依赖锁定、自动化测试、监控和安全评审。
