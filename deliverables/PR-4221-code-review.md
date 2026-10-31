# PR #4221 代码评审

> https://github.com/ModelEngine-Group/nexent/pull/4221
> 标题 `Fix chat continuation after SSE disconnect and document verification`｜作者 hhhhsc701
> head `efe9a1a5e`｜**目标分支 `hotfix/v2.8.1`**｜基准 `11f516b60`
> 分析：nexent-review skill（R1 证据阶梯 / R2 反向验证 / R3 merge-base 归因 / R4 场景卡片）
> 时间：2026-10-27

---

## 一、版本方向核查

| 项 | 值 |
| --- | --- |
| PR head | `efe9a1a5e` |
| **目标分支** | **`hotfix/v2.8.1`** |
| 基准（真实起点） | `11f516b60`（PR head 的祖父提交） |
| 相对 develop 的 drift | 8 |
| **真实 commit** | **2 个**（`3bf8f438f` fix + `efe9a1a5e` docs） |
| **真实规模** | **8 文件 +612 / −20** |
| **业务代码** | **1 文件 +45 / −20**（`backend/management/services/agent/subscription.py`） |
| 前端/契约改动 | **0** |

### ⚠️ 基准选择（关键，否则范围会虚高 4 倍）

PR 分支基于 `hotfix/v2.8.1`，其中已包含 `#4209`（`aaad6f07d`）和 `#4212`（`11f516b60`）。

- 用 develop 做基准 → **78 文件 +3454/−357**，混入 #4209 的 21 文件和 #4212 的 40+ 文件，还有 4 个 `Release v2.8.0` / `Revert` 噪音
- 用 `11f516b60` 做基准 → **8 文件 +612/−20**，这才是本 PR

**标题与内容一致** ✅。两个 commit subject 都准确。

### 与已关闭的 #4216 是同一改动的两次提交

`#4216`（closed，head `e429b8a65`）是第一次提交，基于 develop；`#4221` 是移植到 `hotfix/v2.8.1` 的版本。design.md 明确记录了这次 cherry-pick：*"Cherry-picked `555306ea7` onto `hotfix/v2.8.1` at `11f516b60` without conflicts."*

---

## 二、风险等级（脚本判定）

按 `scoring.py` 的 `rate_change()`（rules v1.1）：

| 口径 | 评级 | 命中规则 |
| --- | --- | --- |
| 全部 8 文件（632 行） | 🟡 **中** | R5 规模中等（>150 行或 >5 文件） |
| **仅 1 业务文件（65 行）** | 🟢 **低** | 无命中 |

**上下文修正**：脚本判 🟢 低是因为业务代码只有 65 行变化。但这段代码是 **SSE 流式执行的生命周期核心**——reservation 归属、worker 清理、断连后是否继续执行，全部集中在这里。一旦出错的表现是"消息丢回复"或"并发重复执行"，属于**静默数据问题**。

我按 **🟡 中偏高** 处理（不覆盖脚本结论，只补充语义权重）。

---

## 三、变更总览

| # | 文件 | 增/删 | 类型 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | `agent/subscription.py` | +45/−20 | **变更** | producer 启动时机前移 + reservation 归属转移 + 新增 done callback |
| 2 | `test_agent_subscription_lifecycle.py` | +270 | **新增** | 8 个生命周期用例 |
| 3 | `test-e2e/cases/NB-CHAT-DISCONNECT-001/test.py` | +104 | 新增 | D3 正式用例（真实 provider） |
| 4 | `.../design.md` | +79 | 新增 | 设计文档（内容详实，见第五节） |
| 5 | `.../NB-CHAT-DISCONNECT-001/case.yaml` | +55 | 新增 | 用例定义 |
| 6 | `.../NB-CHAT-DISCONNECT-20261026.yaml` | +43 | 新增 | 缺陷变更记录 |
| 7 | `.../execution.yaml` | +15 | 新增 | 执行配置 |
| 8 | `test-e2e/features/F-146/cases.md` | +1 | 新增 | 用例关联页 |

---

## 四、代码链路追踪

### 4.1 修复的核心机制

| 步 | 位置 | 改前 | 改后 | 确信度 |
| --- | --- | --- | --- | --- |
| 1 | `stream_with_agent_context` 内 | producer 在**生成器内部**创建 | **移除** | 已确认 |
| 2 | `return StreamingResponse(...)` 之前 | 无 | **创建 producer + done callback** | 已确认 |
| 3 | subscriber `finally` | **无条件** release reservation | 仅 `channel is None` 时 release | 已确认 |
| 4 | producer 完成回调 | 仅 `discard` 任务 | `discard` + release reservation + 条件 cancel worker | 已确认 |

### 4.2 为什么"启动时机"是根因（R1 深挖）

Starlette 的 `StreamingResponse.__call__` 才会首次迭代 `body_iterator`（`starlette/responses.py` L255 `async for chunk in self.body_iterator`）。

改前的链路是：

```
return StreamingResponse(stream_with_agent_context())   ← 只是构造，不执行
        ↓
客户端读到 conversation_id header 后立即关闭连接
        ↓
Starlette 判定连接已断，从未迭代 body_iterator
        ↓
生成器体内的 producer 创建代码从未执行  ← BUG
        ↓
Agent 根本没开始跑，什么都没持久化
```

改后 producer 在 `return` 之前就 `create_task`，**与 body 迭代解耦**，客户端断开只是"没人消费 channel 了"，执行照常进行。

这与 design.md 的描述完全一致：

> Starting that producer inside the response generator tied startup to body iteration.

### 4.3 reservation 归属转移（第二处关键修复）

`release_agent_run_reservation` 的实现（`agent_run_manager.py` L96-108）：

```python
def release_agent_run_reservation(self, conversation_id, user_id, reservation_token) -> bool:
    """Release a reservation only when the caller still owns it."""
    with self._lock:
        run_key = self._get_run_key(conversation_id, user_id)
        if self._reservations.get(run_key) != reservation_token:
            return False
        del self._reservations[run_key]
        return True
```

**返回值语义**：`True` = 调用方仍持有 reservation（本次真的删掉了）；`False` = 已被别人消费。

改前 subscriber 的 `finally` 无条件 release → 客户端早期断开时，**prepare 阶段刚拿到的 reservation 被立即释放**，此时 run 还没 register → 并发请求可以再次通过 admission → **同一会话重复执行**。

改后：`channel is not None` 时不动 reservation，由 producer 的 done callback 在**执行结束后**释放。并且用 `reservation_released` 区分两种状态：

```python
if reservation_released and not execution.future.done():
    deferred_run.cancel()
    runtime_thread_manager.cancel(...)
```

- `reservation_released = True` → reservation 还在（未被 run 消费）→ worker 未绑定 → 需要主动 cancel
- `reservation_released = False` → reservation 已被 `generate_stream` 消费 → worker 已绑定 → **让它自己走完清理**，不能抢着 cancel

这个判断是准确的，注释也写清了（L1072-1075）。

---

## 五、场景验证与问题清单

### 🟡 M1 — 并发 `Channel` 场景下 done callback 未加异常保护

**场景**：Northbound 客户端只读 header 就断开，Agent 正在后台执行

**位置**：`subscription.py` L1064-1083 `release_producer_resources`

**问题**：这是一个 `add_done_callback` 的**同步回调**，内部三个操作都没有 try/except：

```python
def release_producer_resources(task: asyncio.Task) -> None:
    _agent_stream_producer_tasks.discard(task)
    reservation_released = agent_run_manager.release_agent_run_reservation(...)  # ← 可能抛
    if reservation_released and not execution.future.done():
        deferred_run.cancel()          # ← 可能抛
        runtime_thread_manager.cancel(...)  # ← 可能抛
```

若其中任一抛异常，asyncio 会走 `loop.call_exception_handler` 记 ERROR 日志，**后续清理全部跳过**——具体后果：

- `release_agent_run_reservation` 抛 → reservation **永久泄漏**，该会话后续所有请求都被 admission 拒绝（"并发重复执行"反向变成"再也跑不了"）
- `runtime_thread_manager.cancel` 抛 → 未绑定的 worker 残留，占容量

对比同文件 `_consume_agent_stream_producer`（`execution.py` L237-280）的 finally 块——那里每个操作都单独包了 `try/except` + `logger.exception`，说明作者**知道**这些调用会失败。而新加的回调没有沿用同样的防护。

**建议**（与既有风格对齐）：

```python
def release_producer_resources(task: asyncio.Task) -> None:
    _agent_stream_producer_tasks.discard(task)
    try:
        reservation_released = agent_run_manager.release_agent_run_reservation(
            run_identifier, resolved_user_id, reservation_token
        )
    except Exception:
        logger.exception(
            "Failed to release producer reservation conversation=%s",
            agent_request.conversation_id,
        )
        return
    if reservation_released and not execution.future.done():
        try:
            deferred_run.cancel()
            runtime_thread_manager.cancel(...)
        except Exception:
            logger.exception(
                "Failed to cancel unbound worker conversation=%s",
                agent_request.conversation_id,
            )
```

### 💭 L1 — D3 正式验收未执行，本次交付实为"UT 级验证"

design.md 自己明确标注了（诚实且清晰）：

> `.venv/bin/python test-e2e/infra/tools/run_cases.py NB-CHAT-DISCONNECT-001 AGT-064` is **BLOCKED**: `NEXENT_TEST_HOME` is unset and no runtime test home was supplied. Neither Case was executed.

我核实了 `NEXENT_TEST_HOME` 确实未设置，所以这个 BLOCKED 是真实的，不是偷懒。

**这意味着**：真实 HTTP + runtime + model + persistence 全链路**没有被验证过**。UT 用的是 mock stream，能证明"producer 在 body 迭代前启动"和"reservation 不被提前释放"，但证明不了"真实 provider 下 Agent 确实跑完并持久化了回答"。

**建议**：合入前在具备 `NEXENT_TEST_HOME` 的环境补跑 `NB-CHAT-DISCONNECT-001`。这条是 hotfix 分支合并前应该满足的条件，不是代码问题。

### 💭 L2 — 修复的是 process-local 语义，服务重启仍会丢执行

design.md 第 3 行主动说明了边界：

> This is process-local execution, not durable scheduling across server restarts.

也就是说：客户端断开 → 进程内 producer 继续跑到完成 ✅；但若**服务重启**，正在执行的 Agent 仍然丢失。

这个边界划得合理（不在本次 hotfix 范围），但值得在 release note 里说清楚，避免使用者误解为"发完就可以关服务"。

### 💭 L3 — design.md 提到的一处既有基线问题与本 PR 无关

> `CHAT-AGENT-DETAIL-20261026` references missing `frontend/tests/workbench/ConversationResumeBranch.test.tsx`

我核实了：该文件确实不存在，引用来自 `#4209` 的变更记录（`CHAT-AGENT-DETAIL-20261026.yaml` L38），**在基准 `11f516b60` 上就已如此**，本 PR 既没引入也没修复。

design.md 主动披露这一点是对的（R3 精神）。属存量问题，不阻塞本 PR。

---

## 六、测试验证

### 6.1 实跑结果（全部核实 design.md 的声明）

| 命令 | design.md 声称 | **我实测** | 一致 |
| --- | --- | --- | --- |
| `test_agent_subscription_lifecycle.py` | 8 个新用例 | **8 passed** | ✅ |
| 组合 `-k` 筛选（lifecycle + service） | 50 passed, 449 deselected | **50 passed, 449 deselected** | ✅ **完全吻合** |
| `test_runtime_proxy_service.py` + `test_streaming_channel.py` | 66 passed | **66 passed** | ✅ |

**这个 PR 的验证记录是可复现的**——两个数字精确对上，这在评审中不多见。

### 6.2 反向验证（R2）

| 实验 | 操作 | 结果 | 判定 |
| --- | --- | --- | --- |
| 1 | 把 producer 启动移回生成器内部（还原旧 bug） | **4 个用例变红** | ✅ 有效 |
| 2 | 恢复 subscriber `finally` 的无条件 release | **1 个用例变红** | ✅ 有效 |

**实验 1 的失败细节**（证明测试真的在验证"body 迭代前启动"）：

```
tasks = list(env.service._agent_stream_producer_tasks)
assert len(tasks) == 1
E   assert 0 == 1            ← producer 根本没被创建
FAILED test_headers_only_response_starts_producer_and_replays_completed_history
FAILED test_preparation_failure_releases_reservation_worker_and_capacity
FAILED test_producer_cancellation_releases_preparation_even_before_first_iteration[False]
FAILED test_producer_cancellation_releases_preparation_even_before_first_iteration[True]
```

**实验 2 的失败细节**（证明测试在验证"不提前释放 reservation"）：

```
with pytest.raises(env.errors.AgentRunAlreadyActiveError):
E   Failed: DID NOT RAISE AgentRunAlreadyActiveError
FAILED test_disconnect_during_preparation_preserves_reservation_and_rejects_duplicate
```

两处核心修复都有**精准对应的测试**守护，不是"改了代码顺便加点测试"。

### 6.3 测试设计中的亮点

8 个用例的划分体现了对生命周期的完整理解：

| 用例 | 覆盖 |
| --- | --- |
| `test_headers_only_response_starts_producer_and_replays_completed_history` | **本 PR 的核心场景**：只读 header 也启动 producer |
| `test_disconnect_during_preparation_preserves_reservation_and_rejects_duplicate` | prepare 中断连不释放 reservation，并发被拒 |
| `test_preparation_failure_releases_reservation_worker_and_capacity` | 失败路径释放干净 |
| `test_completed_producer_does_not_cancel_bound_worker_cleanup` | **关键边界**：不抢 cancel 已绑定的 worker |
| `test_producer_cancellation_releases_preparation_even_before_first_iteration[False/True]` | 参数化：首次迭代前/后的取消都要释放 |
| `test_debug_disconnect_still_cancels_direct_worker` | debug 分支行为未变 |
| `test_explicit_stop_after_subscriber_disconnect_still_reaches_worker` | 显式 stop 仍能触达 worker |

最后两个尤其重要——它们确认了**修复没有破坏相邻契约**（debug 直连流、显式停止）。

### 6.4 反向检测方法值得记录

design.md 描述了一个我未复现但很巧妙的手法：

> Negative detection used an uncommitted temporary pytest harness to load only the original `run_agent_stream` AST from the base commit into the test process. Product files were never replaced.

即：**不改产品文件**，只把基准版本的函数 AST 加载进测试进程来验证测试确实会失败。比我这轮的"改文件再还原"更安全（不会误留脏改动）。值得借鉴。

---

## 七、专项校验

| 检测项 | 结果 | 说明 |
| --- | --- | --- |
| 1. 数据格式/契约 | ✅ 无 | `frontend/`、`sdk/` 零改动；SSE 事件契约、HTTP 路由、payload 均未变（design.md 明确"HTTP routes, payloads and SSE event contracts stay unchanged"） |
| 2. 版本回退 | ✅ 无 | 2 个 commit，无 Revert |
| 3. 敏感信息 | ✅ 无 | 零命中 |
| 4. locale | ✅ 无 | 未改 locales |
| 5. 循环依赖 | ✅ 无 | 仅复用 `execution.py` 既有导入 |

---

## 八、合并预演

| 目标 | 结果 |
| --- | --- |
| vs develop | **0 冲突** |

但注意：实际目标是 `hotfix/v2.8.1`。该分支合 main 时按项目规约必须用 **merge commit**（禁 squash），否则祖先断裂会导致后续 develop→main 持续冲突。

---

## 九、结论

### 总评

**这是近期评审中技术含量最高、文档质量最好的一个 PR。**

修复思路非常精准：问题不在"producer 逻辑错"，而在**启动时机绑定了另一个生命周期（body 迭代）**。把 `create_task` 从生成器体内提到 `return` 之前，一行位置调整解决了根本问题。这种"找对根因，不做多余改动"的判断力值得肯定。

**第二处修复同样精准**：reservation 归属从 subscriber 转到 producer，并用 `reservation_released` 返回值区分"worker 是否已绑定"，避免了"抢着 cancel 已绑定 worker"这个非常容易踩的坑。注释也把两种状态写清了。

**design.md 是本次最大亮点**：79 行里包含了范围界定、既有证据盘点（哪些复用哪些新增）、AC 追溯表、真实命令输出、BLOCKED 原因、SHA-256 证据、验证局限声明。尤其难得的是**主动标注了"什么没验证"**：

> Missing runtime configuration or credentials blocks D3 acceptance and never counts as a pass.

这种"没有证据就不算通过"的态度，比很多声称"全部通过"的报告可信得多。

### 问题汇总

| # | 严重度 | 问题 | 场景 |
| --- | --- | --- | --- |
| M1 | 🟡 | `release_producer_resources` 回调无 try/except，任一失败会导致 reservation 永久泄漏 | 后台执行完成后清理抛异常 → 该会话再也无法发起新对话 |
| L1 | 💭 | D3 正式验收实际 BLOCKED 未执行，只有 UT 级证据 | 真实 provider 下的持久化行为未验证 |
| L2 | 💭 | 仅 process-local 语义，服务重启仍丢执行 | 使用者可能误以为"断开就安全了" |
| L3 | 💭 | design.md 提到的 `ConversationResumeBranch.test.tsx` 缺失属既有问题 | 与本 PR 无关，已核实 |

### 合并建议：**通过（建议补 M1 的异常保护 + L1 的 D3 验证）**

**无阻塞项。** 核心修复正确、测试有效、文档扎实。

**M1 是唯一建议改代码的**：这个回调是"执行结束后的最后一道清理"，它失败不会报给用户，只会留下泄漏的 reservation。而同一个文件里 `_consume_agent_stream_producer` 的 finally 已经有完整的 try/except + `logger.exception` 模式——**新代码没沿用既有风格**，补上即可（约 8 行）。

**L1 是合并前提**：UT 证明了机制，但证明不了真实链路。hotfix 合 main 前建议在具备 `NEXENT_TEST_HOME` 的环境跑一次 `NB-CHAT-DISCONNECT-001`。

L2/L3 只需在 release note / PR 描述里说明即可。

---

## 十、附：本次评审的关键取证

| 判断 | 证据 | 结果 |
| --- | --- | --- |
| 真实改动范围 | PR 基于 hotfix 分支，含 #4209/#4212 → 用 `11f516b60` 做基准 | 8 文件 +612/−20（而非 develop 基准的 78 文件 +3454） |
| 根因是否为"启动时机" | 读 `starlette/responses.py` L255 `async for chunk in self.body_iterator` | ✅ 构造 response 不迭代 body，故生成器内代码不执行 |
| `reservation_released` 语义 | 读 `agent_run_manager.py` L96-108 | ✅ True=仍持有并删除；False=已被消费 |
| 测试是否真的守护修复 | 2 组反向验证 | ✅ 4 红 / 1 红 |
| design.md 的 50 passed 是否可信 | 实跑同一命令 | ✅ **50 passed, 449 deselected**，精确吻合 |
| design.md 的 66 passed 是否可信 | 实跑 | ✅ **66 passed** |
| D3 BLOCKED 是否真实 | 检查 `NEXENT_TEST_HOME` | ✅ 未设置，BLOCKED 属实 |
| `ConversationResumeBranch.test.tsx` 缺失是否本 PR 引入 | 检查基准 `11f516b60` | ✅ 既有问题，引用来自 #4209 |
