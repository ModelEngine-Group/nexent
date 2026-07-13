# 伪代码规范与示例参考

本文档详细说明 SPEC-Coding 中伪代码的编写规范和示例。如需查阅具体模板，请阅读对应的小节。

## 目录

- [1. 伪代码必须包含的要素](#1-伪代码必须包含的要素)
- [2. 完整类伪代码示例](#2-完整类伪代码示例)
- [3. 数据流伪代码示例](#3-数据流伪代码示例)
- [4. 状态机伪代码示例](#4-状态机伪代码示例)
- [5. 选用指南](#5-选用指南)

---

## 1. 伪代码必须包含的要素

```pseudocode
# 必须包含：
# 1. 输入/输出：明确参数类型和返回值类型
# 2. 步骤编号：使用序号标注执行顺序
# 3. 条件分支：if/else/elif 必须完整写出
# 4. 循环逻辑：for/while 必须标注边界条件
# 5. 异常处理：try/except 必须标注可能的异常类型
# 6. 关键数据流：标注数据从输入到输出的变换过程
```

| 要素 | 作用 | 示例 |
|------|------|------|
| 输入/输出 | 明确函数契约 | `输入: task - Task 对象`<br>`输出: Result - 包含 status, data, error 属性` |
| 步骤编号 | 标注执行顺序 | `# Step 1: 输入校验` + `1.1. if ...` |
| 条件分支 | 覆盖所有逻辑路径 | `if/else/elif + endif` 完整闭合 |
| 循环边界 | 避免无限循环 | `for each X in items` + `endfor` |
| 异常处理 | 标注异常类型 | `raise InvalidTaskError(...)` |
| 关键数据流 | 数据变换过程 | `query_vec = normalize(query_embedding)` |

---

## 2. 完整类伪代码示例

适用于：主协调器类、复杂服务类、含多个方法协作的模块。

```pseudocode
class AgentProcessor:
    """代理处理器 - 负责执行代理任务的主协调器"""

    # 属性定义
    config: AgentConfig      # 配置对象，包含 agent_id, timeout, retry_policy 属性
    cache: Dict[str, Result] # 内存缓存，key 为 memory_id，value 为执行结果
    memory_service: MemoryService  # 内存服务依赖，用于获取上下文

    def __init__(self, config: AgentConfig, memory_service: MemoryService):
        """
        初始化处理器
        输入: config - AgentConfig 配置对象
        输入: memory_service - MemoryService 内存服务实例
        """
        self.config = config
        self.memory_service = memory_service
        self.cache = {}

    async def process(self, task: Task) -> Result:
        """
        主处理方法 - 协调任务执行流程
        输入: task - Task 对象，包含 task_id, memory_id, payload 属性
        输出: Result - 包含 status, data, error 属性
        异常: InvalidTaskError - 任务校验失败时抛出
        """
        # Step 1: 输入校验
        1.1. if not self._validate_task(task):
                 raise InvalidTaskError(f"Task {task.task_id} validation failed")
             endif

        # Step 2: 检查缓存（避免重复执行）
        2.1. if task.memory_id in self.cache:
                 return self.cache[task.memory_id]  # 命中缓存，直接返回
             endif

        # Step 3: 准备上下文（从 memory_service 获取）
        3.1. context = await self.memory_service.get_context(task.memory_id)
        3.2. if context is None:
                 context = self._create_empty_context()
             endif

        # Step 4: 执行核心逻辑
        4.1. result = await self._execute_core(task, context)
        4.2. if result.status == "error":
                 result = await self._handle_error(result.error)
             endif

        # Step 5: 更新缓存
        5.1. self.cache[task.memory_id] = result

        # Step 6: 返回结果
        return result

    def _validate_task(self, task: Task) -> bool:
        """
        校验任务有效性
        输入: task - Task 对象
        输出: bool - 校验是否通过
        """
        1. if task is None: return False
        2. if not hasattr(task, 'task_id'): return False
        3. if not hasattr(task, 'memory_id'): return False
        4. if task.task_id == "": return False
        5. return True

    async def _execute_core(self, task: Task, context: Context) -> Result:
        """
        执行核心业务逻辑
        输入: task - Task 对象
        输入: context - Context 对象，包含 memories, metadata 属性
        输出: Result - 业务执行结果
        """
        1. agent = self._load_agent(task.agent_id)
        2. prompt = self._build_prompt(task.payload, context)
        3. response = await agent.run(prompt)
        4. return Result(status="success", data=response)

    def _handle_error(self, error: Error) -> Result:
        """
        错误处理逻辑
        输入: error - Error 对象
        输出: Result - 错误处理结果
        """
        1. if error.type == "timeout":
               return Result(status="timeout", data=None, error=str(error))
        2. elif error.type == "rate_limit":
               return Result(status="retry_later", data=None, error=str(error))
        3. else:
               return Result(status="error", data=None, error=str(error))
```

**使用场景**：
- 类需要多个方法协作
- 包含状态管理（缓存、依赖注入）
- 业务流程较长（≥4 个步骤）

---

## 3. 数据流伪代码示例

适用于：向量检索、数据变换、ETL 流程、管道处理。

```pseudocode
# 数据流伪代码示例：内存向量检索流程

INPUT:
  - query_embedding: List[float]  # 查询向量，维度 1536
  - top_k: int = 5                 # 返回前 k 个结果
  - filters: Dict[str, Any]         # 元数据过滤条件

OUTPUT:
  - results: List[MemoryItem]     # 检索结果列表

PROCESS:
  1. 构建查询向量
     1.1. query_vec = normalize(query_embedding)  # L2 归一化
     1.2. assert len(query_vec) == 1536, "向量维度必须为 1536"

  2. 构建过滤条件
     2.1. if filters is not None:
            filter_expr = build_filter_expression(filters)
          else:
            filter_expr = None
          endif

  3. 执行向量检索
     3.1. candidates = vector_db.search(
              vector=query_vec,
              top_k=top_k * 2,  # 多取一些，用于后续过滤
              filter=filter_expr
          )

  4. 后处理与排序
     4.1. for each candidate in candidates:
            4.1.1. score = cosine_similarity(query_vec, candidate.vector)
            4.1.2. if score >= THRESHOLD:
                      results.append(candidate)
                  endif
          endfor

  5. 返回最终结果
     5.1. return results[:top_k]
```

**使用场景**：
- 数据变换流程清晰，输入输出明确
- 无需维护内部状态
- 处理步骤是无状态的转换

---

## 4. 状态机伪代码示例

适用于：任务生命周期、订单状态、审批流、有明确状态转换的流程。

```pseudocode
# 状态机伪代码示例：任务生命周期管理

STATES:
  - PENDING: 待处理
  - RUNNING: 执行中
  - COMPLETED: 已完成
  - FAILED: 失败
  - CANCELLED: 已取消

INITIAL_STATE: PENDING

TRANSITIONS:
  PENDING -> RUNNING:
    触发条件: worker 接收到任务
    动作:
      1. update_status(RUNNING)
      2. record_start_time()
      3. acquire_resource()

  RUNNING -> COMPLETED:
    触发条件: 任务正常执行完成
    动作:
      1. update_status(COMPLETED)
      2. record_end_time()
      3. release_resource()
      4. notify_callback()

  RUNNING -> FAILED:
    触发条件: 执行过程中发生异常
    动作:
      1. update_status(FAILED)
      2. record_error(error_info)
      3. release_resource()
      4. schedule_retry() if retry_count < MAX_RETRIES

  PENDING/RUNNING -> CANCELLED:
    触发条件: 用户主动取消
    动作:
      1. update_status(CANCELLED)
      2. release_resource()
      3. cleanup_partial_results()
```

**使用场景**：
- 实体具有有限且明确的状态集合
- 状态之间的转换有明确的触发条件
- 需要描述转换时的副作用

---

## 5. 选用指南

| 场景特征 | 推荐模板 |
|----------|----------|
| 含类的多个方法、需要状态管理 | 完整类伪代码 |
| 数据变换流程、输入输出明确 | 数据流伪代码 |
| 有有限状态集合和明确转换 | 状态机伪代码 |
| 简单工具函数 | 单函数伪代码（无需模板） |
| API 调用编排 | 序列图（可选） |

**混用提示**：
- 同一 Phase 中可以混用多种模板
- 每个文件/类对应一种模板，保持单一职责
- 状态机适合顶层流程，类伪代码适合具体实现