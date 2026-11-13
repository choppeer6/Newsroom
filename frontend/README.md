# Frontend

Vue 3 + Vite + TypeScript 前端应用（待实现）。

## 规划目录

```
frontend/
├── src/
│   ├── api/            # Axios 封装、SSE 客户端
│   ├── views/
│   │   ├── TaskCreate.vue
│   │   ├── TaskList.vue
│   │   ├── TaskDetail.vue
│   │   ├── ArticleReview.vue
│   │   ├── FactCheckReport.vue
│   │   └── PublishConfirm.vue
│   ├── components/     # 状态标签、事件时间线、来源列表、版本 diff
│   ├── stores/         # Pinia
│   ├── router/
│   └── types/          # 与后端 Schema 对齐
├── package.json
└── vite.config.ts
```

## 核心页面

| 页面 | 功能 |
| --- | --- |
| 任务创建 | 提交选题、背景描述、风格、目标篇幅、重点方向 |
| 任务列表 | 状态过滤、进度概览 |
| 任务详情 | 采编计划、Agent 时间线、SSE 实时进度 |
| 稿件审阅 | 正文、资料来源、版本切换、审核意见 |
| 事实核查 | 核查结果、证据来源、总体结论 |
| 审核与发布 | 人工审核决定、待发布状态、用户确认发布 |

## 接口约定

- Base URL：`/api/news`
- 认证：`Authorization: Bearer <JWT>`
- 进度：`GET /api/news/tasks/{task_id}/events`（SSE，可选）

详见 [API 接口设计文档](../docs/06-api/api-specification.md)。
