# Newsroom — AI 多智能体新闻采编系统

**AI Newsroom 智能新闻编辑部**：基于大语言模型和多智能体协作技术的智能新闻采编系统，实现新闻选题分析、资料搜集、新闻撰写、稿件编辑、事实核查和审核发布的半自动化流程。

> 当前阶段：**第 1 周已完成**。已落地 `NewsTaskState`、五个 Agent 的接口契约、FastAPI 骨架和任务基础接口；Agent 逻辑与 LangGraph 编排将在第 2、3 周接入。

## 项目基线

| 项 | 内容 |
| --- | --- |
| 项目定位 | 多智能体协作新闻采编系统（半自动化） |
| 核心技术架构 | Python + LangGraph + FastAPI + Vue 3 + MySQL |
| 五个核心 Agent | 主编、记者、编辑、事实核查、审核发布 |
| 流程控制 | LangGraph 负责工作流与状态管理，不将流程控制完全交给大模型 |
| 发布约束 | AI 可辅助审核，最终发布必须由用户确认 |

### 核心设计原则

1. 主编负责规划、调度和决策，不直接替代记者搜集资料。
2. 每个 Agent 有明确的职责、输入和输出。
3. LangGraph 负责工作流和状态管理，不将流程控制完全交给大模型。
4. 新闻资料必须保留来源信息。
5. AI 可以辅助审核，但最终发布必须由用户确认。

## 技术栈

| 层次 | 选型 |
| --- | --- |
| 开发语言 | Python |
| Agent 工作流 | LangGraph |
| LLM 接口 | OpenAI 兼容 API |
| 后端 | FastAPI |
| 前端 | Vue 3 |
| 数据库 | MySQL |
| ORM | SQLAlchemy |
| 数据校验 | Pydantic |
| 搜索服务 | Tavily 或其他搜索 API |
| 前端请求 | Axios |

> FAISS 暂不作为核心依赖，仅在后续需要对大量新闻资料做语义检索时引入。

## 目录结构

```
Newsroom/
├── docs/
│   ├── 01-requirements/        # PRD
│   ├── 02-architecture/        # 系统总体架构
│   ├── 03-agent-design/        # Agent 统一规范 + 五个 Agent 详细设计
│   ├── 04-workflow/            # LangGraph 工作流
│   ├── 05-data-design/         # 数据库 + NewsTaskState
│   ├── 06-api/                 # API 接口规范
│   ├── 07-prompts/             # Prompt 与工具设计
│   ├── 08-testing/             # 测试计划与验收
│   └── 09-development-plan/    # 开发实施计划与迭代路线
├── backend/                    # FastAPI 后端（State / 契约 / 任务接口已实现）
├── frontend/                   # 前端应用（待实现）
└── README.md
```

## 文档索引

| 序号 | 文档 | 路径 | 状态 |
| --- | --- | --- | --- |
| 01 | 产品需求规格说明书（PRD） | [docs/01-requirements/PRD.md](docs/01-requirements/PRD.md) | V0.1 |
| 02 | 系统总体架构设计（HLD） | [docs/02-architecture/system-architecture.md](docs/02-architecture/system-architecture.md) | V0.1 |
| 03 | Agent 设计说明书（统一规范） | [docs/03-agent-design/agent-specification.md](docs/03-agent-design/agent-specification.md) | V0.2 |
| 03 | 主编 Agent 详细设计 | [docs/03-agent-design/chief-editor-agent.md](docs/03-agent-design/chief-editor-agent.md) | 细化 |
| 03 | 记者 Agent 详细设计 | [docs/03-agent-design/reporter-agent.md](docs/03-agent-design/reporter-agent.md) | 细化 |
| 03 | 编辑 Agent 详细设计 | [docs/03-agent-design/editor-agent.md](docs/03-agent-design/editor-agent.md) | 细化 |
| 03 | 事实核查 Agent 详细设计 | [docs/03-agent-design/fact-checker-agent.md](docs/03-agent-design/fact-checker-agent.md) | 细化 |
| 03 | 审核发布 Agent 详细设计 | [docs/03-agent-design/publisher-agent.md](docs/03-agent-design/publisher-agent.md) | 细化 |
| 04 | 工作流设计文档 | [docs/04-workflow/workflow-design.md](docs/04-workflow/workflow-design.md) | V0.1 |
| 05 | 数据库设计文档 | [docs/05-data-design/database-design.md](docs/05-data-design/database-design.md) | V0.1 |
| 05 | 状态设计文档（NewsTaskState） | [docs/05-data-design/state-schema.md](docs/05-data-design/state-schema.md) | V0.2 |
| 06 | API 接口设计文档 | [docs/06-api/api-specification.md](docs/06-api/api-specification.md) | V0.2 |
| 07 | Prompt 与工具设计文档 | [docs/07-prompts/prompt-design.md](docs/07-prompts/prompt-design.md) | 初稿 |
| 08 | 测试计划与验收文档 | [docs/08-testing/test-plan.md](docs/08-testing/test-plan.md) | 初稿 |
| 09 | 开发实施计划（六周迭代） | [docs/09-development-plan/development-plan.md](docs/09-development-plan/development-plan.md) | V0.1 |

## 开发路线

总体策略：**先跑通核心业务闭环，再完善系统工程能力，最后开发前端和整理文档**。

| 周次 | 开发重点 | 阶段成果 |
| --- | --- | --- |
| 第 1 周（已完成） | 基础设施、State 与接口契约 | 项目可启动，模型可调用，任务 State 可生成 |
| 第 2 周 | 记者 / 编辑 / 事实核查 Agent | 三个 Agent 可独立运行并有结构化输出 |
| 第 3 周 | 主编 Agent 与 LangGraph 编排 | 核心新闻生产工作流（含条件路由与循环） |
| 第 4 周 | 数据持久化与任务管理 | 任务、版本、核查报告可保存、查询和恢复 |
| 第 5 周 | 前端与发布机制 | 前后端联调，用户确认后发布 |
| 第 6 周 | 测试、优化与交付 | 完整可演示项目与交付材料 |

详细任务分解、验收标准、优先级与风险应对见 [开发实施计划](docs/09-development-plan/development-plan.md)。

## 关键设计约束

1. **统一状态**：所有 Agent 通过 `NewsTaskState` 共享数据，不直接互调。
2. **来源可追溯**：新闻资料保留来源链接及元数据；稿件关键事实应有来源支持。
3. **主编决策**：事实核查完成先回到主编，由主编执行 `APPROVE / REQUEST_EDIT / REQUEST_RESEARCH / HUMAN_REVIEW`。
4. **人工兜底**：多次退回或存在争议时转人工；人工介入是正式节点或中断点。
5. **发布确认**：未经用户明确确认，系统不得正式发布。
6. **可恢复**：LangGraph Checkpointer 保存检查点，任务中断后可恢复。

## 快速开始

```bash
# backend
cd backend
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload

# 运行后端测试
python -m pytest -q

# frontend（待实现）
cd frontend && npm install && npm run dev
```

后端当前使用内存存储，重启后任务数据清空；MySQL 持久化安排在第 4 周。详细说明见 [backend/README.md](backend/README.md)。
