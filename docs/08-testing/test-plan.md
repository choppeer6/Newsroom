# AI Newsroom 智能新闻编辑部 — 测试计划与验收文档

| 项目 | 内容 |
| --- | --- |
| 文档编号 | NR-TEST-001 |
| 文档版本 | V0.1 |
| 日期 | 2026-11-13 |
| 状态 | 基线文档 |
| 关联文档 | [PRD](../01-requirements/PRD.md)、[工作流设计](../04-workflow/workflow-design.md)、[API 规范](../06-api/api-specification.md) |

---

## 1. 测试目标

验证：

1. 五个 Agent 的职责、输出结构与权限约束；
2. LangGraph 工作流的顺序执行、四条决策路由、退回循环与人工介入；
3. 新闻资料与稿件来源的可追溯性；
4. API 与前端交互符合接口规范；
5. 异常场景（模型失败、搜索失败、格式错误、中断）可处理或可恢复；
6. **未经用户确认不得发布**。

---

## 2. 测试层次

| 层次 | 范围 | 工具 |
| --- | --- | --- |
| 单元测试 | Agent 输出校验、路由函数、工具封装 | pytest |
| 集成测试 | 节点 + MySQL + Mock LLM / Mock 搜索 | pytest + 测试库 |
| 工作流测试 | LangGraph 全图分支、退回、中断恢复 | 内存 Checkpointer |
| API 测试 | 任务、稿件、审核、确认发布 | httpx / TestClient |
| 前端冒烟 | 任务创建 → 进度 → 稿件 → 审核 → 确认 | Playwright |
| 评测集回归 | 事实核查准确率、来源覆盖率 | 标注数据集 |

---

## 3. 测试环境

| 项 | 配置 |
| --- | --- |
| 环境 | 本地 Docker Compose（MySQL、backend、frontend） |
| LLM | Mock（默认）/ 真实模型（每日回归） |
| 搜索 | 固定搜索结果集（20 组查询） |
| 数据库 | 独立测试 schema，迁移初始化 |
| 测试账号 | 普通用户、管理员各 1 个 |
| 固定数据 | 3 个选题 fixture、12 个来源、50+ 条断言评测集 |

---

## 4. Agent 单元测试

### 4.1 主编 Agent

| 用例 | 输入 | 期望 |
| --- | --- | --- |
| TC-CE-01 | 正常选题 | 输出含 `topic_analysis`、`reporting_angles`、`research_tasks`、`article_outline`、`verification_points` |
| TC-CE-02 | 长选题 / 多重点方向 | 计划完整，无字段缺失 |
| TC-CE-03 | 模型返回非法 JSON | 重试后成功；二次失败节点失败 |
| TC-CE-04 | 核查报告存在事实问题 | 决策 `REQUEST_RESEARCH`，`revision_request.target=reporter` |
| TC-CE-05 | 仅结构 / 表达问题 | 决策 `REQUEST_EDIT`，`target=editor` |
| TC-CE-06 | 关键信息存在争议 | 决策 `HUMAN_REVIEW` |
| TC-CE-07 | 核查通过且稿件合格 | 决策 `APPROVE` |

### 4.2 记者 Agent

| 用例 | 输入 | 期望 |
| --- | --- | --- |
| TC-RP-01 | 正常采编计划 | 调用搜索工具，产出 `draft` 与 `sources`，含 `source_id/title/url/publisher/published_at` |
| TC-RP-02 | 搜索无结果 | 换关键词重试，输出 `unverified_claims`，不编造来源 |
| TC-RP-03 | 网页抓取失败 | 跳过并记录，不阻塞整体 |
| TC-RP-04 | 来源不足 | 标记缺口，供主编决策 |
| TC-RP-05 | 收到 `revision_request` | 仅补充/重写相关部分，保留原有有效来源 |
| TC-RP-06 | 输出缺来源 | Pydantic 校验失败或标记 `unverified_claims`，不得静默通过 |

### 4.3 编辑 Agent

| 用例 | 输入 | 期望 |
| --- | --- | --- |
| TC-ED-01 | 正常初稿 | 输出 `edited_article` 与 `editing_report`，版本号递增 |
| TC-ED-02 | 初稿含事实疑点 | 标记反馈，不擅自修改事实 |
| TC-ED-03 | 收到 `REQUEST_EDIT` | 按意见修改结构/表达，保留事实与来源 |
| TC-ED-04 | 字数超限 | 调整至要求范围，事实不丢失 |

### 4.4 事实核查 Agent

| 用例 | 输入 | 期望 |
| --- | --- | --- |
| TC-FC-01 | 全部有据 | `overall_result=PASSED`，claims 覆盖关键事实 |
| TC-FC-02 | 数字错误 | 对应 claim `CONTRADICTED`，`recommendation=REQUEST_RESEARCH` |
| TC-FC-03 | 引语与来源不符 | `CONTRADICTED`，附证据片段 |
| TC-FC-04 | 找不到证据 | `UNVERIFIED`，不得判为 `CONTRADICTED` |
| TC-FC-05 | 部分有据 | `overall_result=PARTIAL` |
| TC-FC-06 | 仅表达问题 | 报告可建议 `REQUEST_EDIT` |
| TC-FC-07 | 视角/评论内容 | 不作为事实声明核查 |
| TC-FC-08 | 证据缺失 | 校验失败重试；持续缺失则明确 `UNVERIFIED` |

### 4.5 审核发布 Agent

| 用例 | 输入 | 期望 |
| --- | --- | --- |
| TC-PB-01 | `chief_decision != APPROVE` | 拒绝进入发布 |
| TC-PB-02 | `fact_check_status == FAILED` | 拒绝进入发布 |
| TC-PB-03 | 正常通过 | 创建 `PENDING_PUBLISH` 记录 |
| TC-PB-04 | `user_confirmation=false` | 保持待发布 |
| TC-PB-05 | `user_confirmation=true` | 调用发布接口，记录 `PUBLISHED` |
| TC-PB-06 | 重复确认 | 幂等，不重复发布 |
| TC-PB-07 | 发布接口失败 | 保持 `PENDING_PUBLISH`，记录错误，可重试 |

---

## 5. 工作流分支测试

| 用例 | 场景 | 期望路由 / 状态 |
| --- | --- | --- |
| TC-WF-01 | 正常流程 | `chief_planning → reporter → editor → fact_checker → chief_review → APPROVE → publisher → 用户确认 → publish` |
| TC-WF-02 | 主编要求补充资料 | `chief_review → reporter → editor → fact_checker → chief_review` |
| TC-WF-03 | 主编要求编辑修改 | `chief_review → editor → fact_checker → chief_review` |
| TC-WF-04 | 主编转人工 | `chief_review → human_approval`，状态 `HUMAN_REVIEW` |
| TC-WF-05 | 人工通过 | `human_approval → publisher` |
| TC-WF-06 | 人工要求修改 | `human_approval → editor` |
| TC-WF-07 | 人工要求补充资料 | `human_approval → reporter` |
| TC-WF-08 | 人工终止 | 任务 `CANCELLED` |
| TC-WF-09 | 超过最大退回次数 | 强制 `HUMAN_REVIEW`，不无限循环 |
| TC-WF-10 | 修改稿件后 | 必须重新执行 `fact_checker`，报告绑定新版本 |
| TC-WF-11 | 用户暂缓发布 | 保持 `PENDING_PUBLISH` |
| TC-WF-12 | 用户确认发布 | `PUBLISHED`，记录 `published_at` |
| TC-WF-13 | 发布失败 | 保持 `PENDING_PUBLISH`，记录错误，可重试 |
| TC-WF-14 | 任务取消 | 在节点边界终止，`CANCELLED` |
| TC-WF-15 | 中断恢复 | 从最近检查点继续，不重复已完成节点 |
| TC-WF-16 | 同一任务并发执行 | 分布式锁 / 数据库唯一约束保证只执行一次 |

---

## 6. API 测试

| 用例 | 接口 | 期望 |
| --- | --- | --- |
| TC-API-01 | `POST /tasks` 正常 | 201，返回 `task_id`，状态 `CREATED` |
| TC-API-02 | 缺 `topic` / 非法 `target_length` | 400，code=1001 |
| TC-API-03 | 未认证访问 | 401 |
| TC-API-04 | 查询不存在任务 | 404，code=2001 |
| TC-API-05 | 任务列表分页 / 状态过滤 | 数据正确 |
| TC-API-06 | `GET /plan` | 返回结构化采编计划 |
| TC-API-07 | `GET /article` 与版本接口 | 当前版本与历史版本一致 |
| TC-API-08 | `GET /fact-check-reports/latest` | 报告绑定正确版本 |
| TC-API-09 | 非 `HUMAN_REVIEW` 提交人工审核 | 409，code=2002 |
| TC-API-10 | `human-review` 四种决策 | 路由与状态正确 |
| TC-API-11 | 非 `PENDING_PUBLISH` 确认发布 | 409 |
| TC-API-12 | `confirm=true` | 返回 `PUBLISHED` 或失败信息 |
| TC-API-13 | `confirm=false` | 保持 `PENDING_PUBLISH` |
| TC-API-14 | 重复确认 | 幂等，code=2004 或返回原结果 |
| TC-API-15 | 任务创建限流 | 超过 10 次/分钟返回 429 |

---

## 7. 异常与安全测试

| 用例 | 场景 | 期望 |
| --- | --- | --- |
| TC-EX-01 | LLM 超时 / 429 | 有限重试；耗尽后任务 `FAILED` 可恢复 |
| TC-EX-02 | 搜索服务不可用 | 记录错误，尝试备用搜索或要求补充资料 |
| TC-EX-03 | 网页抓取失败 | 跳过来源，不崩溃 |
| TC-EX-04 | 模型输出非法 / 缺字段 | Pydantic 拦截，重试或失败，不进入下一节点 |
| TC-EX-05 | 网页 Prompt 注入 | 不改变 Agent 行为，记录可疑内容 |
| TC-EX-06 | 恶意 URL（内网 / file://） | 工具拒绝 |
| TC-EX-07 | 越权发布 | 403 |
| TC-EX-08 | 日志 / 响应泄露密钥 | 无泄露 |
| TC-EX-09 | 超大网页抓取 | 截断，不 OOM |

---

## 8. 事实核查评测集

- **规模**：≥ 50 条标注断言；
- **构成**：正确 20 条、错误 15 条、无来源 10 条、过期 5 条、歧义 5 条；
- **指标**：
  - 断言抽取召回率 ≥ 90%；
  - 单条结论准确率 ≥ 90%；
  - 已知错误召回率 ≥ 85%，误报率 ≤ 15%；
  - 证据 URL 可访问率 ≥ 95%。

---

## 9. 端到端场景

| 场景 | 流程 | 通过标准 |
| --- | --- | --- |
| E2E-01 常规 | 一次通过 → 用户确认 → 发布 | 稿件带来源，发布记录生成 |
| E2E-02 补充资料 | `REQUEST_RESEARCH` → 记者补充 → 重检 → 通过 | 资料补齐，报告绑定新版本 |
| E2E-03 编辑修改 | `REQUEST_EDIT` → 编辑修改 → 重检 → 通过 | 修改留痕，事实不变 |
| E2E-04 人工审核 | `HUMAN_REVIEW` → 人工通过 | 流程恢复并进入待发布 |
| E2E-05 发布阻断 | 未确认直接调用发布 | 被拒绝 |
| E2E-06 中断恢复 | 执行中重启服务 | 从检查点继续至完成 |

---

## 10. 验收标准

- [ ] Agent 单元测试用例全部通过；
- [ ] 工作流分支 TC-WF-01 ~ TC-WF-16 全部通过；
- [ ] API 用例 TC-API-01 ~ TC-API-15 全部通过；
- [ ] 异常用例 TC-EX-01 ~ TC-EX-09 全部通过；
- [ ] 事实核查评测指标达标；
- [ ] 端到端 E2E-01 ~ E2E-06 全部通过；
- [ ] 未经用户确认的发布拦截率 100%；
- [ ] 修改稿件后 100% 重新核查；
- [ ] 核查报告与稿件版本一一对应，无「核查旧稿、发布新稿」；
- [ ] 中断恢复成功率 ≥ 90%；
- [ ] 测试报告归档至 `docs/08-testing/reports/`（后续创建）。

---

## 11. 缺陷分级

| 级别 | 定义 | 处理 |
| --- | --- | --- |
| Blocker | 阻断主流程、事实错误外流、绕过用户确认发布 | 修复前不得发布 |
| Critical | 分支错误、版本错配、数据丢失、恢复失败 | 当前迭代必须修复 |
| Major | 功能不符合预期但有绕行方案 | 当前迭代修复 |
| Minor | 文案、UI、非关键体验问题 | 可延后 |
