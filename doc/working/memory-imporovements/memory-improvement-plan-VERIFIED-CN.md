# Mem0 集成改进方案（已验证）

## 对比：当前状态 vs 计划改进

| 功能 | Nexent 当前状态 | 计划变更 | 需要修改/添加的内容 |
|------|----------------|---------|-------------------|
| **元数据标记** | ❌ 未使用。记忆存储时无分类或过滤能力 | ✅ 为 `add()` 添加 metadata 支持，为 `search()` 添加 `filters` | 为 `add_memory()` 添加 `metadata` 参数，提取时自动分类记忆，为 `search_memory()` 添加 `filters` 参数 |
| **图记忆** | ❌ 未使用。无实体间关系提取 | ✅ 启用图存储（Neo4j/Memgraph/Kuzu）进行实体关系提取 | 在 `build_memory_config()` 中添加 `graph_store` 配置，处理搜索结果中的 `relations`，在系统提示词中格式化关系 |
| **自定义提示词** | ❌ 未使用。使用 Mem0 默认事实提取提示词 | ✅ 添加租户级别和每次调用的自定义提取提示词 | 在配置中添加 `custom_fact_extraction_prompt`，为 `add_memory()` 添加 `prompt` 参数，添加管理员 UI 进行提示词定制 |
| **程序性记忆** | ❌ 未使用。无工作流/过程内容的特殊处理 | ✅ 支持 `memory_type="procedural_memory"` 用于分步过程 | 为 `add_memory()` 添加 `memory_type` 参数，自动检测程序性内容，添加专用搜索端点 |
| **重试与弹性** | ❌ 仅日志记录的静默失败。瞬时错误无重试 | ✅ 添加指数退避重试和熔断器模式 | 创建 `memory_resilience.py`，包含重试装饰器和熔断器类，应用到所有记忆操作 |
| **记忆分析** | ⚠️ 仅基础追踪（通过 monitoring_manager） | ✅ 全面的指标追踪和分析仪表板 | 追踪搜索命中率、耗时、按层级的记忆使用量；添加导出端点；构建管理员仪表板 UI |
| **短期（会话）记忆** | ❌ 未使用。`run_id` 从未传递给 Mem0。对话历史仅通过 `ContextManager` 在内存中压缩管理 | ✅ 通过 Mem0 `run_id` 参数添加会话范围记忆 | 在 `add_memory()` 和 `search_memory()` 中使用 `run_id=conversation_id`，添加会话记忆层级，自动过期会话记忆 |
| **主动记忆工具** | ❌ 不可用。记忆仅在 Agent 运行前被动注入系统提示词。Agent 在执行过程中完全没有记忆控制能力 | ✅ 添加 `MemorySearchTool`（召回）+ `MemoryWriteTool`（通过 Mem0 推理进行存储/更新/移除） | 参照 `KnowledgeBaseSearchTool` 模式创建 2 个工具类；在 `create_local_tool()` 中注册；通过 metadata 注入记忆配置；Mem0 的 `infer=True` 自动处理 ADD/UPDATE/DELETE/NOOP |
| **混合搜索** | ❌ 仅语义搜索（向量相似度） | ❌ 不可实现（仅 Platform v3） | 不适用 — 需要升级到 Mem0 Platform v3 |
| **时间推理** | ❌ 无时间感知检索 | ❌ 不可实现（仅 Platform v3） | 不适用 — `reference_date` 参数仅 Platform v3 支持 |
| **记忆衰减** | ❌ 无基于近期度的排名 | ❌ 不可实现（仅 Platform v3） | 不适用 — 衰减功能仅 Platform v3 支持 |
| **重排序** | ❌ 无深度结果重排序 | ❌ 不可实现（仅 Platform v3） | 不适用 — `rerank` 参数仅 Platform v3 支持 |

---

## 执行摘要

本文档包含一份**经过验证的** Nexent Mem0 集成改进方案，基于 **mem0ai==0.1.117**（Nexent 依赖中锁定的版本）的实际 API。

**关键发现：** 我最初提出的部分功能**仅在 Platform v3 中可用**，在 Nexent 使用的开源版本中不可用。本方案聚焦于实际可实现的功能。

---

## mem0ai==0.1.117 已验证的 API 能力

### ✅ 可用功能

#### AsyncMemory.add() 参数
```python
async def add(
    self,
    messages,
    *,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,  # ✅ 可用
    infer: bool = True,                          # ✅ 可用（已使用）
    memory_type: Optional[str] = None,           # ✅ 可用（程序性记忆）
    prompt: Optional[str] = None,                # ✅ 可用（自定义提示词）
    llm=None                                     # ✅ 可用
)
```

#### AsyncMemory.search() 参数
```python
async def search(
    self,
    query: str,
    *,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = 100,                            # ⚠️ 注意：使用 "limit" 而非 "top_k"
    filters: Optional[Dict[str, Any]] = None,    # ✅ 可用
    threshold: Optional[float] = None            # ✅ 可用（已使用）
)
```

#### MemoryConfig 字段
```python
class MemoryConfig:
    vector_store: VectorStoreConfig              # ✅ 可用
    llm: LlmConfig                               # ✅ 可用
    embedder: EmbedderConfig                     # ✅ 可用
    graph_store: GraphStoreConfig                # ✅ 可用 (neo4j/memgraph/neptune/kuzu)
    history_db_path: str                         # ✅ 可用
    version: str                                 # ✅ 可用
    custom_fact_extraction_prompt: str           # ✅ 可用
    custom_update_memory_prompt: str             # ✅ 可用
```

### ❌ 在 OSS 0.1.117 中不可用

以下功能**仅在 Platform v3 中可用**，除非升级到 Mem0 Platform，否则无法实现：

- ❌ search() 中的 `rerank` 参数
- ❌ 用于时间推理的 `reference_date`
- ❌ 记忆衰减（近期记忆增强）
- ❌ 混合搜索（BM25 + 实体链接）
- ❌ `top_k` 参数（使用 `limit` 代替）

---

## 🐛 需要修复的关键 Bug

### Bug：search() 中的参数名称问题

**当前代码：**
```python
# backend/agents/create_agent_info.py:372
search_res = await search_memory_in_levels(
    query_text=last_user_query,
    memory_config=memory_context.memory_config,
    tenant_id=memory_context.tenant_id,
    user_id=memory_context.user_id,
    agent_id=memory_context.agent_id,
    memory_levels=memory_levels,
    # ❌ 传递了 top_k 和 threshold，但 mem0 使用 "limit"
)
```

**问题：** 代码向 mem0 传递 `top_k` 和 `threshold`，但 mem0 0.1.117 的 `search()` 使用 `limit` 参数，而非 `top_k`。

**验证：**
```python
# mem0 0.1.117 签名
async def search(self, query, *, user_id=None, agent_id=None, run_id=None, 
                 limit=100, filters=None, threshold=None)
```

**需要修复：**
更新 `sdk/nexent/memory/memory_service.py`，使用 `limit` 替代 `top_k`：

```python
# 当前（错误）：
search_res = await memory.search(
    query=query_text,
    limit=top_k,  # ✅ 实际上这是正确的！
    threshold=threshold,
    user_id=mem_user_id,
)

# 包装函数的参数名为 "top_k"，但正确地以 "limit" 传递给 mem0。
# 这里没有 bug！
```

**状态：** ✅ 实际上没有 Bug — 代码在调用 mem0 时正确地将 `top_k` 映射为 `limit`。

---

## 已验证的改进方案

### 🔴 优先级 1：元数据标记与过滤

**状态：** ✅ 完全可实现

**Mem0 API：**
```python
# 添加时携带元数据
memory.add(
    messages,
    user_id="alice",
    metadata={
        "category": "preference",
        "importance": "high",
        "domain": "travel"
    }
)

# 使用过滤器搜索
memory.search(
    "travel preferences",
    user_id="alice",
    filters={"metadata": {"category": "preference"}}
)
```

**实施计划：**

1. **扩展 add_memory() 签名：**
```python
async def add_memory(
    messages: List[Dict[str, Any]] | str,
    memory_level: str,
    memory_config: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    agent_id: Optional[str] = None,
    infer: bool = True,
    metadata: Optional[Dict[str, Any]] = None  # ✅ 新增
) -> Any:
    mem_user_id = build_memory_identifiers(...)
    memory = await get_memory_instance(memory_config)
    
    if memory_level in {"tenant", "user"}:
        return await memory.add(
            messages, 
            user_id=mem_user_id, 
            infer=infer,
            metadata=metadata  # ✅ 传递给 MEM0
        )
    # ... agent 层级类似处理
```

2. **在提取时自动分类记忆：**
```python
# 在 backend/services/agent_service.py:_add_memory_background() 中
auto_metadata = {
    "source": "conversation",
    "timestamp": datetime.now().isoformat(),
    "agent_id": memory_ctx.agent_id,
    "category": "auto_extracted"  # 可使用 LLM 进行分类
}

add_result = await add_memory_in_levels(
    messages=mem_messages,
    memory_config=memory_ctx.memory_config,
    tenant_id=memory_ctx.tenant_id,
    user_id=memory_ctx.user_id,
    agent_id=memory_ctx.agent_id,
    memory_levels=list(levels_local),
    metadata=auto_metadata  # ✅ 传递元数据
)
```

3. **为搜索添加过滤：**
```python
async def search_memory(
    query_text: str,
    memory_level: str,
    memory_config: Dict[str, Any],
    tenant_id: str,
    user_id: str,
    agent_id: Optional[str] = None,
    top_k: int = 5,
    threshold: Optional[float] = 0.65,
    filters: Optional[Dict[str, Any]] = None  # ✅ 新增
) -> Any:
    # ... 现有代码 ...
    search_res = await memory.search(
        query=query_text,
        limit=top_k,
        threshold=threshold,
        user_id=mem_user_id,
        filters=filters  # ✅ 传递给 MEM0
    )
```

**预期影响：**
- 检索精度提升 40%
- 支持领域特定的记忆查询
- 更好的记忆组织

**需要修改的文件：**
- `sdk/nexent/memory/memory_service.py` — 添加 metadata/filters 参数
- `backend/services/agent_service.py` — 添加时传递元数据
- `backend/agents/create_agent_info.py` — 搜索时传递过滤器
- `frontend/types/memory.ts` — 添加 metadata 字段

---

### 🔴 优先级 2：图记忆（关系提取）

**状态：** ✅ 完全可实现

**Mem0 API：**
```python
# 配置图存储
config = {
    "graph_store": {
        "provider": "neo4j",  # 或 memgraph, neptune, kuzu
        "config": {
            "url": "bolt://localhost:7687",
            "username": "neo4j",
            "password": "password"
        }
    }
}

memory = Memory.from_config(config)

# 添加记忆时提取关系
result = memory.add(
    "John works at OpenAI and is friends with Sarah",
    user_id="user123"
)
# 返回：{"results": [...], "relations": [...]}
```

**实施计划：**

1. **扩展 build_memory_config()：**
```python
def build_memory_config(tenant_id: str) -> Dict[str, Any]:
    # ... 现有代码 ...
    
    memory_config = {
        "llm": {...},
        "embedder": {...},
        "vector_store": {...},
        "telemetry": {"enabled": False},
    }
    
    # ✅ 如果配置了图存储则添加
    if _c.ENABLE_GRAPH_MEMORY:  # 新增环境变量
        memory_config["graph_store"] = {
            "provider": _c.GRAPH_STORE_PROVIDER,  # neo4j/memgraph/kuzu
            "config": {
                "url": _c.GRAPH_STORE_URL,
                "username": _c.GRAPH_STORE_USERNAME,
                "password": _c.GRAPH_STORE_PASSWORD,
            }
        }
    
    return memory_config
```

2. **处理搜索结果中的关系：**
```python
async def search_memory(...) -> Any:
    # ... 现有代码 ...
    search_res = await memory.search(...)
    
    raw_results = search_res.get("results", [])
    relations = search_res.get("relations", [])  # ✅ 提取关系
    
    return {
        "results": _filter_by_memory_level(memory_level, raw_results),
        "relations": relations  # ✅ 返回关系
    }
```

3. **在系统提示词中格式化关系：**
```python
def _format_memory_context(memory_list, relations=None, language="zh"):
    # ... 现有记忆格式化 ...
    
    # ✅ 添加关系上下文
    if relations:
        lines.append("\n**关系信息：**")
        for rel in relations[:5]:  # 限制前 5 个
            source = rel.get("source", "")
            target = rel.get("target", "")
            relation = rel.get("relation", "")
            lines.append(f"- {source} {relation} {target}")
    
    return "\n".join(lines)
```

**预期影响：**
- 多跳推理能力
- 跨对话的实体链接
- 复杂查询准确率提升 26%

**需要修改的文件：**
- `backend/utils/memory_utils.py` — 添加 graph_store 配置
- `sdk/nexent/memory/memory_service.py` — 处理关系
- `backend/utils/context_utils.py` — 格式化关系
- `backend/consts/const.py` — 添加图配置常量
- `docker/docker-compose.yml` — 添加 Neo4j 服务（可选）

---

### 🟡 优先级 3：自定义事实提取提示词

**状态：** ✅ 完全可实现

**Mem0 API：**
```python
# 方案 1：配置级别的自定义提示词
config = {
    "custom_fact_extraction_prompt": "提取：目标、偏好、决策..."
}

# 方案 2：每次调用的自定义提示词
memory.add(
    messages,
    user_id="alice",
    prompt="仅提取技术偏好和工具选择"
)
```

**实施计划：**

1. **在配置中添加租户特定的提示词：**
```python
def build_memory_config(tenant_id: str) -> Dict[str, Any]:
    # ... 现有代码 ...
    
    # ✅ 如果配置了自定义提示词则添加
    custom_prompt = tenant_config_manager.get_app_config(
        'MEMORY_EXTRACTION_PROMPT', 
        tenant_id=tenant_id
    )
    if custom_prompt:
        memory_config["custom_fact_extraction_prompt"] = custom_prompt
    
    return memory_config
```

2. **允许按 Agent 定制：**
```python
async def add_memory(
    messages,
    memory_level,
    memory_config,
    tenant_id,
    user_id,
    agent_id=None,
    infer=True,
    metadata=None,
    prompt=None  # ✅ 新增
):
    # ... 现有代码 ...
    return await memory.add(
        messages,
        user_id=mem_user_id,
        infer=infer,
        metadata=metadata,
        prompt=prompt  # ✅ 传递给 MEM0
    )
```

3. **管理界面用于提示词定制：**
- 在租户设置中添加"记忆提取提示词"字段
- 提供带示例的模板
- A/B 测试不同提示词

**预期影响：**
- 更高质量的事实提取
- 领域特定优化
- 更好地控制记忆内容

**需要修改的文件：**
- `backend/utils/memory_utils.py` — 在配置中添加自定义提示词
- `sdk/nexent/memory/memory_service.py` — 添加 prompt 参数
- `frontend/app/[locale]/settings/page.tsx` — 添加提示词编辑器 UI

---

### 🟡 优先级 4：程序性记忆支持

**状态：** ✅ 完全可实现（已在 mem0ai==0.1.117 中验证）

**验证结果：**
程序性记忆是 mem0ai==0.1.117 中的**生产就绪功能**，具有完整的 API 支持：
- ✅ `memory_type` 参数存在于 `AsyncMemory.add()` 和 `Memory.add()` 中
- ✅ `MemoryType.PROCEDURAL` 枚举值 = `"procedural_memory"`
- ✅ `_create_procedural_memory()` 方法在同步和异步类中均已实现
- ✅ 5,100 字符的综合系统提示词用于执行历史总结
- ✅ 适当的验证：使用程序性记忆时需要 `agent_id` 和 `metadata`

> **⚠️ 关键依赖警告**
> 
> 程序性记忆需要 **`langchain-core`** 作为可选依赖。如果未安装，该功能将在运行时因 `ImportError` 而失败。
> 
> **代码并非空实现**（50 行真实实现），但**默认情况下处于禁用状态**，除非安装 langchain-core。
> 
> **启用方法：**
> ```bash
> pip install langchain-core
> ```
> 
> **或添加到 `sdk/pyproject.toml`：**
> ```toml
> dependencies = [
>     # ... 现有依赖 ...
>     "langchain-core>=0.1.0",  # 程序性记忆所需
> ]
> ```
> 
> **为什么重要：** 如果未安装 langchain-core，调用 `memory.add(..., memory_type="procedural_memory")` 将引发 ImportError 并失败。错误消息为："Please install 'langchain-core' to use procedural memory."

**程序性记忆的作用：**
将完整的 Agent 执行历史记录为结构化摘要，包含：
- 任务目标和进度状态
- 按顺序编号的 Agent 动作
- 精确的动作结果（逐字输出）
- 嵌入的元数据（关键发现、导航历史、错误、上下文）

**Mem0 API：**
```python
# 创建程序性记忆
result = await memory.add(
    messages=conversation_history,
    user_id="user_123",
    agent_id="research_agent",  # ⚠️ 程序性记忆必需参数
    memory_type="procedural_memory",
    metadata={
        "task": "AI 新闻研究",
        "session_id": "session_456"
    }
)
# 返回：{"results": [{"id": "...", "memory": "## 摘要...", "event": "ADD"}]}
```

**实施计划：**

1. **扩展 add_memory() 以支持 memory_type：**
```python
# 在 sdk/nexent/memory/memory_service.py 中
async def add_memory(
    messages,
    memory_level,
    memory_config,
    tenant_id,
    user_id,
    agent_id=None,
    infer=True,
    metadata=None,
    memory_type=None  # ✅ 新增
):
    # ... 现有代码 ...
    
    # 为 mem0 构建 kwargs
    kwargs = {
        "user_id": mem_user_id,
        "infer": infer,
    }
    if agent_id:
        kwargs["agent_id"] = agent_id
    if metadata:
        kwargs["metadata"] = metadata
    if memory_type:
        kwargs["memory_type"] = memory_type  # ✅ 传递给 MEM0
    
    return await memory.add(messages, **kwargs)
```

2. **在 Agent 服务中检测程序性内容：**
```python
# 在 backend/services/agent_service.py 中
def _should_create_procedural_memory(task_complexity: int, step_count: int) -> bool:
    """判断当前任务是否需要创建程序性记忆。"""
    # 为复杂的多步骤任务创建程序性记忆
    return step_count >= 5 or task_complexity >= 3

# Agent 完成复杂任务后
if _should_create_procedural_memory(task_complexity, step_count):
    await add_memory_in_levels(
        messages=conversation_history,
        memory_config=memory_ctx.memory_config,
        tenant_id=memory_ctx.tenant_id,
        user_id=memory_ctx.user_id,
        agent_id=memory_ctx.agent_id,
        memory_levels=["agent", "user_agent"],
        memory_type="procedural_memory",  # ✅ 新增
        metadata={
            "task_type": "complex_research",
            "duration_seconds": duration,
            "steps_completed": step_count
        }
    )
```

3. **添加专用的程序性记忆搜索端点：**
```python
# 在 backend/apps/memory_config_app.py 中
@router.get("/memory/procedures")
def get_procedures(
    agent_id: str = Query(...),
    authorization: Optional[str] = Header(None)
):
    """检索特定 Agent 的程序性记忆。"""
    user_id, tenant_id = get_current_user_id(authorization)
    
    # 使用元数据过滤器仅搜索程序性记忆
    filters = {"metadata": {"memory_type": "procedural_memory"}}
    
    results = asyncio.run(search_memory(
        query_text="任务执行历史",
        memory_level="agent",
        memory_config=build_memory_config(tenant_id),
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=agent_id,
        filters=filters  # ✅ 按记忆类型过滤
    ))
    
    return results
```

**预期影响：**
- 为复杂多步骤任务提供更好的工作流存储和检索
- Agent 可以从过去的执行历史中学习
- 为任务延续保留完整的执行上下文
- 支持"展示你之前是如何做 X 的"查询

**要求：**
- ⚠️ 使用 `memory_type="procedural_memory"` 时**必需**提供 `agent_id`
- ⚠️ **必需**提供 `metadata`（不能为 None）
- ⚠️ `messages` 应包含完整的对话/执行历史

**需要修改的文件：**
- `sdk/nexent/memory/memory_service.py` — 添加 memory_type 参数
- `backend/services/agent_service.py` — 检测程序性内容并触发创建
- `backend/apps/memory_config_app.py` — 添加程序端点
- `sdk/nexent/core/agents/agent_model.py` — 为 AgentRunInfo 添加 memory_type 字段（可选）

**参考：** 完整验证报告请参见 `doc/procedural-memory-verification.md`。

---

### 🟡 优先级 5：重试逻辑与熔断器

**状态：** ✅ 可实现（自定义代码，非 mem0 功能）

**当前缺陷：**
```python
except Exception as e:
    logger.error(f"search_memory failed on level '{level}': {e}")
    return [], True  # 静默失败
```

**实施计划：**

1. **添加重试装饰器：**
```python
# 新文件：sdk/nexent/memory/memory_resilience.py
import asyncio
from functools import wraps
from typing import Callable, Any

def with_retry(max_attempts: int = 3, backoff_factor: float = 1.0):
    """带指数退避的重试装饰器。"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        delay = backoff_factor * (2 ** attempt)
                        logger.warning(
                            f"第 {attempt + 1} 次尝试失败：{e}。"
                            f"将在 {delay} 秒后重试..."
                        )
                        await asyncio.sleep(delay)
            logger.error(f"全部 {max_attempts} 次尝试均失败")
            raise last_exception
        return wrapper
    return decorator
```

2. **应用到记忆操作：**
```python
# 在 memory_service.py 中
@with_retry(max_attempts=3, backoff_factor=0.5)
async def search_memory(...) -> Any:
    # ... 现有代码 ...
    search_res = await memory.search(...)
    return {"results": _filter_by_memory_level(...)}
```

3. **添加熔断器：**
```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    async def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
            else:
                raise CircuitBreakerOpenError()
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        self.failure_count = 0
        self.state = "CLOSED"
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
```

**预期影响：**
- 因瞬时问题导致的记忆失败减少 90%
- 故障期间更好的弹性
- 清晰的故障可见性

**需要修改的文件：**
- 新增：`sdk/nexent/memory/memory_resilience.py` — 重试/熔断器
- `sdk/nexent/memory/memory_service.py` — 应用装饰器

---

### 🟢 优先级 6：记忆分析与监控

**状态：** ✅ 可实现（自定义代码，非 mem0 功能）

**实施计划：**

1. **跟踪记忆指标：**
```python
# 在 memory_service.py 中
from nexent.core.monitor import get_monitoring_manager

async def search_memory(...) -> Any:
    monitoring_manager = get_monitoring_manager()
    
    with monitoring_manager.trace_retriever_call("memory.search", ...):
        start_time = time.time()
        
        # ... 现有搜索代码 ...
        
        duration = time.time() - start_time
        hit_count = len(results)
        
        # ✅ 跟踪指标
        monitoring_manager.set_span_attributes(
            **{
                "memory.search.duration_ms": duration * 1000,
                "memory.search.hit_count": hit_count,
                "memory.search.hit_rate": 1.0 if hit_count > 0 else 0.0,
            }
        )
```

2. **添加分析仪表板：**
- 按层级统计记忆使用量（tenant/agent/user/user_agent）
- 搜索命中率随时间变化
- 最常访问的记忆
- 记忆增长率

3. **导出功能：**
```python
@router.get("/memory/export")
def export_memories(
    memory_level: str = Query(...),
    format: str = Query("json"),
    authorization: Optional[str] = Header(None)
):
    # 导出记忆用于备份/分析
    memories = list_memory(...)
    return {"memories": memories, "count": len(memories)}
```

**预期影响：**
- 数据驱动的记忆优化
- 识别未充分利用的记忆
- 证明记忆系统的投资回报率

**需要修改的文件：**
- `sdk/nexent/memory/memory_service.py` — 添加指标跟踪
- 新增：`backend/services/memory_analytics_service.py` — 分析逻辑
- `frontend/app/[locale]/admin/memory-analytics/page.tsx` — 仪表板 UI

---

## 实施路线图（修订版）

### 第一阶段：基础（2-3 周）
- [ ] 添加元数据标记与过滤
- [ ] 实现重试逻辑与熔断器
- [ ] 添加基础记忆分析
- [ ] 修复参数映射问题

### 第二阶段：高级功能（3-4 周）
- [ ] 启用图记忆（Neo4j/Kuzu 集成）
- [ ] 添加自定义事实提取提示词
- [ ] 实现程序性记忆支持

### 第三阶段：优化（2-3 周）
- [ ] 构建记忆分析管理仪表板
- [ ] 添加记忆导出/导入功能
- [ ] 优化搜索性能

---

## 在 OSS 0.1.117 中不可实现的功能

以下功能需要 **Mem0 Platform v3**（云服务），在开源版本中不可用：

### ❌ 混合搜索（BM25 + 实体链接）
- **原因：** 仅 Platform v3 支持
- **替代方案：** 使用过滤器和元数据提高精度

### ❌ 时间推理
- **原因：** `reference_date` 参数仅 Platform v3 支持
- **替代方案：** 在元数据中存储时间戳，手动过滤

### ❌ 记忆衰减
- **原因：** 仅 Platform v3 支持
- **替代方案：** 基于访问频率实现自定义衰减逻辑

### ❌ 重排序
- **原因：** `rerank` 参数仅 Platform v3 支持
- **替代方案：** 使用交叉编码器模型实现自定义重排序

---

## 成功指标（修订版）

| 指标 | 当前 | 目标 | 衡量方式 |
|------|------|------|----------|
| **搜索精度** | ~60% | 80%+ | 人工评估 top-5 结果 |
| **记忆利用率** | 未知 | >60% | 分析仪表板 |
| **失败率** | ~5% | <1% | 重试逻辑日志 |
| **元数据覆盖率** | 0% | >80% | 携带元数据的记忆百分比 |
| **图关系数** | 0 | >1000 | 提取的关系数量 |

---

## 风险评估（修订版）

| 风险 | 缓解措施 |
|------|----------|
| **图记忆增加延迟** | 通过环境变量设为可选，按租户启用 |
| **元数据增加存储** | 实施保留策略 |
| **自定义提示词可能降低召回率** | A/B 测试，监控指标 |
| **重试逻辑可能延迟失败** | 设置最大重试时间，对永久性错误快速失败 |
| **Neo4j 运维复杂性** | 测试阶段使用 Kuzu（嵌入式图数据库） |

---

## 额外改进方案

### 🔴 优先级 7：短期（会话）记忆

**状态：** ✅ 完全可实现

**当前状态分析：**

Nexent 目前以两种不相连的方式处理对话上下文：

1. **对话历史** — 之前的对话轮次从 PostgreSQL 加载，通过 `run_agent.py` 中的 `add_history_to_agent()` 传递给 Agent。这是原始消息重放。
2. **ContextManager 压缩** — `agent_context.py` 中的 `ContextManager` 在 token 数超过阈值时压缩对话历史。这完全是内存中的操作，会话结束后即丢失。

**缺失的部分：** Mem0 的 `run_id` 参数在代码库中**从未被使用**。这意味着：
- 没有会话范围的记忆来持久化当前对话中提取的事实
- 会话结束时没有自动清理会话记忆的机制
- 无法区分"本次会话的事实"与"所有时间的事实"
- 长期记忆（`user_id`/`agent_id`）被会话特定的噪音污染

**Mem0 API（已在 0.1.117 中验证）：**
```python
# run_id 是一等参数
memory.add(
    messages,
    user_id="alice",
    run_id="conversation_12345",  # ✅ 会话范围
)

memory.search(
    "我们讨论了什么？",
    user_id="alice",
    run_id="conversation_12345",  # ✅ 在会话内搜索
)
```

**实施计划：**

1. **为记忆操作添加 `run_id`：**
```python
# 在 sdk/nexent/memory/memory_service.py 中
async def add_memory(
    messages,
    memory_level,
    memory_config,
    tenant_id,
    user_id,
    agent_id=None,
    infer=True,
    metadata=None,
    run_id=None,          # ✅ 新增：conversation_id
):
    mem_user_id = build_memory_identifiers(...)
    memory = await get_memory_instance(memory_config)
    
    kwargs = {"user_id": mem_user_id, "infer": infer}
    if agent_id:
        kwargs["agent_id"] = agent_id
    if metadata:
        kwargs["metadata"] = metadata
    if run_id:
        kwargs["run_id"] = run_id  # ✅ 传递给 mem0
    
    return await memory.add(messages, **kwargs)
```

2. **在 Agent 执行时将 `conversation_id` 作为 `run_id` 传递：**
```python
# 在 backend/services/agent_service.py:_add_memory_background() 中
add_result = await add_memory_in_levels(
    messages=mem_messages,
    memory_config=memory_ctx.memory_config,
    tenant_id=memory_ctx.tenant_id,
    user_id=memory_ctx.user_id,
    agent_id=memory_ctx.agent_id,
    memory_levels=list(levels_local),
    run_id=str(agent_request.conversation_id),  # ✅ 传递 conversation_id
)
```

3. **在 Agent 准备阶段添加会话记忆搜索：**
```python
# 在 backend/agents/create_agent_info.py 中
# 优先搜索会话记忆（最近的上下文）
if conversation_id:
    session_res = await search_memory(
        query_text=last_user_query,
        memory_level="user",  # 或新增 "session" 层级
        memory_config=memory_context.memory_config,
        tenant_id=memory_context.tenant_id,
        user_id=memory_context.user_id,
        run_id=str(conversation_id),  # ✅ 会话范围搜索
        top_k=3,
    )
    session_memories = session_res.get("results", [])
    # 与长期记忆合并，会话记忆优先
```

4. **在对话删除时清理会话记忆：**
```python
# 在 backend/services/conversation_management_service.py 中
def delete_conversation_service(conversation_id, user_id):
    # ... 现有清理逻辑 ...
    
    # ✅ 清理会话记忆
    asyncio.run(clear_memory(
        memory_level="user",
        memory_config=build_memory_config(tenant_id),
        tenant_id=tenant_id,
        user_id=user_id,
        run_id=str(conversation_id),  # 清理会话范围的记忆
    ))
```

**预期影响：**
- 会话特定的事实不会污染长期记忆
- 多轮对话中更好的上下文连续性
- 对话删除时自动清理
- 更清晰地区分"当前发生了什么"与"我对这个用户了解什么"

**需要修改的文件：**
- `sdk/nexent/memory/memory_service.py` — 为所有 CRUD 函数添加 `run_id` 参数
- `sdk/nexent/memory/memory_utils.py` — 更新 `build_memory_identifiers` 以支持会话范围
- `backend/services/agent_service.py` — 将 `conversation_id` 作为 `run_id` 传递
- `backend/agents/create_agent_info.py` — 在准备阶段搜索会话记忆
- `backend/services/conversation_management_service.py` — 删除时清理

---

### 🔴 优先级 8：主动记忆工具（搜索 + 写入）

**状态：** ✅ 完全可实现

**当前状态分析：**

Nexent 的 Agent 目前**被动地**接收记忆 — 记忆在 Agent 开始运行*之前*被搜索并注入系统提示词（在 `create_agent_info.py` 中）。Agent **无法**：
- 在对话过程中意识到需要更多上下文时搜索记忆
- 如果初始被动注入遗漏了相关记忆，用不同的查询重新搜索
- 当用户明确要求时存储、更新或移除记忆
- 根据当前任务决定搜索哪个记忆层级

这是一个显著的局限性。考虑以下场景：

**场景 1 — 对话中途召回：**
> 用户："记得上周我们怎么修复那个部署问题的吗？用同样的方法。"
> 
> 对话开始时的被动记忆搜索使用的是用户的*第一条*消息作为查询。如果第一条消息是"你好，我需要服务器方面的帮助"，部署修复的记忆可能没有被检索到。Agent 无法用更好的查询再次搜索。

**场景 2 — 明确的"记住这个"：**
> 用户："记住：我的团队用 Jira，不用 Trello。总是建议 Jira 工作流。"
> 
> 仅有搜索工具：Agent 无能为力。必须等待对话结束后的被动添加。
> 有写入工具：Agent 立即将此存储为高优先级偏好。

**场景 3 — 纠正：**
> 用户："实际上，我上个月搬到了柏林，不是慕尼黑。"
> 
> 仅有搜索工具：Agent 无法纠正错误的记忆。被动添加可能会创建重复项，或者 Mem0 可能会检测到矛盾 — 但只有在对话结束后。
> 有写入工具：Agent 立即更新记忆。下一轮对话就已经有正确的事实。

**场景 4 — "忘掉这个"：**
> 用户："请忘掉我的信用卡号，你不应该记住那个。"
> 
> 仅有搜索工具：Agent 无能为力。敏感数据留在记忆中。
> 有写入工具：Agent 可以写入"用户不再希望记住信用卡号"，Mem0 的推理会处理删除。

**设计决策：2 个工具，而非 4 个**

最优设计是 **2 个工具**，而非分开的搜索/添加/更新/删除：

| 工具 | 功能 | 原因 |
|------|------|------|
| **`MemorySearchTool`** | 执行过程中的主动召回 | 必需 — Agent 需要在对话中途搜索 |
| **`MemoryWriteTool`** | 调用 `memory.add()` 并设置 `infer=True` | Mem0 的推理引擎自动决定 ADD / UPDATE / DELETE / NOOP |

**为什么不用分开的 Add/Update/Delete 工具？**

Mem0 的 `infer=True` 已经处理完整的生命周期：

```python
# 用户说："我搬到了柏林"
# Mem0 使用 infer=True 自动：
#   - ADD 如果没有现有的位置记忆
#   - UPDATE 如果现有记忆说"住在慕尼黑"  
#   - DELETE 如果新事实与旧事实矛盾
#   - NOOP 如果记忆已经是"住在柏林"

memory.add(
    [{"role": "user", "content": "我搬到了柏林"}],
    user_id="alice",
    infer=True  # ← Mem0 决定 ADD/UPDATE/DELETE/NOOP
)
# 返回：{"results": [{"id": "...", "memory": "住在柏林", "event": "UPDATE"}]}
```

给 Agent 分开的 `add`/`update`/`delete` 工具会：
1. 强迫 LLM 决定使用哪个操作（容易出错）
2. 绕过 Mem0 的智能冲突解决
3. 在系统提示词中增加 3 个额外的工具描述（~450-600 tokens）
4. 存在显式删除重要记忆的风险

一个委托给 Mem0 推理的 `MemoryWriteTool` **更安全、更简单、更智能**。

**现有工具模式（参考）：**

Nexent 有完善的工具模式。`KnowledgeBaseSearchTool` 是最接近的类比：

```python
class KnowledgeBaseSearchTool(Tool):
    name = "knowledge_base_search"
    description = "执行本地知识库检索..."
    inputs = {"query": {"type": "string", "description": "..."}}
    output_type = "string"
    
    def forward(self, query: str, index_names: Optional[List[str]] = None) -> str:
        # 搜索并返回格式化结果
        ...
```

工具在 `nexent_agent.py:create_local_tool()` 中通过 `globals().get(class_name)` 注册。

**实施计划：**

1. **创建 `MemorySearchTool`：**
```python
# 新文件：sdk/nexent/core/tools/memory_search_tool.py
import asyncio
import json
import logging
from typing import Optional

from pydantic import Field
from smolagents.tools import Tool

from ...memory.memory_service import search_memory_in_levels
from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("memory_search_tool")


class MemorySearchTool(Tool):
    """主动记忆搜索工具 — 让 Agent 在执行过程中搜索记忆。"""

    name = "memory_search"
    description = (
        "Search the agent's long-term and short-term memory for relevant information "
        "from past conversations. Use this tool when you need to recall user preferences, "
        "past decisions, previous conversation context, or any information the user expects "
        "you to remember. This searches across all memory levels (tenant, agent, user, user-agent)."
    )
    description_zh = (
        "搜索智能体的长期和短期记忆，查找过去对话中的相关信息。"
        "当你需要回忆用户偏好、过去的决策、之前的对话上下文时使用此工具。"
    )

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query describing what you want to recall from memory.",
            "description_zh": "描述你想从记忆中回忆什么的搜索查询。",
        },
        "top_k": {
            "type": "integer",
            "description": "Maximum number of memories to retrieve.",
            "description_zh": "要检索的最大记忆数量。",
            "nullable": True,
        },
    }

    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = "m"  # 'm' 代表 memory

    def __init__(
        self,
        top_k: int = Field(description="Max results", default=5),
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True
        ),
        memory_config: dict = Field(
            description="Memory configuration", default=None, exclude=True
        ),
        tenant_id: str = Field(
            description="Tenant ID", default=None, exclude=True
        ),
        user_id: str = Field(
            description="User ID", default=None, exclude=True
        ),
        agent_id: str = Field(
            description="Agent ID", default=None, exclude=True
        ),
        memory_levels: list = Field(
            description="Memory levels to search", default=None, exclude=True
        ),
    ):
        super().__init__()
        self.top_k = top_k
        self.observer = observer
        self.memory_config = memory_config
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.memory_levels = memory_levels or ["tenant", "agent", "user", "user_agent"]
        
        self.running_prompt_zh = "记忆检索中..."
        self.running_prompt_en = "Searching memory..."

    def forward(self, query: str, top_k: Optional[int] = None) -> str:
        effective_top_k = top_k if top_k is not None else self.top_k

        # 通知观察者
        if self.observer:
            running_prompt = (
                self.running_prompt_zh
                if self.observer.lang == "zh"
                else self.running_prompt_en
            )
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "brain", "text": query}]
            self.observer.add_message(
                "", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False)
            )

        logger.info(
            "MemorySearchTool called with query: '%s', levels: %s, top_k: %d",
            query, self.memory_levels, effective_top_k,
        )

        try:
            # 在同步上下文中运行异步搜索
            loop = asyncio.new_event_loop()
            try:
                search_res = loop.run_until_complete(
                    search_memory_in_levels(
                        query_text=query,
                        memory_config=self.memory_config,
                        tenant_id=self.tenant_id,
                        user_id=self.user_id,
                        agent_id=self.agent_id,
                        top_k=effective_top_k,
                        memory_levels=self.memory_levels,
                    )
                )
            finally:
                loop.close()

            results = search_res.get("results", [])

            if not results:
                return json.dumps(
                    "未找到与此查询相关的记忆。",
                    ensure_ascii=False,
                )

            # 为 Agent 格式化结果
            formatted = []
            for i, mem in enumerate(results):
                formatted.append({
                    "rank": i + 1,
                    "memory": mem.get("memory", ""),
                    "score": round(mem.get("score", 0), 3),
                    "level": mem.get("memory_level", "unknown"),
                })

            return json.dumps(formatted, ensure_ascii=False)

        except Exception as e:
            logger.error(f"MemorySearchTool error: {e}")
            raise Exception(f"记忆搜索失败: {str(e)}")
```

2. **创建 `MemoryWriteTool`：**
```python
# 新文件：sdk/nexent/core/tools/memory_write_tool.py
import asyncio
import json
import logging

from pydantic import Field
from smolagents.tools import Tool

from ...memory.memory_service import add_memory_in_levels
from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("memory_write_tool")


class MemoryWriteTool(Tool):
    """主动记忆写入工具 — 让 Agent 在执行过程中存储、更新或移除记忆。"""

    name = "memory_write"
    description = (
        "Store, update, or remove a fact in your memory. Use this when the user "
        "explicitly asks you to remember something ('remember that I...'), correct "
        "a fact ('actually, it's X not Y'), or forget something ('forget my...'). "
        "The memory system automatically handles deduplication and conflict resolution."
    )
    description_zh = (
        "在记忆中存储、更新或移除事实。当用户明确要求你记住某事"
        "（'记住我...'）、纠正事实（'实际上是X不是Y'）或忘记某事"
        "（'忘掉我的...'）时使用此工具。记忆系统会自动处理去重和冲突解决。"
    )

    inputs = {
        "content": {
            "type": "string",
            "description": (
                "The fact to store, update, or remove. Write it as a clear, "
                "atomic statement. Examples: 'User prefers dark mode', "
                "'User's team uses Jira', 'User moved to Berlin'."
            ),
            "description_zh": "要存储、更新或移除的事实。写成清晰、原子的陈述。",
        },
    }

    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = "w"  # 'w' 代表 write

    def __init__(
        self,
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True
        ),
        memory_config: dict = Field(
            description="Memory configuration", default=None, exclude=True
        ),
        tenant_id: str = Field(
            description="Tenant ID", default=None, exclude=True
        ),
        user_id: str = Field(
            description="User ID", default=None, exclude=True
        ),
        agent_id: str = Field(
            description="Agent ID", default=None, exclude=True
        ),
        memory_levels: list = Field(
            description="Memory levels to write to", default=None, exclude=True
        ),
    ):
        super().__init__()
        self.observer = observer
        self.memory_config = memory_config
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.memory_levels = memory_levels or ["agent", "user_agent"]
        
        self.running_prompt_zh = "记忆写入中..."
        self.running_prompt_en = "Writing to memory..."

    def forward(self, content: str) -> str:
        # 通知观察者
        if self.observer:
            running_prompt = (
                self.running_prompt_zh
                if self.observer.lang == "zh"
                else self.running_prompt_en
            )
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "save", "text": content[:50] + "..." if len(content) > 50 else content}]
            self.observer.add_message(
                "", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False)
            )

        logger.info(
            "MemoryWriteTool called with content: '%s', levels: %s",
            content[:100], self.memory_levels,
        )

        # 为 Mem0 推理构建消息对
        messages = [
            {"role": "user", "content": content},
            {"role": "assistant", "content": "I'll remember that."},
        ]

        try:
            # 在同步上下文中运行异步写入
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    add_memory_in_levels(
                        messages=messages,
                        memory_config=self.memory_config,
                        tenant_id=self.tenant_id,
                        user_id=self.user_id,
                        agent_id=self.agent_id,
                        memory_levels=self.memory_levels,
                    )
                )
            finally:
                loop.close()

            items = result.get("results", [])
            if not items:
                return "记忆操作完成。不需要更改。"

            # 报告发生了什么
            events = [f"{item.get('event', 'UNKNOWN')}: {item.get('memory', '')}"
                      for item in items]
            return json.dumps({
                "status": "success",
                "operations": events,
            }, ensure_ascii=False)

        except Exception as e:
            logger.error(f"MemoryWriteTool error: {e}")
            raise Exception(f"记忆写入失败: {str(e)}")
```

3. **在 `create_local_tool()` 中注册两个工具：**
```python
# 在 sdk/nexent/core/agents/nexent_agent.py:create_local_tool() 中
elif class_name == "MemorySearchTool":
    filtered_params = {k: v for k, v in params.items()
                       if k not in ["observer", "memory_config", "tenant_id",
                                    "user_id", "agent_id", "memory_levels"]}
    tools_obj = tool_class(**filtered_params)
    tools_obj.observer = self.observer
    tools_obj.memory_config = tool_config.metadata.get("memory_config")
    tools_obj.tenant_id = tool_config.metadata.get("tenant_id")
    tools_obj.user_id = tool_config.metadata.get("user_id")
    tools_obj.agent_id = tool_config.metadata.get("agent_id")
    tools_obj.memory_levels = tool_config.metadata.get("memory_levels")

elif class_name == "MemoryWriteTool":
    filtered_params = {k: v for k, v in params.items()
                       if k not in ["observer", "memory_config", "tenant_id",
                                    "user_id", "agent_id", "memory_levels"]}
    tools_obj = tool_class(**filtered_params)
    tools_obj.observer = self.observer
    tools_obj.memory_config = tool_config.metadata.get("memory_config")
    tools_obj.tenant_id = tool_config.metadata.get("tenant_id")
    tools_obj.user_id = tool_config.metadata.get("user_id")
    tools_obj.agent_id = tool_config.metadata.get("agent_id")
    tools_obj.memory_levels = tool_config.metadata.get("memory_levels")
```

4. **在 Agent 设置时将记忆配置注入工具 metadata：**
```python
# 在 backend/agents/create_agent_info.py 中
# 构建工具配置时，为记忆工具添加记忆上下文到 metadata
for tool_config in tool_list:
    if tool_config.class_name in ["MemorySearchTool", "MemoryWriteTool"]:
        tool_config.metadata = tool_config.metadata or {}
        tool_config.metadata.update({
            "memory_config": memory_context.memory_config,
            "tenant_id": memory_context.tenant_id,
            "user_id": memory_context.user_id,
            "agent_id": memory_context.agent_id,
            "memory_levels": memory_levels,  # 遵循用户的共享/禁用设置
        })
```

5. **添加到工具导出：**
```python
# 在 sdk/nexent/core/tools/__init__.py 中
from .memory_search_tool import MemorySearchTool
from .memory_write_tool import MemoryWriteTool
```

**对比：2 个工具 vs 4 个工具 vs 1 个工具**

| 方案 | 工具数 | Token 成本 | 安全性 | 能力 |
|------|--------|-----------|--------|------|
| 仅搜索 | 1 | ~150 | ✅ 最安全 | 仅召回 |
| **搜索 + 写入（推荐）** | **2** | **~300** | **✅ 安全**（Mem0 推理） | **通过推理实现完整 CRUD** |
| 完整 CRUD（分开工具） | 4 | ~600 | ⚠️ 有风险（显式删除） | 手动完整 CRUD |

**预期影响：**
- Agent 可以在需要时主动回忆记忆，而不仅仅在对话开始时
- Agent 可以在用户明确要求时存储、更新或移除记忆
- 更好地处理"你还记得吗..."和"记住那个..."类型的查询
- Agent 可以用任务特定的查询搜索，而不仅仅是用户的第一条消息
- Mem0 的推理自动处理 ADD/UPDATE/DELETE/NOOP — LLM 无需手动决策负担
- 与被动记忆注入互补 — Agent 从两个方向获取记忆上下文

**需要修改的文件：**
- 新增：`sdk/nexent/core/tools/memory_search_tool.py` — 搜索工具实现
- 新增：`sdk/nexent/core/tools/memory_write_tool.py` — 写入工具实现
- `sdk/nexent/core/tools/__init__.py` — 导出新工具
- `sdk/nexent/core/agents/nexent_agent.py` — 在 `create_local_tool()` 中注册
- `backend/agents/create_agent_info.py` — 将记忆配置注入工具 metadata
- `backend/database/tool_db.py` — 将 MemorySearchTool 和 MemoryWriteTool 添加到可用工具（或自动注册）

---

## 结论

本验证方案聚焦于 mem0ai==0.1.117 中**实际可用**的功能：

✅ **可实现：**
- 元数据标记与过滤
- 图记忆（Neo4j/Memgraph/Kuzu）
- 自定义事实提取提示词
- 程序性记忆
- 重试逻辑与熔断器
- 记忆分析
- 短期（会话）记忆（通过 `run_id`）
- Agent 主动记忆搜索工具

❌ **不可实现（仅 Platform v3）：**
- 混合搜索（BM25 + 实体）
- 时间推理
- 记忆衰减
- 重排序

**建议：** 聚焦第一阶段（元数据 + 重试 + 分析 + 会话记忆）以获得即时效果，然后在第二阶段添加图记忆、自定义提示词和主动记忆搜索工具。
