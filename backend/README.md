# Backend

FastAPI + LangGraph 后端服务（待实现）。

## 规划目录

```
backend/
├── app/
│   ├── main.py
│   ├── core/           # 配置、安全、日志、LLM 客户端
│   ├── api/            # tasks / articles / reviews / publish / events
│   ├── schemas/        # Pydantic 模型
│   ├── models/         # SQLAlchemy ORM
│   ├── services/       # 业务服务
│   ├── agents/         # 五个 Agent 实现
│   ├── graph/          # StateGraph、节点、路由
│   ├── tools/          # 搜索、抓取、来源提取、发布
│   ├── prompts/        # Prompt 模板（版本化）
│   └── db/             # session、迁移
├── tests/
├── alembic/
├── requirements.txt
└── .env.example
```

## 环境变量（规划）

```
DATABASE_URL=mysql+asyncmy://user:pass@localhost:3306/newsroom
JWT_SECRET=change-me
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o
SEARCH_PROVIDER=tavily
SEARCH_API_KEY=...
MAX_CONCURRENT_TASKS=10
MAX_REVISION_ROUNDS=2
```

## 设计文档

- [系统架构](../docs/02-architecture/system-architecture.md)
- [工作流设计](../docs/04-workflow/workflow-design.md)
- [状态定义](../docs/05-data-design/state-schema.md)
- [API 规范](../docs/06-api/api-specification.md)
