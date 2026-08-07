# A2UI 集成设计方案（增强版）_test

> **版本**: v3.0 | **日期**: 2026-08-06 | **状态**: 实施中

---

## 目录

1. 需求概述
2. A2UI 协议原理
3. 后端实现详解
4. 前端实现详解
5. 卡片类型与使用指导
6. 人在回路交互机制
7. 数据流全景
8. API 端点设计
9. 实施计划
10. 风险与注意事项

---

## 1. 需求概述

### 1.1 需求背景

Nexent 平台当前已具备基础的 Agent 卡片输出能力（通过 ProcessType.CARD 类型将 JSON 内容透传到前端渲染），但存在核心痛点：

| 痛点 | 说明 |
|------|------|
| 卡片表现力不足 | 仅支持简单 JSON 透传，无法表达复杂布局结构 |
| 无交互闭环 | 卡片仅用于展示，无法向 Agent 反馈信息 |
| 组件不统一 | 缺乏标准化组件库，渲染方式不一致 |
| 无增量更新 | 组件无法动态更新，每次变更需全量重绘 |

通过引入 A2UI（Agent-to-UI）标准协议，Agent 可在运行时生成结构化 UI 组件树，结合"人在回路"（HITL）机制实现双向交互。

### 1.2 需求目标

| 编号 | 目标 | 描述 |
|------|------|------|
| G1 | Agent 输出卡片化 | 将结构化输出渲染为精美卡片组件 |
| G2 | 交互表单生成 | 动态生成表单、选项、输入框等交互组件 |
| G3 | 用户反馈闭环 | 形成 Agent→UI→User→Agent 闭环 |
| G4 | A2UI 标准协议 | 遵循 A2UI 规范，支持 Surface 管理和数据绑定 |
| G5 | 向后兼容 | 保持现有 CARD 类型完整兼容 |

---

## 2. A2UI 协议原理

### 2.1 核心概念

A2UI（Agent-to-UI）是一套让 AI Agent 在运行时生成结构化 UI 的协议。**Agent 不直接生成 UI 代码，而是输出符合 A2UI 规范的组件树描述，由前端的 A2UI Renderer 引擎解析并渲染**。

#### 2.1.1 核心实体

| 实体 | 说明 | 类比 |
|------|------|------|
| **Surface** | 独立的 UI 渲染平面（容器） | 浏览器窗口 / 对话框 |
| **Component** | 组件树中的一个节点 | DOM 元素 |
| **DataModel** | 与 Surface 绑定的数据模型 | React State |
| **Action** | 组件上的交互动作 | Event Handler |
| **Catalog** | Surface 的业务分类 | CSS Class |

#### 2.1.2 生命周期

```
CREATE_SURFACE → ADD_COMPONENTS → UPDATE_DATA_MODEL → DELETE_SURFACE
```

#### 2.1.3 四种 SSE 消息类型

| SSE type | 说明 | content 结构 |
|----------|------|-------------|
| a2ui_surface | 创建 Surface | {surfaceId, catalog, title, components, dataModel, rootIds} |
| a2ui_components | 更新组件树 | {surfaceId, components, rootIds} |
| a2ui_data_model | 更新数据模型 | {surfaceId, dataModel} |
| a2ui_delete_surface | 删除 Surface | {surfaceId} |

#### 2.1.4 SSE 消息示例

```json
{
  "type": "a2ui_surface",
  "content": {
    "surfaceId": "s_001",
    "catalog": "basic",
    "title": "搜索结果",
    "components": [],
    "dataModel": {},
    "rootIds": []
  },
  "agent_id": "agent_xxx",
  "agent_name": "搜索Agent",
  "depth": 0,
  "invocation_id": null
}
```

### 2.2 组件树结构

#### 2.2.1 组件类型体系

```
布局组件: Row (水平布局), Column (垂直布局), Card (卡片容器)
内容组件: Text (文本), Button (按钮)
表单组件: TextField (单行输入), TextArea (多行文本), Form (表单容器)
交互组件: Rating (评分), QuickReplies (快捷回复按钮组)
```

#### 2.2.2 组件 JSON 结构

```json
{
  "id": "card_abc123",
  "component": "Card",
  "children": ["text_title", "text_body", "row_actions"],
  "text": null,
  "variant": null,
  "dataBinding": null,
  "action": null,
  "props": {}
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✅ | 组件唯一标识，同一 Surface 内唯一 |
| component | string | ✅ | 组件类型名称 |
| children | string[] | ❌ | 子组件 ID 列表，按顺序排列 |
| text | string | ❌ | 文本内容 |
| variant | string | ❌ | 变体样式（primary/secondary/body/subtitle/caption） |
| dataBinding | string | ❌ | 数据绑定路径 |
| action | object | ❌ | 交互动作 {event: {name, payload}} |
| props | object | ❌ | 扩展属性（label, placeholder, gap 等） |

#### 2.2.3 嵌套示例

一张信息卡片的完整组件树：

```
Card (card_abc123)
├── Text (text_title) → variant: "subtitle", text: "操作成功"
├── Text (text_body)  → variant: "body", text: "订单已处理..."
└── Row (row_actions)
    ├── Button (btn_confirm) → text: "知道了", variant: "primary"
    └── Button (btn_detail)  → text: "查看详情", variant: "secondary"
```

### 2.3 数据绑定机制

组件通过 `dataBinding` 字段与 `dataModel` 双向绑定。当 dataModel 中的数据更新时，前端会自动重新渲染绑定了该路径的组件。

```json
// 组件定义
{"id": "tf_name", "component": "TextField", "dataBinding": "form.name"}

// DataModel
{"form": {"name": "张三"}}
```

### 2.4 交互动作机制

Action 结构：
```json
{"action": {"event": {"name": "confirm_delete", "payload": {"id": 123}}}}
```

交互流程：用户点击 → 提取 action.event → POST /api/a2ui/action → 后端唤醒 Agent

---

## 3. 后端实现详解

### 3.1 架构总览

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
│  │  A2UIRenderer.tsx → Ant Design Components                   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 ProcessType 扩展

**修改文件**: `sdk/nexent/core/utils/observer.py`

在 `ProcessType` 枚举中新增：

```python
class ProcessType(Enum):
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

在 `_init_message_transformers()` 中注册新类型：

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

### 3.3 A2UI Builder 实现

**文件**: `sdk/nexent/core/a2ui/a2ui_builder.py`

#### 3.3.1 A2UIComponent 数据类

```python
@dataclass
class A2UIComponent:
    """A2UI 组件节点。"""
    id: str
    component: str
    children: list[str] = field(default_factory=list)
    text: Optional[str] = None
    variant: Optional[str] = None
    icon: Optional[str] = None
    data_binding: Optional[str] = None
    action: Optional[dict] = None
    props: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        result: dict = {"id": self.id, "component": self.component}
        if self.children: result["children"] = self.children
        if self.text is not None: result["text"] = self.text
        if self.variant is not None: result["variant"] = self.variant
        if self.icon is not None: result["icon"] = self.icon
        if self.data_binding is not None: result["dataBinding"] = self.data_binding
        if self.action is not None: result["action"] = self.action
        if self.props: result["props"] = self.props
        return result
```

#### 3.3.2 A2UIBuilder 核心方法

```python
class A2UIBuilder:
    def __init__(self, surface_id=None):
        self._sid = surface_id or f"surface_{uuid.uuid4().hex[:8]}"
        self._components: dict[str, A2UIComponent] = {}
        self._root_ids: list[str] = []
        self._data_model: dict[str, Any] = {}
        self._created: bool = False

    def create_surface(self, catalog="basic", title=None):
        """创建 Surface。"""
        self._created = True
        return {"surfaceId": self._sid, "catalog": catalog, "title": title,
                "components": [], "dataModel": {}, "rootIds": []}

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
        """卡片容器，自动构建标题、正文和操作按钮行。"""
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
        """快捷回复按钮组。"""
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

    def build_update_components(self):
        if not self._created: self.create_surface()
        return {"surfaceId": self._sid,
                "components": [c.to_dict() for c in self._components.values()],
                "rootIds": self._root_ids, "dataModel": self._data_model}

    def build_delete_surface(self):
        return {"surfaceId": self._sid}

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

### 3.4 OutputCardTool 工具实现

**文件**: `sdk/nexent/core/tools/a2ui_card_tool.py`

`OutputCardTool` 是 A2UI 卡片输出的核心工具，Agent 通过调用此工具生成各类卡片：

```python
class OutputCardTool(Tool):
    name = "output_card"
    description = "Output an interactive A2UI card or form to the user."
    inputs = {
        "card_type": {"type": "string", "description": "Type: info, feedback, confirmation, form, rating"},
        "title": {"type": "string", "description": "Card title text"},
        "message": {"type": "string", "description": "Card body message"},
        "options": {"type": "array", "description": "Option strings for feedback/confirmation"},
        "fields": {"type": "array", "description": "Form field definitions"},
        "allow_custom_input": {"type": "boolean", "description": "Allow custom text input"},
    }
    output_type = "object"
```

#### 3.4.1 工具注册流程

1. **配置注入** (`backend/agents/create_agent_info.py`)：在 `_get_skill_script_tools` 中添加 `OutputCardTool` 的 `ToolConfig`
2. **实例化** (`sdk/nexent/core/agents/nexent_agent.py`)：在 `create_builtin_tool` 方法中添加 `OutputCardTool` 的创建逻辑
3. **工具列表**：`output_card` 出现在 Agent 可用工具列表中

#### 3.4.2 卡片类型映射

| card_type | 生成的组件结构 | 使用场景 |
|-----------|--------------|---------|
| info | Card + Text + Button | 通知、状态展示 |
| feedback | Card + Text + QuickReplies + TextArea | 用户反馈收集 |
| confirmation | Card + Text + Button×2 | 操作确认 |
| form | Card + Form + TextField/TextArea | 数据录入 |
| rating | Card + Rating + TextArea | 评分评价 |

### 3.5 HITL 交互服务

**文件**: `backend/services/a2ui_hitl_service.py`

```python
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

class A2UIHITLService:
    """单例服务，管理所有 HITL 交互。"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._interactions = {}
            cls._instance._events = {}
        return cls._instance

    async def create_interaction(self, conversation_id, agent_id, user_id,
                                  question, payload=None, timeout_seconds=None):
        """创建待处理交互。"""

    async def wait_for_response(self, interaction_id, timeout=None):
        """等待用户响应，超时返回 None。"""

    def submit_response(self, interaction_id, response):
        """前端提交用户响应，唤醒等待中的 Agent。"""

    def cancel_interaction(self, interaction_id):
        """取消交互。"""

    def get_pending(self, conversation_id=None, user_id=None):
        """查询待处理交互列表。"""
```

#### 便捷入口

```python
async def request_user_feedback(agent_run_info, conversation_id, user_id,
                                 agent_id, question, options=None,
                                 allow_custom_input=False, timeout_seconds=None,
                                 observer=None):
    """一步完成：创建交互 + 构建卡片 + 等待响应。"""
```

### 3.6 API 端点

**文件**: `backend/apps/a2ui_app.py`

```python
a2ui_router = APIRouter(prefix="/api/a2ui", tags=["A2UI"])

@a2ui_router.post("/action")
async def submit_action(request: ActionSubmitRequest):
    """提交用户操作响应。"""

@a2ui_router.get("/interactions/{conversation_id}")
async def get_pending_interactions(conversation_id: str, user_id: str | None = None):
    """查询会话的待处理交互（用于断线恢复）。"""

@a2ui_router.delete("/interactions/{interaction_id}")
async def cancel_interaction(interaction_id: str):
    """取消待处理交互。"""
```

注册到 `runtime_service.py`：
```python
from apps.a2ui_app import a2ui_router
app.include_router(a2ui_router)
```

---

## 4. 前端实现详解

### 4.1 类型定义扩展

**文件**: `frontend/types/chat.ts`

```typescript
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
```

### 4.2 A2UI Renderer 引擎

**文件**: `frontend/app/[locale]/chat/a2ui/A2UIRenderer.tsx`

#### 4.2.1 渲染架构

```tsx
export function A2UIRenderer({ surface, onAction, readOnly }: Props) {
  // 1. 构建组件 ID → 组件映射
  const map = useMemo(() => {
    const m = new Map<string, A2UIComponent>();
    surface.components.forEach(c => m.set(c.id, c));
    return m;
  }, [surface.components]);

  // 2. 提取根组件
  const roots = surface.rootIds
    .map(id => map.get(id))
    .filter((c): c is A2UIComponent => c !== undefined);

  // 3. 递归渲染组件树
  return (
    <div className="a2ui-surface" data-surface-id={surface.surfaceId}>
      {roots.map(c => (
        <ComponentRenderer key={c.id} comp={c} map={map}
            dataModel={surface.dataModel} onAction={handleAction}
            readOnly={readOnly || false} />
      ))}
    </div>
  );
}
```

#### 4.2.2 组件渲染器（核心 switch）

```tsx
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
      const styles = {title:{fontSize:16,fontWeight:600},subtitle:{fontSize:14,fontWeight:500},body:{fontSize:14},caption:{fontSize:12,color:"#8c8c8c"}};
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
        <TextArea placeholder={comp.props?.placeholder} rows={comp.props?.rows||3} disabled={readOnly} data-a2ui-binding={comp.dataBinding}/>
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

### 4.3 消息流处理

#### 4.3.1 消息类型扩展

**文件**: `frontend/const/chatConfig.ts`

```typescript
messageTypes: {
    // A2UI
    A2UI_SURFACE: "a2ui_surface" as const,
    A2UI_COMPONENTS: "a2ui_components" as const,
    A2UI_DATA_MODEL: "a2ui_data_model" as const,
    A2UI_DELETE_SURFACE: "a2ui_delete_surface" as const,
    // HITL
    HITL_FORM: "hitl_form" as const,
    HITL_FORM_RESPONSE: "hitl_form_response" as const,
    HITL_TIMEOUT: "hitl_timeout" as const,
}
```

#### 4.3.2 SSE 消息处理

在 `chatStreamHandler.tsx` 的 `switch(messageType)` 中新增：

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
```

#### 4.3.3 卡片渲染集成

在消息渲染组件中检测并渲染 A2UI 卡片：

```tsx
{message.a2uiSurfaces && Object.entries(message.a2uiSurfaces).map(([sid, surface]) => (
  <A2UIRenderer
    key={sid}
    surface={surface}
    onAction={async (payload) => {
      const res = await fetch("/api/a2ui/action", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("Action failed");
    }}
    readOnly={message.role !== MESSAGE_ROLES.ASSISTANT}
  />
))}

---

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

