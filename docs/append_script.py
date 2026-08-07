import os

target = r'c:\Users\qianshengjia\Code\AI\nexent\docs\a2ui_integration_design.md'

content = r'''---

## 5. 卡片类型与使用指导

### 5.1 Info 卡片（信息展示）

**使用场景**：通知、状态展示、结果反馈

**代码示例**：

```python
from nexent.core.a2ui.a2ui_builder import A2UIBuilder
from nexent.core.utils.observer import ProcessType
import json

def show_info_card(observer, title, message):
    builder = A2UIBuilder(surface_id="info")

    # 1. 创建 Surface
    smsg = builder.build_create_surface(catalog="basic", title=title)
    observer.add_message("", ProcessType.A2UI_SURFACE, json.dumps(smsg, ensure_ascii=False))

    # 2. 构建卡片
    builder.add_card(
        title=title,
        body=message,
        actions=[
            {"text": "知道了", "name": "acknowledge", "payload": {"action": "acknowledged"}, "variant": "primary"},
        ],
    )

    # 3. 发送组件
    cmsg = builder.build_update_components()
    observer.add_message("", ProcessType.A2UI_COMPONENTS, json.dumps(cmsg, ensure_ascii=False))
```

**UI 预览**：

![Info 卡片](a2ui_samples/info_card.png)

**生成的组件结构**：

```
Card
├── Text (subtitle) → title
├── Text (body) → message
└── Row
    └── Button (primary) → "知道了"
```

### 5.2 Feedback 卡片（反馈收集）

**使用场景**：用户满意度调查、意见收集

**代码示例**：

```python
def show_feedback_card(observer, question, options, allow_custom=True):
    builder = A2UIBuilder(surface_id="feedback")

    smsg = builder.build_create_surface(catalog="hitl", title=question)
    observer.add_message("", ProcessType.A2UI_SURFACE, json.dumps(smsg, ensure_ascii=False))

    builder.add_text(question, "fb_q", "subtitle")
    builder.add_quick_replies(options=options, cid="fb_opts")
    if allow_custom:
        builder.add_text_area("补充说明", "请输入您的建议...", "fb_ta", "feedback.custom_input")
    builder.add_button("提交反馈", "submit_feedback", cid="fb_submit", variant="primary")

    cmsg = builder.build_update_components()
    observer.add_message("", ProcessType.A2UI_COMPONENTS, json.dumps(cmsg, ensure_ascii=False))
```

**UI 预览**：

![Feedback 卡片](a2ui_samples/feedback_card.png)

### 5.3 Confirmation 卡片（操作确认）

**使用场景**：危险操作确认、二次验证

**代码示例**：

```python
def show_confirmation_card(observer, title, message,
                            confirm_text="确认", cancel_text="取消",
                            confirm_payload=None):
    builder = A2UIBuilder(surface_id="confirm")

    smsg = builder.build_create_surface(catalog="hitl", title=title)
    observer.add_message("", ProcessType.A2UI_SURFACE, json.dumps(smsg, ensure_ascii=False))

    builder.add_card(
        title=title,
        body=message,
        actions=[
            {"text": cancel_text, "name": "cancel", "payload": {"action": "cancelled"}, "variant": "secondary"},
            {"text": confirm_text, "name": "confirm", "payload": confirm_payload or {"action": "confirmed"}, "variant": "primary"},
        ],
    )

    cmsg = builder.build_update_components()
    observer.add_message("", ProcessType.A2UI_COMPONENTS, json.dumps(cmsg, ensure_ascii=False))
```

**UI 预览**：

![Confirmation 卡片](a2ui_samples/confirmation_card.png)

### 5.4 Form 卡片（表单录入）

**使用场景**：数据录入、配置表单

**代码示例**：

```python
def show_form_card(observer, title, fields, submit_action, submit_payload=None):
    builder = A2UIBuilder(surface_id="form")

    smsg = builder.build_create_surface(catalog="hitl", title=title)
    observer.add_message("", ProcessType.A2UI_SURFACE, json.dumps(smsg, ensure_ascii=False))

    # 构建字段
    field_components = []
    for i, f in enumerate(fields):
        if f.get("type") == "text":
            fc = builder.add_text_field(
                label=f.get("label"), placeholder=f.get("placeholder"),
                cid=f"field_{i}", data_binding=f.get("binding"),
                required=f.get("required", False))
        elif f.get("type") == "textarea":
            fc = builder.add_text_area(
                label=f.get("label"), placeholder=f.get("placeholder"),
                cid=f"field_{i}", data_binding=f.get("binding"),
                rows=f.get("rows", 3))
        field_components.append(fc)

    # 构建表单
    builder.add_form(field_components, submit_action, submit_payload, title=title, cid="main_form")

    cmsg = builder.build_update_components()
    observer.add_message("", ProcessType.A2UI_COMPONENTS, json.dumps(cmsg, ensure_ascii=False))
```

**UI 预览**：

![Form 卡片](a2ui_samples/form_card.png)

**调用示例**：

```python
show_form_card(
    observer=observer,
    title="用户信息登记",
    fields=[
        {"type": "text", "label": "姓名", "placeholder": "请输入姓名", "binding": "user.name", "required": True},
        {"type": "text", "label": "邮箱", "placeholder": "请输入邮箱", "binding": "user.email", "required": True},
        {"type": "textarea", "label": "备注", "placeholder": "请输入备注", "binding": "user.notes"},
    ],
    submit_action="submit_user_info",
    submit_payload={"source": "agent_form"},
)
```

### 5.5 Rating 卡片（评分评价）

**使用场景**：用户评分、满意度评价

**代码示例**：

```python
def show_rating_card(observer, title, allow_review=True, max_value=5):
    builder = A2UIBuilder(surface_id="rating")

    smsg = builder.build_create_surface(catalog="hitl", title=title)
    observer.add_message("", ProcessType.A2UI_SURFACE, json.dumps(smsg, ensure_ascii=False))

    builder.add_text(title, "rating_title", "subtitle")
    builder.add_rating(max_value=max_value, cid="main_rating", data_binding="rating.value")
    if allow_review:
        builder.add_text_area("您的评价", "请写下您的建议...", "review_ta", "rating.review", rows=3)
    builder.add_button("提交评价", "submit_rating", cid="rating_submit", variant="primary")

    cmsg = builder.build_update_components()
    observer.add_message("", ProcessType.A2UI_COMPONENTS, json.dumps(cmsg, ensure_ascii=False))
```

**UI 预览**：

![Rating 卡片](a2ui_samples/rating_card.png)

### 5.6 OutputCardTool 调用示例

Agent 可通过 `output_card` 工具直接生成卡片：

```python
# Agent 工具调用
tool_calls = [{
    "name": "output_card",
    "arguments": {
        "card_type": "feedback",
        "title": "请确认操作",
        "message": "即将删除 3 条记录，是否继续？",
        "options": ["确认删除", "取消"],
        "allow_custom_input": False,
    }
}]
```

### 5.7 组件类型速查表

| 组件 | Builder 方法 | 关键参数 | 使用场景 |
|------|-------------|---------|---------|
| Row | `add_row()` | `children`, `gap` | 水平按钮组 |
| Column | `add_column()` | `children`, `gap` | 垂直列表 |
| Card | `add_card()` | `title`, `body`, `actions` | 信息卡片 |
| Text | `add_text()` | `text`, `variant` | 标题/正文 |
| Button | `add_button()` | `text`, `action_name`, `variant` | 操作按钮 |
| TextField | `add_text_field()` | `label`, `placeholder`, `data_binding` | 单行输入 |
| TextArea | `add_text_area()` | `label`, `placeholder`, `data_binding` | 多行输入 |
| Form | `add_form()` | `fields`, `submit_action` | 表单容器 |
| Rating | `add_rating()` | `max_value`, `data_binding` | 星级评分 |
| QuickReplies | `add_quick_replies()` | `options` | 快捷回复按钮组 |

---

## 6. 人在回路交互机制

### 6.1 完整交互流程

```
Agent 运行时                后端 API                   前端
    │  1. request_user_feedback()
    │     ├── A2UIHITLService.create_interaction()
    │     │     → 生成 interaction_id
    │     ├── A2UIBuilder 构建卡片
    │     └── observer.add_message
    │           → SSE: a2ui_surface + a2ui_components
    │ ─────────────────────────────────────────────────►
    │                         │               2. 渲染卡片
    │                         │               3. 用户点击
    │  4. POST /api/a2ui/action ◄────────────────────────
    │     {interaction_id, action, payload}
    │  5. A2UIHITLService.submit_response() → 唤醒 asyncio.Event
    │  6. Agent 收到响应，继续执行
    │     → SSE: hitl_form_response
    │ ─────────────────────────────────────────────────►
    │                         │               7. 更新状态
    │  8. a2ui_delete_surface → 清理 UI
```

### 6.2 使用示例

```python
async def confirm_operation_tool(self, query: str):
    from services.a2ui_hitl_service import request_user_feedback

    response = await request_user_feedback(
        agent_run_info=self.agent_run_info,
        conversation_id=self.conversation_id,
        user_id=self.user_id,
        agent_id=self.agent_id,
        question=f"确认执行操作: {query}?",
        options=["确认执行", "取消"],
        allow_custom_input=True,
        timeout_seconds=300,
        observer=self.observer,
    )

    if response is None:
        return "操作超时，已自动取消"

    user_choice = response.get("payload", {}).get("value")
    if user_choice == "确认执行":
        await self.execute_operation(query)
        return "操作已执行"
    else:
        return "操作已取消"
```

### 6.3 状态机

```
                    create_interaction()
                          │
                          ▼
                      ┌─────────┐
                      │ PENDING │◄──────────────┐
                      └────┬────┘               │
                           │                    │
            submit_response()              cancel_interaction()
                           │                    │
                           ▼                    ▼
                     ┌──────────┐          ┌───────────┐
                     │ RESPONDED│          │ CANCELLED │
                     └──────────┘          └───────────┘

            timeout (无响应)
                           │
                           ▼
                     ┌──────────┐
                     │ TIMEOUT  │
                     └──────────┘
```

### 6.4 超时与降级策略

| 场景 | 处理方式 |
|------|---------|
| 用户在超时时间内响应 | 正常返回用户输入，Agent 继续执行 |
| 超时未响应 | 返回 None，Agent 可选择重试或跳过 |
| 用户取消 | 返回 None，Agent 正常终止流程 |
| 网络断开后重连 | 前端通过 GET /api/a2ui/interactions/{id} 恢复状态 |
| Agent 崩溃重启 | 交互状态可持久化到 Redis（Phase 3） |

---

## 7. 数据流全景

### 7.1 Agent 工具调用流

```
Agent 决策调用 output_card 工具
    │
    ▼
OutputCardTool.execute(card_type, title, message, ...)
    │
    ▼
根据 card_type 选择构建策略:
    ├── info         → builder.add_card(title, message, actions)
    ├── feedback     → builder.add_text + add_quick_replies + add_text_area
    ├── confirmation → builder.add_card(title, message, [cancel, confirm])
    ├── form         → builder.add_form(fields, submit_action)
    └── rating       → builder.add_rating + add_text_area
    │
    ▼
observer.add_message(ProcessType.A2UI_SURFACE, surface_msg)
observer.add_message(ProcessType.A2UI_COMPONENTS, components_msg)
    │
    ▼
SSE → 前端 chatStreamHandler → A2UIRenderer → Ant Design 渲染
```

### 7.2 SSE 消息序列

```
Event 1: {"type": "a2ui_surface", "content": "{surface_desc}"}
Event 2: {"type": "a2ui_components", "content": "{component_tree}"}
... (可能有多个 components 更新)
Event N: {"type": "a2ui_delete_surface", "content": "{surface_id}"}
```

### 7.3 消息处理时序

```
时间轴  0ms    50ms   100ms  150ms  200ms  250ms
        │      │      │      │      │      │
Agent   ├─ SSE1─┤      │      │      │      │
        │      ├─ SSE2─┤      │      │      │
        │      │      ├─ SSE3─┤      │      │
        │      │      │      ├─ SSE4─┤      │
        │      │      │      │      ├─ SSE5─┤
前端    ├─ 接收  ├─ 解析 ├─ 合并 ├─ 渲染 ├─ 更新
        │      │      │      │      │      │
UI          [卡片出现]  [交互可用]  [更新状态]
```

---

## 8. API 端点设计

### 8.1 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/a2ui/action` | 提交用户操作响应 |
| GET | `/api/a2ui/interactions/{conversation_id}` | 查询待处理交互列表 |
| DELETE | `/api/a2ui/interactions/{interaction_id}` | 取消待处理交互 |

### 8.2 请求/响应格式

**POST /api/a2ui/action**

请求：
```json
{
  "interaction_id": "surface_abc123",
  "action": "submit_feedback",
  "payload": {
    "feedback.custom_input": "非常好用",
    "rating.value": 5
  },
  "user_id": "user_xxx"
}
```

响应：
```json
{"status": "ok", "interaction_id": "surface_abc123"}
```

**GET /api/a2ui/interactions/{conversation_id}**

响应：
```json
{
  "status": "ok",
  "interactions": [
    {
      "interaction_id": "abc123",
      "status": "pending",
      "question": "请确认操作",
      "payload": {"options": ["确认", "取消"]},
      "created_at": 1728192000.0
    }
  ]
}
```

### 8.3 错误码

| HTTP 状态码 | 说明 |
|------------|------|
| 404 | 交互不存在或已完成 |
| 400 | 交互状态不允许操作 |
| 403 | 用户无权限访问 |
| 500 | 服务内部错误 |

---

## 9. 实施计划

### Phase 1: 基础设施（1-2 周）

| 任务 | 交付物 | 负责层 |
|------|--------|--------|
| 新增 ProcessType | `observer.py` 枚举扩展 | SDK |
| 实现 A2UI Builder | `a2ui_builder.py` | SDK |
| 实现 OutputCardTool | `a2ui_card_tool.py` | SDK |
| 实现 HITL Service | `a2ui_hitl_service.py` | 后端服务 |
| 实现 API 端点 | `a2ui_app.py` | 后端 API |
| 单元测试 | pytest 测试用例 | 全部 |

### Phase 2: 前端集成（1-2 周）

| 任务 | 交付物 | 负责层 |
|------|--------|--------|
| TypeScript 类型定义 | `chat.ts` 扩展 | 前端 |
| 消息类型常量 | `chatConfig.ts` 扩展 | 前端 |
| A2UI Renderer | `A2UIRenderer.tsx` | 前端 |
| Stream Handler 修改 | `chatStreamHandler.tsx` 分支 | 前端 |
| Ant Design 集成 | 组件映射实现 | 前端 |

### Phase 3: 测试与优化（1 周）

| 任务 | 交付物 |
|------|--------|
| 集成测试 | Agent→SSE→前端 端到端验证 |
| HITL 流程测试 | 超时、取消、恢复场景 |
| 性能测试 | 大组件量渲染性能 |
| 兼容性测试 | 现有 CARD 类型不受影响 |
| 用户体验打磨 | 加载状态、动画效果 |

### 里程碑

```
Week 1-2  ──► Phase 1 完成
Week 3-4  ──► Phase 2 完成 + Phase 3 启动
Week 5    ──► Phase 3 完成 + 全量测试
```

---

## 10. 风险与注意事项

### 10.1 兼容性

- **现有 CARD 类型**：保持 100% 向后兼容，不修改现有 CARD 处理逻辑
- **新功能独立**：A2UI 使用独立的 ProcessType 枚举值，与现有类型互不干扰
- **渐进式部署**：可通过功能开关（feature flag）控制 A2UI 功能的启用/禁用

### 10.2 性能

- **组件数量**：单个 Surface 组件数量建议 < 50 个，避免渲染性能问题
- **SSE 频率**：避免过于密集的 A2UI 消息推送，建议节流（100ms 最小间隔）
- **数据量**：大体积数据（如表格）建议使用分页或懒加载
- **内存管理**：Surface 使用完毕后及时调用 `delete_surface` 释放资源

### 10.3 安全性

- **权限验证**：POST /api/a2ui/action 需验证用户对会话的访问权限
- **输入校验**：HITL 表单提交数据需在后端进行校验和清洗
- **XSS 防护**：用户输入内容在前端渲染时需转义
- **CSRF 防护**：API 端点需遵守项目现有认证机制

### 10.4 用户体验

- **HITL 超时**：超时后需给用户友好提示，Agent 应优雅降级
- **网络断开**：前端重连后通过 API 恢复待处理交互状态
- **加载状态**：组件渲染过程中显示适当的加载指示
- **移动端适配**：组件布局需响应式设计，适配移动端

### 10.5 技术债务

- **内存存储**：当前 HITL 交互存储在内存中，服务重启会丢失。Phase 3 可引入 Redis
- **组件映射**：Ant Design 组件映射覆盖有限，复杂组件需逐步完善
- **国际化**：A2UI 组件文本需支持 i18n
'''

with open(target, 'a', encoding='utf-8') as f:
    f.write(content)

print('Successfully appended content to', target)