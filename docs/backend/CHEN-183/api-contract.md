# API 契约 — CHEN-183 对话管理功能

| 字段 | 值 |
| --- | --- |
| **创建者** | BackendDev-6fe9f90e-f4eb-4c04-9c81-3b953d334b10 |
| **创建时间** | 2026-09-20 |
| **版本** | v1.0 |
| **状态** | 草案（待 G2 汇合） |
| **JIRA** | CHEN-183 |
| **上游 PRD** | Issue CHEN-183《对话管理功能：按日期/智能体/名称查看对话》（全量自包含） |
| **架构设计** | `docs/design/CHEN-183/design.md`（Git，分支 `agent/architect/02700bba0782`，提交 `546c51b79`，v0.3） |
| **对应实现分支** | `agent/backenddev/11a4b9e4707d`（`nexent` 仓库） |

## 1. 概述

本契约定义 CHEN-183「对话管理」功能的后端接口。

- 范围：在现有 `GET /conversation/list` 上**扩展**筛选能力，并复用现有 `ConversationResponse` 信封，不破坏任何既有消费方。
- 与架构设计「实现步骤（后端）」步骤 1、非功能需求（性能/可观测性）对应。
- 非目标：不做会话编辑/删除/合并、不做全文/语义搜索、不做批量导出；详情查看复用现有 `GET /conversation/{conversation_id}`。

## 2. 端点清单

| API-ID | 方法 | 路径 | 对应 BR-/AC- |
| --- | --- | --- | --- |
| API-CHEN183-01 | GET | `/conversation/list` | AC-1、AC-2、AC-3、AC-4、AC-6、REV-1（分桶随筛选同口径） |
| API-CHEN183-02 | GET | `/conversation/{conversation_id}`（现有，复用） | AC-5（查看完整消息） |

> 注：API-CHEN183-02 为既有端点，本契约仅声明其契约不变，用于 AC-5 详情查看。

## 3. 端点详情

### 3.1 API-CHEN183-01：GET /conversation/list

**鉴权**：`authorization` Header（沿用现有会话鉴权，`get_current_user_id`）。未认证/会话过期 → HTTP 401（`TokenExpiredError`），业务码约定 `code != 0`。

**查询参数（Query）**：

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `offset` | integer | 否（默认 0） | 分页偏移，`>= 0` |
| `limit` | integer | 否（后端默认 None，前端约定 20） | 单页条数，`1..100` |
| `start_date_ms` | integer | 否 | 日期区间起点（Unix ms 时间戳），**含端点**，即 `create_time >= start_date_ms` |
| `end_date_ms` | integer | 否 | 日期区间终点（Unix ms 时间戳），**含端点**，即 `create_time <= end_date_ms` |
| `agent_id` | integer | 否 | 按智能体过滤，`agent_id == ?`（nullable，可传 `null` 匹配无智能体的会话） |
| `keyword` | string | 否 | 按会话名称模糊包含匹配（`conversation_title ilike %keyword%`，大小写不敏感） |
| `today_start_ms` | integer | **是** | 今日分桶起点（Unix ms 时间戳，`>= 0`） |
| `week_start_ms` | integer | **是** | 近 7 天分桶起点（Unix ms 时间戳，`>= 0`） |

**SUG-C 决策（必填性）**：`today_start_ms` / `week_start_ms` **保持现行为必填**。

- 依据：当前实现 `backend/apps/conversation_management_app.py:66-67` 中二者为 `Annotated[int, Query(ge=0)]` 无默认值，属必填；前端 `frontend/services/conversationService.ts:37-46` 与 `frontend/hooks/chat/useConversationManagement.ts:85-90` 的现有消费方始终传入二者。
- 理由：保持向后兼容，避免破坏既有聊天侧栏与 legacy chat 消费方（对应设计 RISK-5「改签名可能波及」）；本次新增的筛选参数 `start_date_ms`/`end_date_ms`/`agent_id`/`keyword` 均为可选。
- 行为：缺省筛选参数（仅传必填的 `today_start_ms`/`week_start_ms`）时，返回行为与现状完全一致。

**响应（HTTP 200）**：复用现有 `ConversationResponse` 信封（实际代码位置：`backend/consts/model.py:898`，`ConversationResponse`：`code: int = 0`、`message: str = "success"`、`data: Any`）。

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "conversation_id": 123,
        "conversation_title": "示例对话",
        "agent_id": 42,
        "chat_mode": "execution",
        "create_time": 1758360000000,
        "update_time": 1758360000000
      }
    ],
    "metadata": {
      "total": 1,
      "today": 1,
      "last_7_days": 0,
      "older": 0
    }
  }
}
```

**数据模型（items 字段）**：与现状一致（`backend/database/conversation_db.py:920-929`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `conversation_id` | integer | 会话 ID |
| `conversation_title` | string | 会话标题 |
| `agent_id` | integer \| null | 智能体 ID |
| `chat_mode` | string | 聊天模式，缺省为 `execution` |
| `create_time` | integer | 创建时间（ms 时间戳） |
| `update_time` | integer | 更新时间（ms 时间戳） |

**metadata 分桶口径（REV-1）**：`total`/`today`/`last_7_days`/`older` 均为窗口计数（`conversation_db.py:894-900`），作用于同一 WHERE 链、同一次查询、**无子查询**；有筛选时四桶与 `total` 同口径（随筛选生效），无筛选时保持现状。

**排序**：`create_time DESC, conversation_id DESC`（现状）。

**错误码**：沿用现有约定——
- HTTP 401：会话过期/未授权（`TokenExpiredError` 或 `get_current_user_id` 未返回用户）。
- HTTP 500：服务端异常（`code != 0`，`message` 携带详情）。
- 参数校验失败（如 `limit` 越界）：HTTP 422（FastAPI 默认）。

**幂等性**：只读查询，天然幂等。

### 3.2 API-CHEN183-02：GET /conversation/{conversation_id}（现有，复用）

- 鉴权：`authorization` Header。
- 响应：复用 `ConversationResponse` 信封，`data` 为该会话完整消息历史（`get_conversation_history_service`，`conversation_management_app.py:177-199`）。
- 本端点契约不变，供前端「查看」操作调用（AC-5）。

## 4. 通用约定

- **时间格式**：所有时间戳为 Unix ms 时间戳（整数）。
- **分页**：`offset`/`limit` 游标式翻页；`limit` 默认 20，上限 100。
- **日期区间**：`[start_date_ms, end_date_ms]` 闭区间，含端点；仅传一端时按单侧过滤（建议两端同时传）。
- **名称模糊**：`keyword` 对 `conversation_title` 做包含匹配（SQL `ilike`），大小写不敏感，不做全文/语义搜索。
- **三条件组合**：`start_date_ms`/`end_date_ms`、`agent_id`、`keyword` 在 SQL 层以 `and_` 组合（AC-4）。
- **用户隔离**：始终附加 `created_by == user_id` 条件，越权不可见（RISK-2 之外）。
- **日志**：后端查询日志记录筛选参数（日期区间/agent/keyword）与分桶口径（非功能-可观测性）。
- **模型路径核对（SUG-A）**：设计文档「理解」节写 `conversation_models.py`，实际代码中 `ConversationRequest`/`ConversationResponse` 定义于 `backend/consts/model.py:894/898`；本契约以实际代码为准。

## 5. 数据模型 / 字段变更

- 无新增字段、无表结构变更（索引覆盖 `(create_time, agent_id)` 属 DDL，若保留须并入版本化迁移批次，见设计后端步骤 2 / SUG-2）。
- 请求侧：仅新增可选 query 参数，不改变任何请求体。
- 响应侧：`ConversationResponse` 信封与 `data` 结构完全不变。

## 6. TDD / 测试映射

| API-ID | 单元测试覆盖 |
| --- | --- |
| API-CHEN183-01 | 无筛选（向后兼容）、单条件筛选（日期/agent/keyword）、三条件组合、含端点日期边界、`keyword` 大小写不敏感、metadata 分桶随筛选同口径、必填参数校验、401/500 错误码 |
| API-CHEN183-02 | 复用现状，无新增测试（契约不变） |

## 7. 修订记录

| 日期 | 版本 | 作者 | 变更 |
| --- | --- | --- | --- |
| 2026-09-20 | v1.0 | BackendDev-6fe9f90e-f4eb-4c04-9c81-3b953d334b10 | 初稿：定义 `GET /conversation/list` 扩展筛选契约；登记 SUG-C（`today_start_ms`/`week_start_ms` 保持必填）；核对模型路径（实际 `backend/consts/model.py:894/898`） |
