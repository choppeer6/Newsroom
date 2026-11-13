# AI Newsroom 智能新闻编辑部 — API 接口设计文档

| 项目 | 内容 |
| --- | --- |
| 文档编号 | NR-API-001 |
| 文档版本 | V0.2 |
| Base URL | `/api/news` |
| 日期 | 2026-11-13 |
| 状态 | 骨架已实现（第 1 周） |
| 关联文档 | [PRD](../01-requirements/PRD.md)、[工作流设计](../04-workflow/workflow-design.md)、[数据库设计](../05-data-design/database-design.md) |

---

## 1. 通用约定

### 1.1 认证

- 除登录接口外，所有接口要求 `Authorization: Bearer <JWT>`；
- 审核、发布确认接口要求登录用户具备相应权限；
- JWT 有效期 8 小时。

### 1.2 响应结构

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "request_id": "req_01J..."
}
```

- `code=0` 表示成功；非 0 为业务错误；
- HTTP 状态码与业务码同时使用：参数错误 400，未认证 401，无权限 403，不存在 404，状态冲突 409，服务错误 500。

### 1.3 错误码

| code | HTTP | 含义 |
| --- | --- | --- |
| 0 | 200 | 成功 |
| 1001 | 400 | 参数校验失败 |
| 1002 | 401 | 未登录或 Token 失效 |
| 1003 | 403 | 无权限 |
| 2001 | 404 | 任务 / 稿件不存在 |
| 2002 | 409 | 当前任务状态不允许该操作 |
| 2003 | 409 | 任务正在执行（并发冲突） |
| 2004 | 409 | 重复操作（幂等命中） |
| 3001 | 500 | Agent 执行失败 |
| 3002 | 503 | 外部服务不可用（LLM / 搜索） |

### 1.4 分页与时间

- 分页：`?page=1&page_size=20`（`page_size` ≤ 100），响应 `data` 内为 `items/page/page_size/total`；
- 时间：ISO 8601，如 `2026-11-13T14:03:21+08:00`；
- 任务 ID：`task_id` 字符串（如 `TASK_001` 或 UUID）。

### 1.5 任务状态

`CREATED, PLANNING, RESEARCHING, WRITING, EDITING, FACT_CHECKING, REVIEWING, HUMAN_REVIEW, PENDING_PUBLISH, PUBLISHED, REVISION_REQUIRED, FAILED, CANCELLED`

---

## 2. 认证

### `POST /api/news/auth/login`

```json
// request
{ "username": "editor01", "password": "******" }
// response.data
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 28800,
  "user": { "id": 2, "username": "editor01", "display_name": "张编辑", "role": "user" }
}
```

### `GET /api/news/auth/me`

返回当前用户信息。

---

## 3. 任务接口

### 3.1 `POST /api/news/tasks` — 创建新闻采编任务

```json
// request
{
  "topic": "人工智能技术在高校教育中的应用",
  "description": "关注人工智能在高校教学中的应用现状",
  "requirements": {
    "style": "客观新闻报道",
    "target_length": 1500,
    "focus": ["应用案例", "实际效果", "存在的问题"]
  }
}
// response 201
{
  "code": 0, "message": "ok",
  "data": {
    "task_id": "TASK_001",
    "status": "CREATED",
    "created_at": "2026-11-13T14:00:00+08:00"
  }
}
```

校验：`topic` 必填、1~500 字；`target_length` 200~5000；`style` 为字符串；`focus` 为字符串数组。

### 3.2 `GET /api/news/tasks` — 任务列表

查询参数：`status`、`keyword`、`page`、`page_size`。

```json
{
  "items": [{
    "task_id": "TASK_001",
    "topic": "人工智能技术在高校教育中的应用",
    "status": "REVIEWING",
    "current_stage": "chief_review",
    "created_at": "...",
    "updated_at": "..."
  }],
  "page": 1, "page_size": 20, "total": 1
}
```

### 3.3 `GET /api/news/tasks/{task_id}` — 任务详情

```json
{
  "task_id": "TASK_001",
  "topic": "...",
  "description": "...",
  "requirements": { "style": "客观新闻报道", "target_length": 1500, "focus": ["应用案例"] },
  "status": "REVIEWING",
  "current_stage": "chief_review",
  "retry_count": 0,
  "current_article_version": 2,
  "latest_fact_check": { "overall_result": "PARTIAL", "report_id": "RPT_001" },
  "publication_status": null,
  "error": null,
  "created_at": "...",
  "updated_at": "..."
}
```

### 3.4 `POST /api/news/tasks/{task_id}/cancel` — 取消任务

允许状态：除 `PUBLISHED`、`CANCELLED` 外的未完成状态。响应 `data.status = "CANCELLED"`。

### 3.5 `GET /api/news/tasks/{task_id}/plan` — 获取采编计划

```json
{
  "plan_id": "PLAN_001",
  "task_id": "TASK_001",
  "plan_content": {
    "topic_analysis": "...",
    "reporting_angles": ["..."],
    "research_tasks": ["..."],
    "article_outline": ["..."],
    "verification_points": ["..."]
  },
  "created_at": "..."
}
```

---

## 4. 稿件接口

### 4.1 `GET /api/news/tasks/{task_id}/article` — 获取当前稿件

```json
{
  "article_id": "ARTICLE_001",
  "article_version": 2,
  "title": "优化后的新闻标题",
  "content": "编辑后的新闻正文……",
  "status": "EDITED",
  "editor_name": "editor",
  "updated_at": "..."
}
```

### 4.2 `GET /api/news/tasks/{task_id}/article/versions` — 版本列表

返回 `version_number, title, editor_name, change_summary, created_at` 摘要。

### 4.3 `GET /api/news/tasks/{task_id}/article/versions/{version}` — 指定版本

返回完整 `content` 与 `change_summary`。

### 4.4 `GET /api/news/tasks/{task_id}/sources` — 资料来源

```json
{
  "items": [{
    "source_id": "SRC_001",
    "title": "新闻资料标题",
    "url": "https://example.com/article",
    "publisher": "资料发布机构",
    "published_at": "2026-01-01T00:00:00Z",
    "summary": "资料摘要",
    "retrieved_at": "..."
  }]
}
```

---

## 5. 事实核查接口

### 5.1 `GET /api/news/tasks/{task_id}/fact-check-reports`

```json
{
  "items": [{
    "report_id": "RPT_001",
    "article_version": 2,
    "overall_result": "PARTIAL",
    "created_at": "..."
  }]
}
```

### 5.2 `GET /api/news/tasks/{task_id}/fact-check-reports/latest`

返回完整核查报告：

```json
{
  "report_id": "RPT_001",
  "article_version": 2,
  "overall_result": "PARTIAL",
  "report_content": {
    "claims": [{
      "claim": "某高校已经开展人工智能教学实践",
      "result": "VERIFIED",
      "evidence": [{ "source_id": "SRC_001", "url": "...", "supporting_excerpt": "..." }],
      "reason": "存在可靠来源支持"
    }],
    "issues": ["部分统计数据缺少可靠来源"],
    "recommendation": "REQUEST_RESEARCH"
  },
  "created_at": "..."
}
```

### 5.3 `GET /api/news/tasks/{task_id}/fact-check-reports/{report_id}`

按报告 ID 查询完整报告。

---

## 6. 审核接口

### 6.1 `GET /api/news/tasks/{task_id}/reviews` — 审核记录

```json
{
  "items": [{
    "review_id": "REV_001",
    "article_version": 2,
    "reviewer_type": "chief",
    "decision": "REQUEST_EDIT",
    "comments": "标题夸大，需与正文一致",
    "created_at": "..."
  }]
}
```

### 6.2 `POST /api/news/tasks/{task_id}/human-review` — 人工审核

仅在任务状态为 `HUMAN_REVIEW` 时允许。

```json
{
  "decision": "APPROVE",
  "comments": "内容与来源一致，同意进入发布流程。"
}
```

- `decision`: `APPROVE` | `REQUEST_EDIT` | `REQUEST_RESEARCH` | `TERMINATE`；
- `APPROVE` → 进入 `publisher`；
- `REQUEST_EDIT` → 返回 `editor`；
- `REQUEST_RESEARCH` → 返回 `reporter`；
- `TERMINATE` → 任务 `CANCELLED`。

响应：

```json
{ "data": { "review_id": "REV_002", "decision": "APPROVE", "status": "PENDING_PUBLISH" } }
```

---

## 7. 发布接口

### 7.1 `GET /api/news/tasks/{task_id}/publication` — 待发布 / 发布记录

```json
{
  "publication_id": "PUB_001",
  "article_id": "ARTICLE_001",
  "article_version": 2,
  "status": "PENDING_PUBLISH",
  "confirmed_by": null,
  "confirmed_at": null,
  "published_at": null,
  "external_url": null,
  "message": "稿件已进入待发布状态，等待用户确认"
}
```

### 7.2 `POST /api/news/tasks/{task_id}/publication/confirm` — 用户确认

仅在任务状态为 `PENDING_PUBLISH` 时允许。

```json
{ "confirmed": true }
```

- `confirmed=true`：调用发布接口，成功返回 `PUBLISHED`，失败保持 `PENDING_PUBLISH` 且 `publication.status=FAILED`；
- `confirmed=false`：保持待发布状态，任务状态仍为 `PENDING_PUBLISH`。

响应：

```json
{
  "data": {
    "status": "PUBLISHED",
    "published_at": "2026-11-13T16:30:00+08:00",
    "external_url": "https://mock.example.com/news/ARTICLE_001"
  }
}
```

### 7.3 `POST /api/news/tasks/{task_id}/publication/retry` — 发布失败重试

仅当 `publication.status == "FAILED"` 时允许；重复请求幂等返回已有结果。

---

## 8. 执行日志与进度

### 8.1 `GET /api/news/tasks/{task_id}/logs` — Agent 执行日志

```json
{
  "items": [{
    "log_id": "LOG_001",
    "agent_name": "fact_checker",
    "status": "COMPLETED",
    "input_summary": "稿件版本 2",
    "output_summary": "核查 12 条断言，3 项问题",
    "error_message": null,
    "started_at": "...",
    "finished_at": "..."
  }]
}
```

### 8.2 `GET /api/news/tasks/{task_id}/events` — 进度事件流（可选 SSE）

用于前端实时进度展示，事件包含 `node`、`event_type`、`status`、`message`、`created_at`。

---

## 9. 接口与任务状态对照

| 接口 | 允许的任务状态 |
| --- | --- |
| `POST /tasks` | — |
| `GET /tasks/{id}` | 任意 |
| `POST /tasks/{id}/cancel` | 除 `PUBLISHED`、`CANCELLED` 外的未完成状态 |
| `GET /tasks/{id}/article` | 已生成稿件后 |
| `POST /tasks/{id}/human-review` | `HUMAN_REVIEW` |
| `GET /tasks/{id}/publication` | `PENDING_PUBLISH`、`PUBLISHED`、失败待重试 |
| `POST /tasks/{id}/publication/confirm` | `PENDING_PUBLISH` |
| `POST /tasks/{id}/publication/retry` | `PENDING_PUBLISH` 且 `publication.status=FAILED` |

---

## 10. 非功能约定

- 创建任务、人工审核、发布确认接口支持 `Idempotency-Key`，服务端 24h 内去重；
- 所有写接口记录审计日志（操作人、IP、请求摘要）；
- 错误响应不返回堆栈、Prompt、密钥等内部信息；
- 单用户任务创建限流 10 次/分钟；
- SSE 每任务最多 5 个并发连接（如启用）。

---

## 11. 第 1 周实现状态（V0.2）

### 11.1 已实现接口

| 方法 | 路径 | 状态 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/news/health` | 已实现 | 返回服务状态、版本、环境及 LLM / 搜索配置状态 |
| `POST` | `/api/news/tasks` | 已实现 | 创建任务并生成 `NewsTaskState`；当前存储于内存 |
| `GET` | `/api/news/tasks` | 已实现 | 支持 `status`、`keyword`、`page`、`page_size` |
| `GET` | `/api/news/tasks/{task_id}` | 已实现 | 返回任务摘要、当前阶段、核查摘要和发布状态 |
| `POST` | `/api/news/tasks/{task_id}/cancel` | 已实现 | 已发布或已取消任务返回 `2002` |

其余接口（文章、核查报告、审核、发布、日志、SSE）将在后续周次实现。

### 11.2 已实现的通用约定

- 统一响应结构：`code / message / data / request_id`；
- 请求 ID：接受客户端 `X-Request-ID`，否则自动生成，并通过响应头回传；
- 参数校验失败：HTTP `400`，业务码 `1001`；
- 资源不存在：HTTP `404`，业务码 `2001`；
- 状态冲突：HTTP `409`，业务码 `2002`；
- 未处理异常：HTTP `500`，业务码 `5000`（实现阶段补充的内部错误码，后续可并入正式错误码表）；
- 已配置 CORS，默认允许 `http://localhost:5173`。

### 11.3 暂未实现

- JWT 认证与权限校验；
- MySQL 持久化（当前任务数据存储在进程内存，重启后丢失，第 4 周替换）；
- `Idempotency-Key`、限流、审计日志；
- Agent 执行接口、工作流启动与中断恢复接口；
- SSE 进度事件。
