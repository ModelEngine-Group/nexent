# 💡 基本使用

本指南提供使用 Nexent SDK 构建智能体的全面介绍。

## 🚀 安装与环境

完整的全栈与仅 SDK 安装路径已集中到 [环境准备](../developer-guide/environment-setup) 指南。请先完成环境配置，再继续本页的快速开始。

## ⚡ 快速开始

### 💡 基本导入

```python
from nexent.core.utils.observer import MessageObserver, ProcessType
from nexent.core.agents.core_agent import CoreAgent
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.tools import ExaSearchTool, KnowledgeBaseSearchTool
```

## 🤖 创建你的第一个智能体

### 🔧 设置环境

```python
# 创建消息观察者用于流式输出
observer = MessageObserver()

# 创建模型（模型和智能体必须使用同一个观察者）
model = OpenAIModel(
    observer=observer,
    model_id="your-model-id",
    api_key="your-api-key",
    api_base="your-api-base"
)
```

### 🛠️ 添加工具

```python
# 创建搜索工具
search_tool = ExaSearchTool(
    exa_api_key="your-exa-key", 
    observer=observer, 
    max_results=5
)

# 创建知识库工具
kb_tool = KnowledgeBaseSearchTool(
    top_k=5, 
    observer=observer
)
```

### 🤖 构建智能体

```python
# 使用工具和模型创建智能体
agent = CoreAgent(
    observer=observer,
    tools=[search_tool, kb_tool],
    model=model,
    name="my_agent",
    max_steps=5
)
```

### 🚀 运行智能体

```python
# 用你的问题运行智能体
agent.run("你的问题")

```

## 📡 使用 agent_run（推荐的流式运行方式）

当需要在服务端或前端以“事件流”方式消费消息时，使用 `agent_run`。它在后台线程执行智能体，并从 `MessageObserver` 持续产出 JSON 字符串，便于 UI 展示与日志采集。

```python
import json
import asyncio
from threading import Event

from nexent.core.agents.run_agent import agent_run
from nexent.core.agents.agent_model import AgentRunInfo, AgentConfig, ModelConfig
from nexent.core.utils.observer import MessageObserver

async def main():
    observer = MessageObserver(lang="zh")
    stop_event = Event()

    model_config = ModelConfig(
        cite_name="gpt-4",
        api_key="<YOUR_API_KEY>",
        model_name="Qwen/Qwen2.5-32B-Instruct",
        url="https://api.siliconflow.cn/v1",
    )

    agent_config = AgentConfig(
        name="example_agent",
        description="An example agent",
        tools=[],
        max_steps=5,
        model_name="gpt-4",
    )

    agent_run_info = AgentRunInfo(
        query="strrawberry中出现了多少个字母r",
        model_config_list=[model_config],
        observer=observer,
        agent_config=agent_config,
        stop_event=stop_event
    )

    async for message in agent_run(agent_run_info):
        message_data = json.loads(message)
        print(message_data)  # 每条都是 JSON 字符串

asyncio.run(main())
```

### 🛰️ 消息流格式

- `type`：消息类型（对应 `ProcessType`，如 `STEP_COUNT`、`MODEL_OUTPUT_THINKING`、`PARSE`、`EXECUTION_LOGS`、`FINAL_ANSWER`、`ERROR`）
- `content`：文本内容
- `agent_name`（可选）：产出该消息的智能体

### 🧠 传入历史（可选）

```python
from nexent.core.agents.agent_model import AgentHistory

history = [
    AgentHistory(role="user", content="你好"),
    AgentHistory(role="assistant", content="你好，我能帮你做什么？"),
]

agent_run_info = AgentRunInfo(
    # ...
    history=history,
)
```

### 🌐 MCP 工具集成（可选）

```python
agent_run_info = AgentRunInfo(
    # ...
    mcp_host=["http://localhost:3000"],  # 或包含 url/transport 的 dict
)
```

### ⏹️ 优雅中断

```python
stop_event.set()  # 智能体会在当前步完成后停止
```

## 🔧 配置选项

### ⚙️ 智能体配置

```python
agent = CoreAgent(
    observer=observer,
    tools=[search_tool, kb_tool],
    model=model,
    name="my_agent",
    max_steps=10,  # 最大执行步骤
)
```

### 🔧 工具配置

```python
# 使用特定参数配置搜索工具
search_tool = ExaSearchTool(
    exa_api_key="your-exa-key",
    observer=observer,
    max_results=10,  # 搜索结果数量
)
```

## 📚 更多资源

- **[流式运行 agent_run](#使用-agent_run推荐的流式运行方式)**
- **[工具开发指南](./core/tools)**
- **[模型架构指南](./core/models)**
- **[智能体模块](./core/agents)** 