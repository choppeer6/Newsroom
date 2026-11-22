# AI Newsroom 智能新闻编辑部 — API 接口设计文档

| 项目 | 内容 |
| --- | --- |
| 文档编号 | NR-API-001 |
| 文档版本 | V0.4 |
| Base URL | `/api/news` |
| 日期 | 2026-11-22 |
| 状态 | 执行服务与交付接口已实现（C-05） |
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

`CREATED, RUNNING, HUMAN_REVIEW, PENDING_REVIEW, DELIVERED, FAILED, TERMINATED`

具体执行位置由 `current_stage` 返回：`created / chief_planning / research / editing / fact_check / special_check / chief_review / revision_required / human_review / prepare_delivery / pending_review / delivered / error / terminated`。

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
    "status": "RUNNING",
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
  "status": "HUMAN_REVIEW",
  "current_stage": "human_review",
  "paused": false,
  "revision_round": 0,
  "article_version": 2,
  "latest_fact_check": { "overall_result": "PARTIAL", "report_id": "RPT_001" },
  "latest_special_check": { "result": "PASSED", "report_id": "SC_001" },
  "delivery": null,
  "error": null,
  "created_at": "...",
  "updated_at": "..."
}
```

### 3.4 `POST /api/news/tasks/{task_id}/cancel` — 取消任务

允许状态：除 `DELIVERED`、`TERMINATED` 外的未完成状态。响应 `data.status = "TERMINATED"`。

### 3.5 `POST /api/news/tasks/{task_id}/execute` — 启动执行

仅 `CREATED` 状态且未暂停的任务可执行。接口**同步推进到下一个暂停点**（人工审核、待复核、失败或终止），不创建后台任务。

响应 `data` 为最新 `TaskDetail`：

```json
{
  "task_id": "TASK_001",
  "status": "HUMAN_REVIEW",
  "current_stage": "human_review",
  "paused": false,
  "revision_round": 0,
  "article_version": 2,
  "latest_fact_check": { "overall_result": "PASSED", "report_id": "FC_0001", "article_version": 2 },
  "latest_special_check": { "result": "PASSED", "report_id": "SC_0001", "article_version": 2 },
  "delivery": null,
  "error": null
}
```

- 无人工介入时，执行在 `PENDING_REVIEW` 结束并返回交付材料摘要；
- 任务正在执行（执行锁被占用）时返回 `2003`；
- 非 `CREATED` 状态返回 `2002`；已暂停返回 `2002`。

### 3.6 `POST /api/news/tasks/{task_id}/pause` — 暂停任务

仅 `CREATED`、`RUNNING` 状态的未暂停任务可暂停；暂停后 `execute` / `resume` 被拒绝。响应 `data` 为最新 `TaskDetail`（`paused=true`）。

> 同步执行模式下，暂停是启动前的闸门；执行请求本身会占用执行锁，执行期间收到的暂停请求返回 `2003`。

### 3.7 `POST /api/news/tasks/{task_id}/resume` — 恢复任务

仅已暂停的 `CREATED` 任务可恢复：清除 `paused` 后立即同步执行到下一个暂停点。响应 `data` 为最新 `TaskDetail`。

### 3.8 `GET /api/news/tasks/{task_id}/plan` — 获取采编计划

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
  "comments": "内容与来源一致，同意准备交付材料。"
}
```

- `decision`: `APPROVE` | `REQUEST_EDIT` | `REQUEST_RESEARCH` | `TERMINATE`；
- `APPROVE` → 进入 `prepare_delivery`，完成后任务为 `PENDING_REVIEW`；
- `REQUEST_EDIT` → 返回 `editor`；
- `REQUEST_RESEARCH` → 返回 `reporter`；
- `TERMINATE` → 任务 `TERMINATED`；
- 若事实核查为 `FAILED` 或专项检查为 `BLOCKED`，`APPROVE` 不会进入交付准备，任务保持 `HUMAN_REVIEW` 并在审核意见中说明原因；
- 退回修改必须提供 `revision_reason` 与至少一条 `revision_requirements`；
- 接口同步恢复工作流并推进到下一个暂停点，`data` 直接返回最新 `TaskDetail`。

响应（`APPROVE` 且交付材料已生成）：

```json
{
  "task_id": "TASK_001",
  "status": "PENDING_REVIEW",
  "current_stage": "pending_review",
  "human_decision": "APPROVE",
  "delivery": { "package_id": "DLV_0001", "article_version": 2, "prepared_at": "..." }
}
```

---

## 7. 交付接口

> 系统不执行对外发布。审核通过后由 `prepare_delivery` 生成交付材料包，任务进入 `PENDING_REVIEW`；用户复核后自行导出与提交。

### 7.1 `GET /api/news/tasks/{task_id}/delivery` — 交付材料包

```json
{
  "package_id": "DLV_0001",
  "task_id": "TASK_001",
  "article_id": "ARTICLE_001",
  "article_version": 2,
  "fact_check_report_id": "FC_0001",
  "special_check_report_id": "SC_0001",
  "source_ids": ["SRC_0001", "SRC_0002"],
  "prepared_at": "2026-11-22T16:30:00+08:00",
  "note": "预发布材料已准备，等待用户复核与导出。"
}
```

### 7.2 `POST /api/news/tasks/{task_id}/delivery/confirm` — 用户确认交付

仅在任务状态为 `PENDING_REVIEW` 时允许。

```json
{ "confirmed": true }
```

- `confirmed=true`：任务进入 `DELIVERED`，记录确认时间与操作人；
- `confirmed=false`：保持 `PENDING_REVIEW`，材料不丢失。

响应 `data` 为最新 `TaskDetail`：

```json
{
  "task_id": "TASK_001",
  "status": "DELIVERED",
  "current_stage": "delivered",
  "delivery": { "package_id": "DLV_0001", "article_version": 2, "prepared_at": "..." }
}
```

### 7.3 终止

复用 `POST /api/news/tasks/{task_id}/cancel`：未交付任务终止后为 `TERMINATED`；`DELIVERED` 任务不允许终止。

> 以上交付接口由 C-05 执行服务实现。当前演示控制台使用 `/api/news/demo/tasks/{task_id}/confirm`，语义与 7.2 一致。

---

## 8. 执行日志与进度

### 8.1 `GET /api/news/tasks/{task_id}/events` — 执行事件

按 `seq` 顺序返回该任务的 Agent 执行事件（与执行日志同源）：

```json
{
  "code": 0,
  "message": "ok",
  "data": [{
    "log_id": "LOG_001",
    "task_id": "TASK_001",
    "agent_name": "fact_checker",
    "status": "COMPLETED",
    "input_summary": null,
    "output_summary": "核查 12 条断言，3 项问题",
    "error_message": null,
    "started_at": "...",
    "finished_at": "..."
  }],
  "request_id": "req_01J..."
}
```

### 8.2 SSE 实时进度（可选，未实现）

后续可用于前端实时订阅节点事件；当前前端通过任务详情与执行事件接口轮询。

---

## 9. 接口与任务状态对照

| 接口 | 允许的任务状态 |
| --- | --- |
| `POST /tasks` | — |
| `GET /tasks/{id}` | 任意 |
| `POST /tasks/{id}/cancel` | 除 `DELIVERED`、`TERMINATED` 外的未完成状态 |
| `POST /tasks/{id}/execute` | `CREATED` 且未暂停 |
| `POST /tasks/{id}/pause` | `CREATED`、`RUNNING` 且未暂停 |
| `POST /tasks/{id}/resume` | 已暂停的 `CREATED` |
| `GET /tasks/{id}/article` | 已生成稿件后 |
| `POST /tasks/{id}/human-review` | `HUMAN_REVIEW` |
| `GET /tasks/{id}/delivery` | 已生成交付材料 |
| `POST /tasks/{id}/delivery/confirm` | `PENDING_REVIEW` |
| `GET /tasks/{id}/events` | 任意 |

---

## 10. 非功能约定

- 创建任务、人工审核、交付确认接口支持 `Idempotency-Key`，服务端 24h 内去重；
- 所有写接口记录审计日志（操作人、IP、请求摘要）；
- 错误响应不返回堆栈、Prompt、密钥等内部信息；
- 单用户任务创建限流 10 次/分钟；
- SSE 每任务最多 5 个并发连接（如启用）。

---

## 11. 实现状态（2026-11-22）

### 11.1 已实现接口

| 方法 | 路径 | 状态 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/news/health` | 已实现 | 返回服务状态、版本、环境及 LLM / 搜索配置状态 |
| `POST` | `/api/news/tasks` | 已实现 | 创建任务并生成 `NewsTaskState`；默认持久化到 SQLite / MySQL |
| `GET` | `/api/news/tasks` | 已实现 | 支持 `status`、`keyword`、`page`、`page_size` |
| `GET` | `/api/news/tasks/{task_id}` | 已实现 | 返回任务摘要、当前阶段、修改轮次、核查 / 专项检查摘要与交付材料摘要 |
| `POST` | `/api/news/tasks/{task_id}/cancel` | 已实现 | 已交付或已终止任务返回 `2002`；终止后状态为 `TERMINATED` |
| `POST` | `/api/news/tasks/{task_id}/execute` | 已实现 | 同步执行到暂停点，返回最新 `TaskDetail`；执行锁冲突返回 `2003` |
| `POST` | `/api/news/tasks/{task_id}/pause` | 已实现 | 暂停 `CREATED` / `RUNNING` 任务 |
| `POST` | `/api/news/tasks/{task_id}/resume` | 已实现 | 清除暂停并同步执行 |
| `POST` | `/api/news/tasks/{task_id}/human-review` | 已实现 | 人工批准 / 退回 / 终止，返回最新 `TaskDetail` |
| `GET` | `/api/news/tasks/{task_id}/delivery` | 已实现 | 返回完整交付材料包 |
| `POST` | `/api/news/tasks/{task_id}/delivery/confirm` | 已实现 | 确认交付置为 `DELIVERED`，拒绝时保持 `PENDING_REVIEW` |
| `GET` | `/api/news/tasks/{task_id}/events` | 已实现 | 返回 Agent 执行事件列表 |
| `GET` | `/api/news/demo/meta` | 演示 | 联调页配置信息 |
| `POST` | `/api/news/demo/tasks` | 演示 | 启动演示任务（进程内运行工作流） |
| `GET` | `/api/news/demo/tasks/{task_id}` | 演示 | 演示任务快照（阶段、中断、核查、专项检查、交付材料） |
| `POST` | `/api/news/demo/tasks/{task_id}/review` | 演示 | 提交人工审核结论并恢复工作流 |
| `POST` | `/api/news/demo/tasks/{task_id}/confirm` | 演示 | 待复核阶段确认交付（`DELIVERED`）或暂不交付 |

`TaskDetail` 字段：`paused`、`revision_round`、`article_version`、`latest_fact_check`、`latest_special_check`、`delivery`、`error`。

C-05 已补齐执行、暂停、恢复、人工审核、交付确认与执行事件接口。演示接口暂保留用于联调页；后续可切换到 `/tasks` 接口。SSE 实时进度未实现。

执行服务约定：

- 执行请求同步推进到下一个暂停点，不创建后台任务；
- 执行期间持有任务级执行锁（默认 900 秒 TTL），并发执行返回 `2003`；
- 执行异常会被记录为 `FAILED` + `RUNTIME_ERROR` 并持久化；人工审核恢复需要进程内检查点存在（重启恢复在 C-06 实现）；
- 暂停是启动前闸门：执行期间无法中断正在运行的同步请求。

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
