# A2UI 卡片功能验证操作指南

## 1. 前置条件

### 1.1 启动服务
确保后端和前端服务已正常启动：

```bash
# 后端服务
cd backend && python config_service.py

# 前端服务
cd frontend && npm run dev
```

### 1.2 检查功能是否已启用
登录系统后，在 Agent 配置页面检查 A2UI 功能是否正常加载。

---

## 2. 快速验证：通过 Prompt 让 Agent 输出卡片

### 2.1 方法一：在 Agent 指令中添加提示

编辑 Agent 的 "System Prompt" 或 "Duty Prompt"，添加以下提示：

```
当你需要向用户展示结构化信息或请求用户反馈时，
请使用 output_card 工具来生成交互式卡片。

卡片类型说明：
- info: 展示信息卡片
- feedback: 反馈表单卡片  
- confirmation: 确认对话框
- form: 自定义表单
- rating: 评分组件
```

### 2.2 方法二：在对话中直接请求

在与 Agent 对话时，直接说：

```
请用卡片的形式展示以下信息：
标题：操作完成
内容：文件已成功上传到知识库
```

Agent 会识别意图并调用 `output_card` 工具生成卡片。

---

## 3. 卡片类型详细配置

### 3.1 信息卡片 (info)

**用途**：展示通知、结果、状态等信息

**配置参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| card_type | string | 固定值: `"info"` |
| title | string | 卡片标题 |
| message | string | 卡片内容 |

**Agent 调用示例**：
```python
output_card(
    card_type="info",
    title="操作成功",
    message="文件已成功上传到知识库，共包含 25 个文档。"
)
```

**效果截图**：
```
┌─────────────────────────────────────┐
│  操作成功                            │  ← 标题
├─────────────────────────────────────┤
│  文件已成功上传到知识库，共包含       │  ← 内容
│  25 个文档。                         │
└─────────────────────────────────────┘
```

---

### 3.2 反馈表单卡片 (feedback)

**用途**：收集用户反馈、意见、评分

**配置参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| card_type | string | 固定值: `"feedback"` |
| title | string | 表单标题 |
| message | string | 反馈问题 |
| options | array | 预设选项列表 |
| allow_custom_input | boolean | 是否允许自定义输入 |

**Agent 调用示例**：
```python
output_card(
    card_type="feedback",
    title="请提供您的反馈",
    message="您对这次对话的满意度如何？",
    options=["非常满意", "满意", "一般", "不满意"],
    allow_custom_input=True
)
```

**效果截图**：
```
┌─────────────────────────────────────┐
│  请提供您的反馈                       │
├─────────────────────────────────────┤
│  您对这次对话的满意度如何？          │
│                                     │
│  [非常满意] [满意] [一般] [不满意]   │  ← 快捷选项按钮
│                                     │
│  补充说明（可选）                    │
│  ┌─────────────────────────────┐    │
│  │                             │    │
│  └─────────────────────────────┘    │
│                                     │
│  [提交反馈]                          │
└─────────────────────────────────────┘
```

---

### 3.3 确认对话框 (confirmation)

**用途**：请求用户确认操作、选择是/否

**配置参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| card_type | string | 固定值: `"confirmation"` |
| title | string | 对话框标题 |
| message | string | 确认内容 |
| options | array | 按钮选项（默认: ["确认", "取消"]） |

**Agent 调用示例**：
```python
output_card(
    card_type="confirmation",
    title="确认操作",
    message="此操作将删除所有已上传的文档，是否继续？",
    options=["确认删除", "取消"]
)
```

**效果截图**：
```
┌─────────────────────────────────────┐
│  确认操作                             │
├─────────────────────────────────────┤
│  此操作将删除所有已上传的文档，       │
│  是否继续？                          │
│                                     │
│  [取消]              [确认删除]       │  ← 操作按钮
└─────────────────────────────────────┘
```

---

### 3.4 自定义表单 (form)

**用途**：收集用户信息，支持多种字段类型

**配置参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| card_type | string | 固定值: `"form"` |
| title | string | 表单标题 |
| fields | array | 字段定义列表 |

**字段定义格式**：
```json
{
    "name": "字段名称",
    "label": "显示标签",
    "type": "textfield|textarea|select|checkbox",
    "placeholder": "占位文本（可选）",
    "options": ["选项1", "选项2"],  // select 类型必填
    "required": true|false
}
```

**Agent 调用示例**：
```python
output_card(
    card_type="form",
    title="用户信息登记",
    fields=[
        {
            "name": "username",
            "label": "用户名",
            "type": "textfield",
            "placeholder": "请输入用户名",
            "required": True
        },
        {
            "name": "email",
            "label": "邮箱地址",
            "type": "textfield",
            "placeholder": "请输入邮箱"
        },
        {
            "name": "department",
            "label": "部门",
            "type": "select",
            "options": ["技术部", "产品部", "运营部", "市场部"]
        },
        {
            "name": "remark",
            "label": "备注",
            "type": "textarea",
            "placeholder": "请输入备注信息"
        }
    ]
)
```

**效果截图**：
```
┌─────────────────────────────────────┐
│  用户信息登记                         │
├─────────────────────────────────────┤
│  用户名 *                            │
│  ┌─────────────────────────────┐    │
│  │ 请输入用户名                │    │
│  └─────────────────────────────┘    │
│                                     │
│  邮箱地址                            │
│  ┌─────────────────────────────┐    │
│  │ 请输入邮箱                  │    │
│  └─────────────────────────────┘    │
│                                     │
│  部门                                │
│  ┌─────────────────────────────┐    │
│  │ 技术部                      ▼ │    │
│  └─────────────────────────────┘    │
│                                     │
│  备注                                │
│  ┌─────────────────────────────┐    │
│  │                             │    │
│  │ 请输入备注信息              │    │
│  └─────────────────────────────┘    │
│                                     │
│  [提交表单]                          │
└─────────────────────────────────────┘
```

---

### 3.5 评分组件 (rating)

**用途**：收集用户评分、星级反馈

**配置参数**：
| 参数 | 类型 | 说明 |
|------|------|------|
| card_type | string | 固定值: `"rating"` |
| title | string | 评分标题 |
| message | string | 评分说明 |

**Agent 调用示例**：
```python
output_card(
    card_type="rating",
    title="服务评分",
    message="请为您本次的使用体验打分"
)
```

**效果截图**：
```
┌─────────────────────────────────────┐
│  服务评分                             │
├─────────────────────────────────────┤
│  请为您本次的使用体验打分            │
│                                     │
│  ⭐ ⭐ ⭐ ⭐ ⭐                       │  ← 点击星星评分
│                                     │
│  [提交评分]                          │
└─────────────────────────────────────┘
```

---

## 4. 端到端验证步骤

### 4.1 创建测试 Agent

1. 登录系统，进入 Agent 管理页面
2. 点击 "创建 Agent"
3. 填写基本信息：
   - 名称：`卡片测试助手`
   - 描述：`用于测试 A2UI 卡片输出功能`
4. 在 "Duty Prompt" 中添加以下内容：

```
你是一个测试助手，专门用于展示各种卡片类型。

当用户询问卡片功能时，你应该使用 output_card 工具来展示相应的卡片：
- 当用户说"展示信息卡片"时，输出一个 info 类型的卡片
- 当用户说"展示反馈表单"时，输出一个 feedback 类型的卡片
- 当用户说"展示确认对话框"时，输出一个 confirmation 类型的卡片
- 当用户说"展示自定义表单"时，输出一个 form 类型的卡片
- 当用户说"展示评分组件"时，输出一个 rating 类型的卡片
```

### 4.2 启用工具

在 Agent 配置页面，确保已启用 `output_card` 工具（如果未显示，请在系统工具中查找）。

如果工具列表中没有 `output_card`，可以通过修改 Agent 注册代码来添加：

```python
# 在 Agent 初始化时添加工具
from nexent.core.tools import OutputCardTool

agent.add_tool(OutputCardTool(observer=observer))
```

### 4.3 开始验证对话

1. 保存 Agent 配置
2. 点击 "开始对话" 进入聊天界面
3. 依次测试以下场景：

#### 测试场景 1：信息卡片
```
用户：请展示一个信息卡片
Agent：（应该输出一个 info 类型的卡片）
```

#### 测试场景 2：反馈表单
```
用户：请展示一个反馈表单
Agent：（应该输出一个 feedback 类型的卡片）
```

#### 测试场景 3：确认对话框
```
用户：请展示一个确认对话框
Agent：（应该输出一个 confirmation 类型的卡片）
```

#### 测试场景 4：自定义表单
```
用户：请展示一个包含用户名、邮箱和部门选择的表单
Agent：（应该输出一个 form 类型的卡片，包含对应的字段）
```

#### 测试场景 5：评分组件
```
用户：请展示一个评分组件
Agent：（应该输出一个 rating 类型的卡片）
```

### 4.4 验证交互功能

#### 卡片提交
1. 在反馈表单卡片中，点击快捷选项按钮
2. 填写补充说明
3. 点击 "提交反馈" 按钮
4. 验证：Agent 应该收到反馈并回复相关内容

#### 表单提交
1. 在自定义表单卡片中，填写所有字段
2. 点击 "提交表单" 按钮
3. 验证：表单数据应该被发送回 Agent 处理

---

## 5. 故障排查

### 5.1 卡片不显示

**检查项**：
- [ ] 后端 `a2ui_router` 是否已注册（查看 config_app.py）
- [ ] 前端 `A2UIChatMessage` 组件是否已导入
- [ ] SSE 消息是否正确发送

**调试方法**：
```bash
# 检查后端路由
curl http://localhost:8000/openapi.json | grep a2ui

# 检查浏览器控制台
# 查看是否有 A2UI 相关的日志
```

### 5.2 工具不可用

**检查项**：
- [ ] `OutputCardTool` 是否已在 `__init__.py` 中导出
- [ ] Agent 初始化时是否注册了该工具

**解决方法**：
```python
# 手动添加工具
from nexent.core.tools import OutputCardTool

tool = OutputCardTool(observer=agent.observer)
agent.tools.append(tool)
```

### 5.3 交互无响应

**检查项**：
- [ ] 前端 action 提交是否成功（检查 Network 面板）
- [ ] 后端 HITL 服务是否正常运行
- [ ] 交互 ID 是否正确传递

**调试方法**：
```bash
# 查看后端日志
tail -f backend/logs/app.log | grep a2ui

# 测试 API
curl -X POST http://localhost:8000/api/a2ui/action \
  -H "Content-Type: application/json" \
  -d '{"interaction_id": "test", "action": "submit", "payload": {}}'
```

---

## 6. 高级用法

### 6.1 在自定义工具中使用 A2UI

```python
from nexent.core.a2ui.a2ui_builder import A2UIBuilder
from nexent.core.utils.observer import ProcessType
import json

class MyCustomTool(Tool):
    def forward(self, query: str):
        # ... 业务逻辑 ...
        
        # 直接发送 A2UI 消息
        builder = A2UIBuilder(surface_id="result")
        builder.create_surface("basic")
        builder.add_card(title="查询结果", body=f"找到 {len(results)} 条记录")
        
        msg = builder.build_update_components()
        self.observer.add_message(
            "", 
            ProcessType.A2UI_COMPONENTS, 
            json.dumps(msg)
        )
```

### 6.2 组合多种卡片

```python
# 先展示信息卡片
output_card(card_type="info", title="任务完成", message="已处理 100 条数据")

# 然后请求反馈
output_card(
    card_type="feedback",
    title="请评价本次任务",
    message="您对处理结果满意吗？",
    options=["满意", "不满意"]
)
```

---

## 7. 总结

| 验证项 | 状态 | 预期结果 |
|--------|------|---------|
| 信息卡片显示 | ☐ | 显示标题和内容 |
| 反馈表单显示 | ☐ | 显示选项按钮和输入框 |
| 确认对话框显示 | ☐ | 显示确认和取消按钮 |
| 自定义表单显示 | ☐ | 显示所有字段 |
| 评分组件显示 | ☐ | 显示星星评分 |
| 卡片交互提交 | ☐ | 提交后 Agent 收到反馈 |
| 表单数据提交 | ☐ | 提交后 Agent 收到表单数据 |

**恭喜！** 您已成功验证 A2UI 卡片功能。
