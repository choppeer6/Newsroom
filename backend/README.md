# Backend

FastAPI + LangGraph 后端服务。当前进度：**第 1 周（State、Agent 接口契约、FastAPI 骨架）**。

## 当前已实现

- `NewsTaskState` 及全部嵌套领域模型（Pydantic）
- 五个 Agent 的输入 / 输出契约（主编拆分为规划与审核两个节点）
- 模型级不变量：核查报告绑定稿件版本、发布必须用户确认
- FastAPI 骨架：统一响应、请求 ID、异常处理、CORS
- 任务创建 / 列表 / 详情 / 取消（内存存储）
- 40 个单元与接口测试

未实现：Agent 具体逻辑、LangGraph 编排、MySQL 持久化、JWT 认证（按六周计划推进）。

## 目录结构

```
backend/
├── app/
│   ├── main.py              # create_app / 中间件 / 异常处理
│   ├── core/                # 配置、错误、ID 与时间工具
│   ├── schemas/             # 枚举、领域模型、API 模型
│   ├── graph/
│   │   └── state.py         # NewsTaskState
│   ├── agents/
│   │   ├── base.py          # Agent 抽象基类
│   │   └── contracts.py     # 五个 Agent 的输入输出契约
│   ├── services/            # 任务服务与内存存储
│   ├── api/                 # 路由、依赖、统一响应
│   ├── models/              # SQLAlchemy ORM（第 4 周）
│   ├── db/                  # 数据库会话与迁移（第 4 周）
│   ├── tools/               # 搜索、抓取、发布工具（第 2 周起）
│   └── prompts/             # Prompt 模板（第 2 周起）
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

任务数据当前保存在进程内存中，服务重启后清空；第 4 周替换为 MySQL。

## 设计文档

- [系统架构](../../docs/02-architecture/system-architecture.md)
- [工作流设计](../../docs/04-workflow/workflow-design.md)
- [状态定义](../../docs/05-data-design/state-schema.md)
- [Agent 统一规范](../../docs/03-agent-design/agent-specification.md)
- [API 规范](../../docs/06-api/api-specification.md)
- [开发实施计划](../../docs/09-development-plan/development-plan.md)
