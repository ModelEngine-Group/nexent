# A2UI 集成设计方案 — Agent 卡片输出与人在回路交互

> **版本**: v2.0 | **日期**: 2026-08-05 | **状态**: 设计中

---

## 1. 需求概述

### 1.1 需求背景

Nexent 平台当前已具备基础的 Agent 卡片输出能力（通过 `ProcessType.CARD` 类型将 JSON 内容透传到前端渲染），但存在核心痛点：

1. **卡片表现力不足**：仅支持简单 JSON 文本透传，无法表达复杂布局结构
2. **无交互闭环**：卡片仅用于展示，无法通过卡片操作向 Agent 反馈信息
3. **组件不统一**：缺乏标准化组件库，渲染方式不一致
4. **无增量更新**：组件无法动态更新，每次变更需全量重绘

通过引入 A2UI（Agent-to-UI）标准协议，Agent 可在运行时生成结构化 UI 组件树，结合"人在回路"（HITL）机制实现双向交互。

### 1.2 需求目标

| 编号 | 目标 | 描述 |
|------|------|------|
| G1 | Agent 输出卡片化 | 将结构化输出渲染为精美卡片组件 |
| G2 | 交互表单生成 | 动态生成表单、选项、输入框等交互组件 |
| G3 | 用户反馈闭环 | 形成 Agent→UI→User→Agent 闭环 |
| G4 | A2UI 标准协议 | 遵循 A2UI 规范，支持 Surface 管理和数据绑定 |
| G5 | 向后兼容 | 保持现有 `CARD` 类型完整兼容 |

### 1.3 参考

- [A2UI 官方规范](https://a2ui.org/)
- [openJiuwen 项目](https://github.com/openJiuwen-ai/jiuwenswarm)
- 现有代码：`sdk/nexent/core/utils/observer.py`、`frontend/types/chat.ts`、`frontend/const/chatConfig.ts`、`frontend/app/[locale]/chat/streaming/chatStreamHandler.tsx`

---

## 2. 现有功能分析

### 2.1 现有卡片处理机制

#### 2.1.1 后端实现

**ProcessType 定义**（`sdk/nexent/core/utils/observer.py:15-47`）：

```python
class ProcessType(Enum):
    # 现有类型 (节选)
    CARD = "card"               # 现有卡片类型
    TOOL = "tool"
    NL2A = "nl2a"
    SKILL_ARTIFACT = "skill_artifact"
    MEMORY_SEARCH = "memory_search"
    MAX_STEPS_REACHED = "max_steps_reached"
    VERIFICATION = "verification"
    PLAN = "plan"
    PLAN_STEP_UPDATE = "plan_step_update"
    AUTOMATION_PROPOSAL = "automation_proposal"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    # ... 其余类型
```

**卡片发送方式**（`observer.py:443-492`）：

```python
self.observer.add_message(
    agent_name="",
    process_type=ProcessType.CARD,
    content=json.dumps(card_content, ensure_ascii=False)
)
```

消息经 `Message.to_json()` 序列化为 JSON 格式后，通过 SSE（Server-Sent Events）经 `StreamingChannel` 推送到前端。

#### 2.1.2 前端实现

**消息类型定义**（`frontend/const/chatConfig.ts:122-152`）：

```typescript
messageTypes: {
    CARD: "card" as const,            // 现有卡片类型
    FINAL_ANSWER: "final_answer" as const,
    ERROR: "error" as const,
    // ... 其他类型
}
```

**卡片渲染处理**（`chatStreamHandler.tsx:753-784`）：

```typescript
case chatConfig.messageTypes.CARD:
    currentStep.contents.push({
        id: `card-${Date.now()}-...`,
        type: chatConfig.messageTypes.CARD,
        content: messageContent,
        expanded: true,
        timestamp: Date.now(),
    });
    lastContentType = chatConfig.contentTypes.CARD;
    break;
```

#### 2.1.3 数据流架构

```
Agent Runtime
    │
    ▼
MessageObserver.add_message(process_type=CARD, content=JSON)
    │
    ▼
Message.to_json() → JSON String
    │
    ▼
SSE Stream (StreamingChannel)
    │
    ▼
chatStreamHandler.tsx → handleStreamResponse()
    │
    ▼
switch(messageType) → case "card":
    │
    ▼
StepContent { type: "card", content: JSON }
    │
    ▼
Chat UI 渲染（Card 组件）
```

### 2.2 现有机制的局限性

| 维度 | 现有实现 | 具体问题 |
|------|---------|---------|
| **卡片类型** | 简单 JSON 透传 | 无法表达结构化布局、组件嵌套 |
| **布局能力** | 无布局支持 | 无法实现网格、表单、列表 |
| **交互能力** | 仅展示无交互 | 无法获取用户操作反馈 |
| **数据绑定** | 无绑定机制 | 组件无法动态响应变化 |
| **增量更新** | 不支持 | 每次变更需全量重绘 |
| **标准化** | 自定义格式 | 无统一标准 schema |
| **超时恢复** | 无处理 | 超时后无法优雅降级 |
| **多 Surface** | 单平面 | 无法管理多个独立 UI 区域 |

---

## 3. A2UI 集成方案

### 3.1 架构设计

#### 3.1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Agent 运行时 (SDK)                              │
│  ┌─────────────────────┐  ┌────────────────────────────────────┐  │
│  │   A2UI Builder      │  │   HITL Interaction Manager          │  │
│  │  (a2ui_builder.py)  │  │  (a2ui_hitl_service.py)            │  │
│  └─────────┬───────────┘  └──────────────┬─────────────────────┘  │
│            ▼                               ▼                        │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │              MessageObserver (observer.py)                   │  │
│  │  A2UI_SURFACE / A2UI_COMPONENTS / A2UI_DATA_MODEL / ...      │  │
│  └─────────────────────────┬────────────────────────────────────┘  │
└─────────────────────────────┼───────────────────────────────────────┘
                              ▼ SSE
┌─────────────────────────────────────────────────────────────────────┐
│              后端 API 层 (a2ui_app.py)                              │
│  POST /api/a2ui/action · GET /api/a2ui/interactions/{id} · DELETE  │
└─────────────────────────────┬───────────────────────────────────────┘
                              ▼ HTTP/SSE
┌─────────────────────────────────────────────────────────────────────┐
│                       前端应用                                       │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  A2UIRenderer.tsx → Ant Design Components (Row/Col/Card/...) │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  chatStreamHandler.tsx → 新增 a2ui_* 消息处理分支            │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.1.2 A2UI 消息流

```
Agent 运行时                后端 API                   前端
    │  1. builder.create_surface()                                    │
    │     → SSE: {type:"a2ui_surface", content:{...}}                │
    │ ─────────────────────────────────────────────────────────►     │
    │                         │                        │ 创建 Surface
    │  2. builder.build_update_components()                           │
    │     → SSE: {type:"a2ui_components", content:{...}}             │
    │ ─────────────────────────────────────────────────────────►     │
    │                         │                        │ 渲染组件树
    │                                         3. 用户操作
    │              4. POST /api/a2ui/action ◄─────────────────────── │
    │  5. HITLService 唤醒 Agent 继续执行
    │  6. 更新组件 → SSE → 前端更新渲染
    │  7. builder.build_delete_surface() → 清理
```

#### 3.1.3 SSE 消息格式

所有 A2UI 消息遵循现有 SSE JSON 格式规范：

```json
{
  "type": "a2ui_surface",
  "content": { "surfaceId": "s_001", "catalog": "basic", "title": "搜索结果", ... },
  "agent_id": "agent_xxx",
  "agent_name": "搜索Agent",
  "depth": 0,
  "invocation_id": null
}
```

### 3.2 后端修改方案

#### 3.2.1 新增 ProcessType 定义

**修改文件**: `sdk/nexent/core/utils/observer.py`

在 `ProcessType` 枚举中新增：

```python
class ProcessType(Enum):
    # === 现有类型保持不变 ===
    # ... (省略)

    # === A2UI 新增类型 ===
    A2UI_SURFACE = "a2ui_surface"
    A2UI_COMPONENTS = "a2ui_components"
    A2UI_DATA_MODEL = "a2ui_data_model"
    A2UI_DELETE_SURFACE = "a2ui_delete_surface"

    # === HITL 新增类型 ===
    HITL_FORM = "hitl_form"
    HITL_FORM_RESPONSE = "hitl_form_response"
    HITL_TIMEOUT = "hitl_timeout"
```

在 `_init_message_transformers()` 中注册新类型（使用默认透传）：

```python
def _init_message_transformers(self):
    default_transformer = DefaultTransformer()
    # ... (现有注册保持不变)

    self.transformers.update({
        ProcessType.A2UI_SURFACE: default_transformer,
        ProcessType.A2UI_COMPONENTS: default_transformer,
        ProcessType.A2UI_DATA_MODEL: default_transformer,
        ProcessType.A2UI_DELETE_SURFACE: default_transformer,
        ProcessType.HITL_FORM: default_transformer,
        ProcessType.HITL_FORM_RESPONSE: default_transformer,
        ProcessType.HITL_TIMEOUT: default_transformer,
    })
```

#### 3.2.2 新增 A2UI 组件生成器

**新文件**: `sdk/nexent/core/a2ui/__init__.py`

```python
from .a2ui_builder import A2UIBuilder, A2UIComponent, A2UISurface
__all__ = ["A2UIBuilder", "A2UIComponent", "A2UISurface"]
```

**新文件**: `sdk/nexent/core/a2ui/a2ui_builder.py`

```python
"""
A2UI Component Builder — 提供构建 A2UI 组件树的流式 API。
"""
from __future__ import annotations
import json, uuid
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class A2UIComponent:
    id: str
    component: str
    children: list[str] = field(default_factory=list)
    text: Optional[str] = None
    variant: Optional[str] = None
    icon: Optional[str] = None
    data_binding: Optional[str] = None
    action: Optional[dict] = None
    props: dict = field(default_factory=dict)

    def to_dict(self):
        r = {"id": self.id, "component": self.component}
        if self.children: r["children"] = self.children
        if self.text is not None: r["text"] = self.text
        if self.variant is not None: r["variant"] = self.variant
        if self.icon is not None: r["icon"] = self.icon
        if self.data_binding is not None: r["dataBinding"] = self.data_binding
        if self.action is not None: r["action"] = self.action
        if self.props: r["props"] = self.props
        return r

class A2UIBuilder:
    def __init__(self, surface_id=None):
        self._sid = surface_id or f"surface_{uuid.uuid4().hex[:8]}"
        self._components = {}
        self._root_ids = []
        self._data_model = {}
        self._created = False

    def create_surface(self, catalog="basic", title=None):
        self._created = True
        return {"surfaceId": self._sid, "catalog": catalog, "title": title,
                "components": [], "dataModel": {}, "rootIds": []}

    def delete_surface(self):
        return {"surfaceId": self._sid}

    def add_row(self, children=None, cid=None, gap="8px"):
        return self._add("Row", cid=cid, children=children, props={"gap": gap})

    def add_column(self, children=None, cid=None, gap="8px"):
        return self._add("Column", cid=cid, children=children, props={"gap": gap})

    def add_text(self, text, cid=None, variant="body", data_binding=None):
        return self._add("Text", cid=cid, text=text, variant=variant,
                         data_binding=data_binding)

    def add_button(self, text, action_name, action_payload=None,
                   cid=None, variant="primary"):
        return self._add("Button", cid=cid, text=text, variant=variant,
            action={"event": {"name": action_name, "payload": action_payload or {}}})

    def add_card(self, title=None, body=None, actions=None, cid=None):
        card_id = cid or f"card_{uuid.uuid4().hex[:8]}"
        child_ids = []
        if title:
            t = self.add_text(title, f"{card_id}_title", "subtitle")
            child_ids.append(t.id)
        if body:
            b = self.add_text(body, f"{card_id}_body", "body")
            child_ids.append(b.id)
        if actions:
            ids = []
            for i, a in enumerate(actions):
                btn = self.add_button(a.get("text","Action"), a.get("name","action"),
                                      a.get("payload"), f"{card_id}_btn_{i}",
                                      a.get("variant","secondary"))
                ids.append(btn.id)
            if ids:
                row = self.add_row(ids, f"{card_id}_actions")
                child_ids.append(row.id)
        return self._add("Card", cid=card_id, children=child_ids)

    def add_quick_replies(self, options, cid=None):
        btns = []
        for i, opt in enumerate(options):
            if isinstance(opt, str):
                b = self.add_button(opt, "quick_reply", {"value": opt},
                                    f"qr_{i}", "secondary")
            else:
                b = self.add_button(opt.get("text"), opt.get("name","quick_reply"),
                                    opt.get("payload"), opt.get("id",f"qr_{i}"),
                                    opt.get("variant","secondary"))
            btns.append(b.id)
        return self.add_row(btns, cid or f"qr_{uuid.uuid4().hex[:8]}")

    def add_text_field(self, label=None, placeholder=None, cid=None,
                       data_binding=None, required=False):
        return self._add("TextField", cid=cid or f"tf_{uuid.uuid4().hex[:8]}",
            props={"label":label,"placeholder":placeholder,"required":required},
            data_binding=data_binding)

    def add_text_area(self, label=None, placeholder=None, cid=None,
                      data_binding=None, rows=3):
        return self._add("TextArea", cid=cid or f"ta_{uuid.uuid4().hex[:8]}",
            props={"label":label,"placeholder":placeholder,"rows":rows},
            data_binding=data_binding)

    def add_form(self, fields, submit_action, submit_payload=None,
                  title=None, cid=None):
        fid = cid or f"form_{uuid.uuid4().hex[:8]}"
        child_ids = []
        if title:
            t = self.add_text(title, f"{fid}_title", "subtitle")
            child_ids.append(t.id)
        for f in fields:
            child_ids.append(f.id)
        btn = self.add_button("Submit", submit_action, submit_payload,
                              f"{fid}_submit", "primary")
        child_ids.append(btn.id)
        return self._add("Form", cid=fid, children=child_ids,
                         props={"submitPayload": submit_payload or {}})

    def add_rating(self, max_value=5, cid=None, data_binding=None):
        return self._add("Rating", cid=cid or f"rating_{uuid.uuid4().hex[:8]}",
            props={"maxValue": max_value},
            data_binding=data_binding or "rating.value")

    def build_create_surface(self, catalog="basic", title=None):
        return self.create_surface(catalog=catalog, title=title)

    def build_update_components(self):
        if not self._created: self.create_surface()
        return {"surfaceId": self._sid,
                "components": [c.to_dict() for c in self._components.values()],
                "rootIds": self._root_ids, "dataModel": self._data_model}

    def build_delete_surface(self):
        return self.delete_surface()

    def _add(self, component, cid=None, children=None, text=None,
             variant=None, icon=None, data_binding=None, action=None, props=None):
        comp_id = cid or f"{component.lower()}_{uuid.uuid4().hex[:8]}"
        child_ids = []
        if children:
            for ch in children:
                child_ids.append(ch.id if isinstance(ch, A2UIComponent) else ch)
        comp = A2UIComponent(id=comp_id, component=component, children=child_ids,
                              text=text, variant=variant, icon=icon,
                              data_binding=data_binding, action=action,
                              props=props or {})
        self._components[comp_id] = comp
        if not self._is_child(comp_id):
            self._root_ids.append(comp_id)
        return comp

    def _is_child(self, cid):
        return any(cid in c.children for c in self._components.values())
```

#### 3.2.3 新增 HITL 交互服务

**新文件**: `backend/services/a2ui_hitl_service.py`

```python
"""
A2UI Human-In-The-Loop (HITL) Interaction Service.
管理 Agent 运行时的用户交互：创建交互 → 发送表单 → 等待响应 → 超时处理。
"""
from __future__ import annotations
import asyncio, json, logging, time, uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

class InteractionStatus(str, Enum):
    PENDING = "pending"
    RESPONDED = "responded"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

@dataclass
class PendingInteraction:
    interaction_id: str
    conversation_id: str
    agent_id: str
    user_id: str
    question: str
    payload: dict = field(default_factory=dict)
    status: InteractionStatus = InteractionStatus.PENDING
    response: Optional[dict] = None
    created_at: float = field(default_factory=time.time)
    timeout_at: Optional[float] = None

    def to_dict(self):
        return {"interaction_id": self.interaction_id, "status": self.status.value,
                "response": self.response, "question": self.question,
                "payload": self.payload, "created_at": self.created_at}

class A2UIHITLService:
    """Singleton 服务，管理所有 HITL 交互。"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._interactions = {}
            cls._instance._events = {}
        return cls._instance

    @classmethod
    def get_instance(cls):
        return cls()

    async def create_interaction(self, conversation_id, agent_id, user_id,
                                  question, payload=None, timeout_seconds=None):
        iid = uuid.uuid4().hex
        interaction = PendingInteraction(
            interaction_id=iid, conversation_id=conversation_id,
            agent_id=agent_id, user_id=user_id, question=question,
            payload=payload or {},
            timeout_at=time.time() + timeout_seconds if timeout_seconds else None)
        self._interactions[iid] = interaction
        self._events[iid] = asyncio.Event()
        logger.info("Created interaction %s", iid)
        return interaction

    async def wait_for_response(self, interaction_id, timeout=None):
        interaction = self._interactions.get(interaction_id)
        if not interaction or interaction.status != InteractionStatus.PENDING:
            return interaction.response if interaction else None
        event = self._events.get(interaction_id)
        if not event: return None
        effective = timeout
        if effective is None and interaction.timeout_at:
            effective = max(0, interaction.timeout_at - time.time())
        try:
            if effective is not None:
                await asyncio.wait_for(event.wait(), timeout=effective)
            else:
                await event.wait()
        except asyncio.TimeoutError:
            interaction.status = InteractionStatus.TIMEOUT
            self._cleanup(interaction_id)
            return None
        if interaction.status == InteractionStatus.RESPONDED:
            return interaction.response
        return None

    def submit_response(self, interaction_id, response):
        interaction = self._interactions.get(interaction_id)
        if not interaction or interaction.status != InteractionStatus.PENDING:
            return False
        interaction.status = InteractionStatus.RESPONDED
        interaction.response = response
        event = self._events.get(interaction_id)
        if event: event.set()
        return True

    def cancel_interaction(self, interaction_id):
        interaction = self._interactions.get(interaction_id)
        if not interaction: return False
        if interaction.status == InteractionStatus.PENDING:
            interaction.status = InteractionStatus.CANCELLED
            event = self._events.get(interaction_id)
            if event: event.set()
        self._cleanup(interaction_id)
        return True

    def get_pending(self, conversation_id=None, user_id=None):
        return [i for i in self._interactions.values()
                if i.status == InteractionStatus.PENDING
                and (not conversation_id or i.conversation_id == conversation_id)
                and (not user_id or i.user_id == user_id)]

    def _cleanup(self, iid):
        self._interactions.pop(iid, None)
        self._events.pop(iid, None)


# ── 便捷方法 ────────────────────────────────────────────────────

async def request_user_feedback(agent_run_info, conversation_id, user_id,
                                 agent_id, question, options=None,
                                 allow_custom_input=False,
                                 timeout_seconds=None, observer=None):
    """Agent 运行时请求用户反馈的高级入口。"""
    from nexent.core.utils.observer import ProcessType
    from nexent.core.a2ui.a2ui_builder import A2UIBuilder

    service = A2UIHITLService.get_instance()
    interaction = await service.create_interaction(
        conversation_id=conversation_id, agent_id=agent_id,
        user_id=user_id, question=question,
        payload={"options": options or [], "allow_custom_input": allow_custom_input},
        timeout_seconds=timeout_seconds)

    if observer:
        builder = A2UIBuilder(surface_id=f"hitl_{interaction.interaction_id}")
        smsg = builder.build_create_surface(catalog="hitl", title=question)
        observer.add_message("", ProcessType.A2UI_SURFACE, json.dumps(smsg, ensure_ascii=False))

        qt = builder.add_text(question, "hitl_q", "subtitle")
        if options:
            qr = builder.add_quick_replies(options, "hitl_opts")
        if allow_custom_input:
            ta = builder.add_text_area("补充说明", "请输入...", "hitl_ta", "hitl.custom_input")
        cmsg = builder.build_update_components()
        observer.add_message("", ProcessType.A2UI_COMPONENTS, json.dumps(cmsg, ensure_ascii=False))

    response = await service.wait_for_response(interaction.interaction_id, timeout_seconds)

    if observer:
        observer.add_message("", ProcessType.HITL_FORM_RESPONSE,
            json.dumps({"interaction_id": interaction.interaction_id,
                        "status": interaction.status.value, "response": response},
                       ensure_ascii=False))
    return response
```

#### 3.2.4 新增 API 端点

**新文件**: `backend/apps/a2ui_app.py`

```python
"""
A2UI API 端点：用户操作提交、交互查询与取消。
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.a2ui_hitl_service import A2UIHITLService

logger = logging.getLogger("a2ui_app")
a2ui_router = APIRouter(prefix="/api/a2ui", tags=["A2UI"])

class ActionSubmitRequest(BaseModel):
    interaction_id: str
    action: str = "quick_reply"
    payload: dict | None = None
    user_id: str | None = None

@a2ui_router.post("/action")
async def submit_action(request: ActionSubmitRequest):
    """提交用户操作响应到待处理交互。"""
    service = A2UIHITLService.get_instance()
    interaction = service.get_interaction(request.interaction_id)
    if not interaction:
        raise HTTPException(status_code=404, detail="Interaction not found")
    if interaction.status != "pending":
        raise HTTPException(status_code=400, detail=f"Interaction is {interaction.status}")
    if request.user_id and interaction.user_id != request.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    success = service.submit_response(request.interaction_id,
        {"interaction_id": request.interaction_id, "action": request.action,
         "payload": request.payload or {}})
    if not success:
        raise HTTPException(status_code=500, detail="Failed to submit")
    return {"status": "ok", "interaction_id": request.interaction_id}

@a2ui_router.get("/interactions/{conversation_id}")
async def get_pending_interactions(conversation_id: str, user_id: str | None = None):
    """查询会话的所有待处理交互。"""
    service = A2UIHITLService.get_instance()
    interactions = service.get_pending(conversation_id=conversation_id, user_id=user_id)
    return {"status": "ok", "interactions": [i.to_dict() for i in interactions]}

@a2ui_router.delete("/interactions/{interaction_id}")
async def cancel_interaction(interaction_id: str):
    """取消待处理交互。"""
    service = A2UIHITLService.get_instance()
    if not service.cancel_interaction(interaction_id):
        raise HTTPException(status_code=404, detail="Interaction not found")
    return {"status": "ok"}
```

#### 3.2.5 注册到应用

在主应用入口注册 `a2ui_router`：

```python
from apps.a2ui_app import a2ui_router
app.include_router(a2ui_router)
```

### 3.3 前端修改方案

#### 3.3.1 新增 A2UI 类型定义

**修改文件**: `frontend/types/chat.ts`

```typescript
// ── A2UI Types ─────────────────────────────────────────────────

export interface A2UIComponent {
  id: string;
  component: string;
  children?: string[];
  text?: string;
  variant?: string;
  icon?: string;
  dataBinding?: string;
  action?: { event: { name: string; payload?: Record<string, any> } };
  props?: Record<string, any>;
}

export interface A2UISurface {
  surfaceId: string;
  catalog: string;
  title?: string;
  components: A2UIComponent[];
  dataModel: Record<string, any>;
  rootIds: string[];
}

export interface A2UIActionPayload {
  interaction_id: string;
  action: string;
  payload: Record<string, any>;
}

// ChatMessageType 扩展
export interface ChatMessageType {
  // ... 现有字段
  a2uiSurfaces?: Record<string, A2UISurface>;
}

// StepContent 扩展
export interface StepContent {
  // ... 现有类型
  type:
    | typeof chatConfig.messageTypes.A2UI_SURFACE
    | typeof chatConfig.messageTypes.A2UI_COMPONENTS
    | typeof chatConfig.messageTypes.A2UI_DATA_MODEL
    | typeof chatConfig.messageTypes.A2UI_DELETE_SURFACE
    | typeof chatConfig.messageTypes.HITL_FORM
    | typeof chatConfig.messageTypes.HITL_FORM_RESPONSE;
  a2uiSurfaceId?: string;
}
```

#### 3.3.2 新增 A2UI 渲染引擎

**新文件**: `frontend/app/[locale]/chat/a2ui/A2UIRenderer.tsx`

```tsx
"use client";
import React, { useCallback, useMemo } from "react";
import { Card, Button, Input, Rate, Typography } from "antd";
import type { A2UIComponent, A2UISurface, A2UIActionPayload } from "@/types/chat";

const { Text: AntText } = Typography;
const { TextArea } = Input;

interface Props {
  surface: A2UISurface;
  onAction: (payload: A2UIActionPayload) => void;
  readOnly?: boolean;
}

export function A2UIRenderer({ surface, onAction, readOnly }: Props) {
  const map = useMemo(() => {
    const m = new Map<string, A2UIComponent>();
    surface.components.forEach(c => m.set(c.id, c));
    return m;
  }, [surface.components]);

  const handleAction = useCallback((c: A2UIComponent) => {
    if (readOnly || !c.action) return;
    onAction({ interaction_id: surface.surfaceId,
               action: c.action.event.name, payload: c.action.event.payload || {} });
  }, [onAction, readOnly, surface.surfaceId]);

  const roots = surface.rootIds.map(id => map.get(id))
    .filter((c): c is A2UIComponent => c !== undefined);
  if (!roots.length) return null;

  return (
    <div className="a2ui-surface" data-surface-id={surface.surfaceId}>
      {roots.map(c => (
        <ComponentRenderer key={c.id} comp={c} map={map}
            dataModel={surface.dataModel} onAction={handleAction} readOnly={readOnly || false} />
      ))}
    </div>
  );
}

function ComponentRenderer({ comp, map, dataModel, onAction, readOnly }) {
  const text = comp.dataBinding && dataModel[comp.dataBinding] !== undefined
    ? String(dataModel[comp.dataBinding]) : (comp.text || "");

  const children = (comp.children || [])
    .map(id => map.get(id)).filter(Boolean)
    .map(child => <ComponentRenderer key={child.id} comp={child} map={map}
        dataModel={dataModel} onAction={onAction} readOnly={readOnly} />);

  switch (comp.component) {
    case "Row":
      return <div style={{display:"flex",flexDirection:"row",gap:comp.props?.gap||"8px",flexWrap:"wrap"}}>{children}</div>;
    case "Column":
      return <div style={{display:"flex",flexDirection:"column",gap:comp.props?.gap||"8px"}}>{children}</div>;
    case "Text": {
      const styles = { title:{fontSize:16,fontWeight:600}, subtitle:{fontSize:14,fontWeight:500},
          body:{fontSize:14}, caption:{fontSize:12,color:"#8c8c8c"} };
      return <AntText style={styles[comp.variant||"body"]}>{text}</AntText>;
    }
    case "Button":
      return <Button type={comp.variant==="primary"?"primary":"default"}
          disabled={comp.props?.disabled||readOnly}
          onClick={()=>onAction(comp)} size="small">{comp.text}</Button>;
    case "Card":
      return <Card size="small" style={{marginBottom:8}} styles={{body:{padding:12}}}>{children}</Card>;
    case "TextField":
      return <div>
        {comp.props?.label && <div style={{fontSize:12,color:"#595959",marginBottom:4}}>{comp.props.label}</div>}
        <Input placeholder={comp.props?.placeholder} disabled={readOnly} data-a2ui-binding={comp.dataBinding}/>
      </div>;
    case "TextArea":
      return <div>
        {comp.props?.label && <div style={{fontSize:12,color:"#595959",marginBottom:4}}>{comp.props.label}</div>}
        <TextArea placeholder={comp.props?.placeholder} rows={comp.props?.rows||3}
            disabled={readOnly} data-a2ui-binding={comp.dataBinding}/>
      </div>;
    case "Form":
      return <form onSubmit={e=>{e.preventDefault();if(readOnly)return;
        const fd:Record<string,any>={};const bs=new Set<string>();
        map.forEach(c=>{if(c.dataBinding)bs.add(c.dataBinding)});
        bs.forEach(b=>{const el=document.querySelector(`[data-a2ui-binding="${b}"]`) as HTMLInputElement|null;if(el)fd[b]=el.value});
        onAction({interaction_id:comp.id,action:"form_submit",payload:{...comp.props?.submitPayload,...fd}});
      }}>{children}</form>;
    case "Rating":
      return <Rate count={comp.props?.maxValue||5} disabled={readOnly}
          onChange={v=>onAction({interaction_id:comp.id,action:"rating_change",payload:{value:v}})}/>;
    default:
      return <div style={{padding:4,background:"#f5f5f5",borderRadius:4}}>[{comp.component}]</div>;
  }
}
```

#### 3.3.3 修改消息类型配置

**修改文件**: `frontend/const/chatConfig.ts`

```typescript
messageTypes: {
    // ... 现有类型

    // A2UI message types
    A2UI_SURFACE: "a2ui_surface" as const,
    A2UI_COMPONENTS: "a2ui_components" as const,
    A2UI_DATA_MODEL: "a2ui_data_model" as const,
    A2UI_DELETE_SURFACE: "a2ui_delete_surface" as const,

    // HITL message types
    HITL_FORM: "hitl_form" as const,
    HITL_FORM_RESPONSE: "hitl_form_response" as const,
    HITL_TIMEOUT: "hitl_timeout" as const,
}
```

#### 3.3.4 修改 chatStreamHandler.tsx

在 `handleStreamResponse` 的 `switch(messageType)` 中新增：

```typescript
case chatConfig.messageTypes.A2UI_SURFACE: {
    const sd = JSON.parse(messageContent);
    setMessages(prev => prev.map((m, i) => i === prev.length - 1 && m.role === MESSAGE_ROLES.ASSISTANT
        ? { ...m, a2uiSurfaces: { ...(m.a2uiSurfaces||{}), [sd.surfaceId]: { ...sd, components:[], dataModel:{}, rootIds:[] } } }
        : m));
    break;
}
case chatConfig.messageTypes.A2UI_COMPONENTS: {
    const cd = JSON.parse(messageContent);
    setMessages(prev => prev.map((m, i) => i === prev.length - 1 && m.role === MESSAGE_ROLES.ASSISTANT
        ? { ...m, a2uiSurfaces: { ...(m.a2uiSurfaces||{}), [cd.surfaceId]: { ...(m.a2uiSurfaces?.[cd.surfaceId]||{surfaceId:cd.surfaceId}), ...cd } } }
        : m));
    break;
}
case chatConfig.messageTypes.A2UI_DATA_MODEL: {
    const md = JSON.parse(messageContent);
    setMessages(prev => prev.map((m, i) => {
        if (i !== prev.length - 1 || !m.a2uiSurfaces?.[md.surfaceId]) return m;
        const s = { ...m.a2uiSurfaces[md.surfaceId], dataModel: { ...m.a2uiSurfaces[md.surfaceId].dataModel, ...md.dataModel } };
        return { ...m, a2uiSurfaces: { ...m.a2uiSurfaces, [md.surfaceId]: s } };
    }));
    break;
}
case chatConfig.messageTypes.A2UI_DELETE_SURFACE: {
    const dd = JSON.parse(messageContent);
    setMessages(prev => prev.map((m, i) => {
        if (i !== prev.length - 1 || !m.a2uiSurfaces?.[dd.surfaceId]) return m;
        const ns = { ...m.a2uiSurfaces }; delete ns[dd.surfaceId];
        return { ...m, a2uiSurfaces: ns };
    }));
    break;
}
case chatConfig.messageTypes.HITL_FORM:
case chatConfig.messageTypes.HITL_FORM_RESPONSE:
    break;
```

---

## 4. 人在回路交互机制

### 4.1 交互流程

```
Agent 决定需要用户输入
    │
    ▼
调用 request_user_feedback()
    │
    ├── 1. A2UIHITLService.create_interaction() 创建待处理交互
    ├── 2. A2UIBuilder 构建表单组件
    ├── 3. observer.add_message 发送 A2UI_SURFACE + A2UI_COMPONENTS
    ├── 4. SSE 推送到前端，渲染交互表单
    │
    ▼
前端用户操作
    │
    ▼
POST /api/a2ui/action {interaction_id, action, payload}
    │
    ▼
A2UIHITLService.submit_response() 唤醒 asyncio.Event
    │
    ▼
Agent 收到响应，继续执行
    │
    ▼
发送 HITL_FORM_RESPONSE 消息 → 前端更新状态
```

### 4.2 使用示例

```python
# Agent 工具中使用 HITL
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

### 4.3 超时与降级策略

| 场景 | 处理方式 |
|------|---------|
| 用户在超时时间内响应 | 正常返回用户输入，Agent 继续执行 |
| 超时未响应 | 返回 `None`，Agent 可选择重试或跳过 |
| 用户取消 | 返回 `None`，Agent 正常终止流程 |
| 网络断开后重连 | 前端通过 `GET /api/a2ui/interactions/{id}` 恢复状态 |
| Agent 崩溃重启 | 交互状态可持久化到 Redis（Phase 3） |

---

## 5. 现有功能 vs 修改后对比

### 5.1 功能对比

| 功能 | 现有实现 | 修改后实现 |
|------|---------|-----------|
| 卡片类型 | 简单 JSON 透传 | Row/Column/Card/Form/Button/Rating 等 |
| 布局能力 | 无布局支持 | 灵活的 Row/Column 嵌套布局 |
| 交互能力 | 仅展示无交互 | 按钮、输入框、选择器、评分组件 |
| 数据绑定 | 无 | 组件数据双向绑定，动态更新 |
| 用户反馈 | 无 | HITL 机制，形成 Agent↔User 闭环 |
| 标准协议 | 自定义格式 | A2UI 标准协议，便于扩展 |
| 流式更新 | 不支持 | 支持增量组件更新 |
| 多 Surface | 不支持 | 支持同时管理多个独立 Surface |
| 超时恢复 | 无 | 可配置超时 + 优雅降级 |

### 5.2 代码修改清单

**新建文件**:

| 文件路径 | 说明 |
|---------|------|
| `sdk/nexent/core/a2ui/__init__.py` | A2UI 包入口 |
| `sdk/nexent/core/a2ui/a2ui_builder.py` | A2UI 组件构建器 |
| `backend/services/a2ui_hitl_service.py` | HITL 交互服务 |
| `backend/apps/a2ui_app.py` | A2UI API 端点 |
| `frontend/app/[locale]/chat/a2ui/A2UIRenderer.tsx` | A2UI 渲染引擎 |

**修改文件**:

| 文件路径 | 修改内容 |
|---------|---------|
| `sdk/nexent/core/utils/observer.py` | 新增 ProcessType 枚举值 + Transformer 注册 |
| `frontend/types/chat.ts` | 新增 A2UI 相关类型定义 + ChatMessageType 扩展 |
| `frontend/const/chatConfig.ts` | 新增 A2UI/HITL 消息类型常量 |
| `frontend/app/[locale]/chat/streaming/chatStreamHandler.tsx` | 新增 a2ui_* 消息处理分支 |
| 主应用入口 | 注册 a2ui_router 到 FastAPI 应用 |

---

## 6. 扩展使用方法

### 6.1 在工具中使用 A2UI

```python
from nexent.core.a2ui.a2ui_builder import A2UIBuilder
from nexent.core.utils.observer import ProcessType

class ProductSearchTool(BaseTool):
    def execute(self, query: str):
        builder = A2UIBuilder(surface_id="search_results")
        builder.create_surface(catalog="basic", title="搜索结果")

        for product in products:
            builder.add_card(
                title=product.name,
                body=f"价格: ¥{product.price}",
                actions=[
                    {"text": "加入购物车", "name": "add_to_cart", "payload": {"id": product.id}},
                    {"text": "立即购买", "name": "buy_now", "payload": {"id": product.id}},
                ],
            )

        msg = builder.build_update_components()
        self.observer.add_message("", ProcessType.A2UI_COMPONENTS, json.dumps(msg, ensure_ascii=False))
```

### 6.2 在 Skill 脚本中使用

```python
# skill_script.py
from nexent.core.a2ui.a2ui_builder import A2UIBuilder
from nexent.core.utils.observer import ProcessType

def generate_report_card(observer, report_data):
    builder = A2UIBuilder(surface_id="report")
    builder.create_surface(catalog="reports", title="分析报告")

    # 摘要卡片
    builder.add_card(
        title="核心指标",
        body=f"完成率: {report_data['completion_rate']}%",
    )

    # 操作按钮行
    builder.add_quick_replies(
        options=[
            {"text": "查看详情", "name": "view_detail", "payload": {"report_id": report_data["id"]}},
            {"text": "导出PDF", "name": "export_pdf", "payload": {"format": "pdf"}},
        ],
        component_id="report_actions",
    )

    observer.add_message("", ProcessType.A2UI_COMPONENTS,
        json.dumps(builder.build_update_components(), ensure_ascii=False))
```

### 6.3 支持的组件类型

| 组件类型 | 说明 | 使用场景 |
|---------|------|---------|
| Row | 水平布局容器 | 按钮组、工具栏 |
| Column | 垂直布局容器 | 表单、列表 |
| Card | 卡片容器 | 信息展示、搜索结果 |
| Text | 文本组件 | 标题、正文、说明 |
| Button | 交互按钮 | 操作触发、提交 |
| TextField | 单行输入框 | 简短输入 |
| TextArea | 多行文本域 | 评论、长文本 |
| Form | 表单容器 | 数据收集 |
| Rating | 评分组件 | 用户评价 |

---

## 7. 实施计划

### Phase 1: 基础设施（1-2 周）

| 任务 | 交付物 | 负责层 |
|------|--------|--------|
| 新增 ProcessType | `observer.py` 枚举扩展 | SDK |
| 实现 A2UI Builder | `a2ui_builder.py` | SDK |
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

## 8. 风险与注意事项

### 8.1 兼容性

- **现有 CARD 类型**：保持 100% 向后兼容，不修改现有 CARD 处理逻辑
- **新功能独立**：A2UI 使用独立的 ProcessType 枚举值，与现有类型互不干扰
- **渐进式部署**：可通过功能开关（feature flag）控制 A2UI 功能的启用/禁用

### 8.2 性能

- **组件数量**：单个 Surface 组件数量建议 < 50 个，避免渲染性能问题
- **SSE 频率**：避免过于密集的 A2UI 消息推送，建议节流（100ms 最小间隔）
- **数据量**：大体积数据（如表格）建议使用分页或懒加载
- **内存管理**：Surface 使用完毕后及时调用 `delete_surface` 释放资源

### 8.3 安全性

- **权限验证**：`POST /api/a2ui/action` 需验证用户对会话的访问权限
- **输入校验**：HITL 表单提交数据需在后端进行校验和清洗
- **XSS 防护**：用户输入内容在前端渲染时需转义
- **CSRF 防护**：API 端点需遵守项目现有认证机制

### 8.4 用户体验

- **HITL 超时**：超时后需给用户友好提示，Agent 应优雅降级
- **网络断开**：前端重连后通过 API 恢复待处理交互状态
- **加载状态**：组件渲染过程中显示适当的加载指示
- **移动端适配**：组件布局需响应式设计，适配移动端

### 8.5 技术债务

- **内存存储**：当前 HITL 交互存储在内存中，服务重启会丢失。Phase 3 可引入 Redis
- **组件映射**：Ant Design 组件映射覆盖有限，复杂组件需逐步完善
- **国际化**：A2UI 组件文本需支持 i18n

---

## 9. 总结

本设计方案通过引入 A2UI 标准协议和人在回路（HITL）机制，将 Nexent 平台的 Agent 交互能力从简单的文本/JSON 输出升级为丰富的结构化卡片交互体验。

### 核心价值

| 价值 | 说明 |
|------|------|
| **更好的用户体验** | 卡片、表单、评分等组件让 Agent 输出更直观、更专业 |
| **更强的交互能力** | 支持用户实时反馈，形成 Agent→UI→User 协作闭环 |
| **标准化协议** | 遵循 A2UI 规范，便于与其他框架（如 openJiuwen）集成 |
| **良好的扩展性** | 支持自定义 catalog 和组件扩展 |
| **渐进式实施** | 分三阶段实施，风险可控，每阶段可独立交付 |

### 实施要点

1. **保持向后兼容**：现有 CARD 类型不受影响，A2UI 为独立新功能
2. **关注点分离**：SDK 层负责消息构建，后端服务负责交互管理，前端负责渲染
3. **端到端测试**：每个 Phase 完成后需进行完整的集成测试
4. **性能前置**：在 Phase 2 即关注渲染性能，避免后期大规模重构

### 后续展望

- **Phase 3+**：Redis 持久化、更多组件类型（图表、表格）、拖拽交互
- **生态集成**：与 openJiuwen 等 A2UI 生态项目对接
- **自定义 Catalog**：支持业务方注册自定义组件 catalog