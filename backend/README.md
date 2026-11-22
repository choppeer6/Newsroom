# Backend

FastAPI + LangGraph 后端服务。当前进度：**第 4 周（任务编排与持久化）**。

## 当前已实现

- `NewsTaskState` 及全部嵌套领域模型（Pydantic）
- 五个 Agent 的输入 / 输出契约（主编拆分为规划与审核两个节点）
- 模型级不变量：核查报告绑定稿件版本、发布必须用户确认
- FastAPI 骨架：统一响应、请求 ID、异常处理、CORS
- 任务创建 / 列表 / 详情 / 取消，基于 SQLAlchemy 落库（默认 SQLite，可切 MySQL）
- Reporter：检索词生成 → 搜索 → 来源去重编号 → 撰写初稿，支持退回补充资料
- Editor：结构化编辑，版本号由代码递增，不采信模型返回的版本
- Fact Checker：断言抽取 → 逐条检索 → 依据证据判定，证据由代码绑定、总体结果由代码计算
- Chief Editor：规划节点输出采编计划；审核节点输出四种决策，`APPROVE` 仅在核查通过时保留
- 预发布准备：校验事实核查与专项检查前置条件，生成绑定版本的交付材料包；用户确认后置为已交付，不调用外部发布通道
- LangGraph 工作流：条件路由、退回循环、人工审核中断、执行日志与内存检查点
- 执行服务：后台任务推进、暂停 / 恢复、人工批准 / 退回 / 终止、交付确认、执行事件查询
- 版本与恢复：人工编辑新版本从事实核查重跑并重新绑定报告；启动时清理遗留 `RUNNING` 任务；执行锁防重复启动
- 接口失败重试按接口独立计数（`interface_retry_counts`），与稿件修改轮次分别设限
- 临时联调页面 `/demo`：发起任务、进度轮询、人工审核、发布确认（正式前端仍按计划推进）
- OpenAI 兼容 LLM JSON 客户端（超时 / 429 / 5xx 有限重试）与 Tavily 搜索工具
- YAML + Jinja2 Prompt 模板与共享输出 / 安全 / 来源规则
- 177 个单元、集成与工作流测试
- 真实 DeepSeek + Tavily 全流程验证：规划 → 记者 → 编辑 → 核查 → 专项检查 → 主编 → 人工审核 → 交付材料

未实现：正式前端、JWT 认证、SSE 进度事件、持久化 Checkpointer（按六周计划推进）。

## 目录结构

```
backend/
├── app/
│   ├── main.py              # create_app / 中间件 / 异常处理
│   ├── core/                # 配置、错误、ID 与时间工具、LLM 客户端
│   ├── schemas/             # 枚举、领域模型、API 模型
│   ├── graph/
│   │   ├── state.py         # NewsTaskState
│   │   ├── routing.py       # 条件路由
│   │   ├── nodes.py         # 九个工作流节点与 Agent 装配
│   │   └── workflow.py      # 图组装、检查点与运行封装
│   ├── agents/
│   │   ├── base.py          # Agent 抽象基类
│   │   ├── contracts.py     # 五个 Agent 的输入输出契约
│   │   ├── runtime.py       # 输出校验重试与统一失败输出
│   │   ├── sources.py       # 来源归一化、去重与编号
│   │   ├── reporter.py      # 记者 Agent
│   │   ├── editor.py        # 编辑 Agent
│   │   ├── fact_checker.py  # 事实核查 Agent
│   │   ├── chief_editor.py  # 主编规划 / 审核 Agent
│   │   └── publisher.py     # 发布 Agent
│   ├── prompts/
│   │   ├── loader.py        # YAML + Jinja2 加载器
│   │   ├── agents/          # 五个 Agent 的 Prompt
│   │   └── shared/          # 输出、安全、来源规则
│   ├── services/            # 任务服务、内存存储、模拟发布通道、联调运行器
│   ├── api/                 # 路由、依赖、统一响应
│   ├── web/                 # 临时联调页面
│   ├── models/              # SQLAlchemy ORM（任务、执行事件）
│   ├── db/                  # 数据库会话与存储实现
│   └── tools/               # Tavily 搜索工具
├── tests/
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
└── .env.example
```

## 本地运行

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000/docs 查看接口文档。

## 工作流联调页面（临时）

启动服务后打开 http://127.0.0.1:8000/demo 。

- 页面发起选题，轮询展示选题规划、稿件、事实核查、来源与执行日志；
- 人工审核节点可选择通过 / 退回编辑 / 退回记者 / 终止；
- 待复核节点可确认交付或暂缓交付；
- 任务保存在进程内存中，刷新页面会自动接回当前任务，重启服务后清空；
- 页面直接调用真实 LLM 与搜索接口，一次完整流程通常 1–3 分钟。

该页面只用于联调核心工作流；正式任务接口已实现（见下文），正式前端按计划推进。

## LLM 与搜索配置

配置从 `backend/.env` 读取，由 `app/core/config.py` 加载；`.env` 已被 Git 忽略。

```bash
cd backend
cp .env.example .env
```

编辑 `.env`：

```dotenv
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o

SEARCH_PROVIDER=tavily
SEARCH_API_KEY=tvly-...
```

也支持直接设置同名环境变量，环境变量优先级高于 `.env`。修改配置后需重启 uvicorn（配置有进程内缓存）。

验证：

```bash
curl http://127.0.0.1:8000/api/news/health
```

`llm_configured` / `search_configured` 为 `true` 表示对应密钥已配置；空字符串会被视为未配置。

```json
{
  "code": 0,
  "data": {
    "status": "ok",
    "llm_configured": true,
    "search_configured": true
  }
}
```

密钥只在服务端使用，不会通过接口返回；不要提交 `.env` 或把密钥写入代码。

## 运行工作流

```python
import asyncio

from app.graph.state import NewsTaskState
from app.graph.workflow import NewsroomWorkflow


async def main() -> None:
    workflow = NewsroomWorkflow()  # 读取 .env 中的 LLM 与搜索配置
    result = await workflow.run(
        NewsTaskState(task_id="TASK_001", topic="人工智能在高校教育中的应用")
    )
    # 停在人工审核时 result.interrupt 非空；批准后到达 PENDING_REVIEW
    result = await workflow.resume(
        "TASK_001", {"decision": "APPROVE", "comments": "通过"}
    )
    print(result.state.task_status)


asyncio.run(main())
```

- 人工审核恢复值为 `{"decision": "APPROVE|REQUEST_EDIT|REQUEST_RESEARCH|TERMINATE", ...}`。
- 检查点为内存实现；重启后进行中的任务会被标记失败，人工编辑可通过 `stream_recheck` 重建检查点。

## 独立运行 Agent

各 Agent 均返回契约模型，不会返回裸自然语言；失败时通过 `status=FAILED` 与 `error.code` 表达，不抛出到调用方。

```python
import asyncio

from app.agents.contracts import EditorInput
from app.agents.editor import EditorAgent
from app.schemas.domain import ArticleContent

async def main() -> None:
    agent = EditorAgent()  # 读取 .env 中的 LLM 配置
    result = await agent.run(
        EditorInput(
            task_id="TASK_001",
            draft=ArticleContent(title="初稿标题", content="初稿正文"),
            current_version=1,
        )
    )
    if result.status == "FAILED":
        print(result.error.code, result.error.message)
    else:
        print(result.version, result.edited_article.title)

asyncio.run(main())
```

- Reporter / Fact Checker 需要同时配置 `LLM_API_KEY` 与 `SEARCH_API_KEY`，Editor 只需要 LLM。
- Reporter 支持传入 `revision_request`、`existing_sources` 和 `previous_draft` 完成退回重写。
- Fact Checker 的核查报告会自动绑定 `article_id` 与 `article_version`。

## 测试

```bash
cd backend
python -m pytest -q
```

## 已实现接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/news/health` | 服务健康与配置状态 |
| `POST` | `/api/news/tasks` | 创建任务并生成 `NewsTaskState` |
| `GET` | `/api/news/tasks` | 任务列表（状态、关键词、分页） |
| `GET` | `/api/news/tasks/{task_id}` | 任务详情 |
| `POST` | `/api/news/tasks/{task_id}/cancel` | 取消任务 |
| `POST` | `/api/news/tasks/{task_id}/execute` | 后台执行到暂停点（202） |
| `POST` | `/api/news/tasks/{task_id}/pause` | 暂停任务 |
| `POST` | `/api/news/tasks/{task_id}/resume` | 从检查点恢复（202） |
| `POST` | `/api/news/tasks/{task_id}/human-review` | 人工批准 / 退回 / 终止（202） |
| `GET` | `/api/news/tasks/{task_id}/delivery` | 交付材料包 |
| `POST` | `/api/news/tasks/{task_id}/delivery/confirm` | 确认交付 |
| `GET` | `/api/news/tasks/{task_id}/events` | 执行事件 |

任务与执行事件通过 SQLAlchemy 落库，默认 SQLite（`backend/newsroom.db`），可用 `DATABASE_URL` 切换 MySQL。

## 设计文档

- [系统架构](../../docs/02-architecture/system-architecture.md)
- [工作流设计](../../docs/04-workflow/workflow-design.md)
- [状态定义](../../docs/05-data-design/state-schema.md)
- [Agent 统一规范](../../docs/03-agent-design/agent-specification.md)
- [API 规范](../../docs/06-api/api-specification.md)
- [开发实施计划](../../docs/09-development-plan/development-plan.md)
