# 项目目录

## AI GEO 品牌可见度工作台

[源码与启动说明](AI-GEO-workspace/README.md) · [2026-11-11 检查与优化记录](AI-GEO-workspace/docs/project-review-2026-11-11.md)

Windows 本地运行的多平台品牌观察工具，支持分平台问题规划、任务队列、回答采集、统计与导出。本次保存包含已验证的稳定性修复，以及通过的 234 项单元／HTTP 测试和 6 项前端交互测试。

在 `AI-GEO-workspace` 目录运行 `start.bat` 启动；需要 Python 3.10–3.13 和 Microsoft Edge。仓库不包含运行数据库、浏览器登录资料、API 密钥、虚拟环境或本地修改备份。

## 历史项目迁移

本仓库于 **2026-10-23** 完成拆分。三个项目的源码、文档和后续更新分别维护在独立仓库中：

| 项目 | 独立仓库 | 主要内容 |
| --- | --- | --- |
| Commerce Insight · 知购 | [commerce-insight](https://github.com/keke152/commerce-insight) | 订单分析、品类识别与复购洞察 |
| Thesis Agent Workbench · 学术同行 | [thesis-agent-workbench](https://github.com/keke152/thesis-agent-workbench) | 多智能体论文研究、检索、检查点和权限服务 |
| AlphaLens Stock Lab | [alphalens-stock-lab](https://github.com/keke152/alphalens-stock-lab) | 股票趋势预测、回测与实验对比 |

请从对应的新仓库获取源码、阅读启动说明或提交问题。

上述三个项目在本仓库中的目录作为迁移前的历史快照保留，后续维护在对应的独立仓库中进行。
