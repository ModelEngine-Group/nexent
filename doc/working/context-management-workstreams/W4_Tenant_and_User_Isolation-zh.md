# W4：租户与用户隔离

## 目标

消除裸 Conversation 上下文状态，要求缓存、压缩快照、锁、指标、生命周期操作和授权均使用完整限定的身份。

## 现状与威胁模型

`backend/agents/agent_run_manager.py` 按用户和 Conversation 限定活动运行的范围，但可复用的 `ContextManager` 实例和运行计数仅按 `conversation_id` 建键。跨租户或用户的相同 ID 因此可能发生冲突。持久化会话、压缩快照和运行产物（Artifact）会在身份问题修复之前成倍放大影响。

## 身份契约

W4 负责身份解析、授权和身份限定的建键。它不定义事件 Schema、压缩快照内容或生命周期行为；W5 和 W7 消费已授权的身份契约。

引入不可变、无分支的 `ContextIdentity`：

```text
tenant_id, user_id, conversation_id
```

所有字段在 Conversation/会话状态变更时均为必填。智能体身份是运行属性，而非会话所有权字段，因为一个 Conversation 可能在不同时间执行不同的智能体。稳定序列化用于数据库唯一性约束、缓存键、分布式锁和指标标签。公共 API 从已认证的请求上下文中派生租户/用户身份，绝不能信任调用方提供的所有权字段。

### 子智能体身份契约

子智能体在自己的 `agent_session_id`（UUID）下运行，但继承父级的 `conversation_id`。`agent_session` 表记录 `parent_session_id`（UUID，可空）和 `delegation_type`（枚举：`'subagent'` 或 NULL）以捕获委派关系。

子智能体的 W4 `ContextIdentity` 使用与父会话相同的 `tenant_id` 和 `user_id`。子智能体授权遵循与普通智能体相同的规则，由其智能体配置决定。

递归委派被禁止：子智能体不能创建子子智能体。

**发现：** CM-025。

### 初始单所有者契约

初始版本为每个 Conversation 及其 W5 `agent_session` 支持恰好一个不可变的所有 `tenant_id` 和 `user_id`。不支持 Conversation 成员、共享会话访问或所有权转移。未来的产品请求若需给另一个用户独立副本，则创建新的 Conversation/会话；不改变原始所有者的持久身份。

共享智能体、租户共享记忆和其他独立治理的资源不授予对 Conversation、会话、事件、压缩快照、运行产物（Artifact）、投影或生命周期操作的访问权限。显式管理员/运维特权（如单独定义）是经审计的策略例外，绝不改变会话所有权。

## 授权规则

- 普通 Conversation/会话的读写要求已认证用户与可信后端代码解析的不可变所有者匹配。
- 共享 Conversation 或转移所有权的请求返回 `shared_conversation_unsupported` 或 `ownership_transfer_unsupported`。
- 普通未授权资源访问返回现有的不泄露信息的 `access_denied`/`not_found` 行为，而非暴露其他用户的资源是否存在。
- 共享智能体和租户共享记忆状态使用自身的显式策略和作用域，而非省略的用户 ID 或继承的 Conversation 访问权限。
- 跨租户操作在存储查找之前即被拒绝。
- 指标必须避免无界的原始身份标签；使用作用域哈希或聚合标签。
- 删除和清理操作使用相同的身份契约。

## 身份解析契约

```text
resolve_context_identity(authenticated_request, conversation_id) -> ContextIdentity
authorize_context_operation(identity, operation, resource) -> AuthorizationDecision
```

不可变身份按规范方式序列化。决策包含允许/拒绝、策略版本、原因码和审计元数据。租户/用户所有权始终由服务端派生和验证。必需的拒绝包括 `identity_not_found`、`tenant_mismatch`、`user_not_authorized`、`conversation_not_owned` 和 `resource_scope_mismatch`。调用方提供的身份字段或授权决策不可信。模型调度和受治理的持久化要求当前服务端签发的允许决策绑定到正在执行的操作和资源。

## 建键、交付物和阶段

- 缓存、持久唯一性约束、锁和清理选择器使用完整身份或抗碰撞的规范哈希；原始身份不作为指标标签。
- 交付共享身份模型、解析器、授权矩阵/服务、迁移后的运行时/存储键、碰撞报告和拒绝访问审计事件。
- 分阶段实施：影子双键比较、缓存/运行/锁迁移、完全强制执行，最后移除裸内部变更 API 和旧版键。

## 实施计划

1. 在后端和 SDK 边界模型中添加 `ContextIdentity`。
2. 替换 `AgentRunManager` 中的字符串键构造。
3. 在上下文管理器创建、清理和运行注册中要求身份。
4. 验证 W5 持久化 Schema 包含身份列和复合索引；与 W5 实施协调以确保对齐。
5. 添加供压缩快照、运行产物（Artifact）和生命周期操作使用的授权服务。
6. 将仅接受 `conversation_id` 的内部变更 API 标记为已弃用，并注明将在下一版本中移除。公共 Conversation API 可以保留 `conversation_id` 作为参数，但必须从请求上下文中解析和授权完整身份。
7. 为拒绝访问添加结构化安全审计事件。
8. 要求模型调度和受治理的持久化边界拒绝缺失、过期、不匹配或调用方提供的授权决策。

## 代码触点

- `backend/agents/agent_run_manager.py`
- `backend/agents/create_agent_info.py`
- `backend/apps/agent_app.py`
- `backend/apps/conversation_management_app.py`
- `backend/services/conversation_management_service.py`
- `backend/database/conversation_db.py`
- W5-W7 的新事件日志、运行产物（Artifact）和生命周期模块

## 测试

- 碰撞测试使用跨租户和用户的相同 Conversation ID。
- 授权测试覆盖读取、写入、删除、恢复和运行产物（Artifact）访问。
- 单所有者测试拒绝共享和所有权转移请求，证明共享智能体或租户共享记忆的访问不授予会话访问权限，并证明经审计的运维特权不改变会话所有者。
- 并发测试证明锁是身份限定的。
- 清理测试证明删除一个身份时所有碰撞身份不受影响。
- 静态检查或定向仓库测试拒绝新的裸 ID 上下文变更 API。
- 负面集成测试证明 SDK/客户端的身份和授权断言不能授权模型调用或受治理的持久化。
- 子智能体身份测试证明子智能体会话继承父级租户/用户和 conversation_id。
- 递归委派测试证明子智能体不能创建子子智能体。
- 子智能体授权测试证明子智能体权限由其自身的智能体配置决定。

## 上线与完成标准

短暂使用双键内存状态并记录不匹配，然后切换到完整身份并移除旧版键。现有 Conversation 在迁移期间获得内部 W5 会话。当每次上下文状态变更都需要已授权的 `ContextIdentity`、不支持的共享/转移显式失败、且碰撞/安全测试套件全部通过时，W4 即完成。
