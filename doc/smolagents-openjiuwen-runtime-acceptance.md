# Nexent 单服务、Agent 级运行框架验收说明

> 日期：2026-07-21  
> 状态：实现与真实环境验收完成；固定使用已有 `openjiuwen==0.1.16`，OpenSpec change 保持未归档

## 1. 验收边界

通过验收必须同时满足：

- 仅有 `nexent-runtime:5014` 和现有 `nexent-mcp:5011`，没有 OpenJiuwen Runtime/Gateway 服务或新端口；
- Agent 首次保存时选择框架，之后 UI、API、版本回滚和数据库都无法修改；
- `/agent/run` 只依据 Agent 数据分派，debug/request/tenant 不能覆盖且失败不 fallback；
- Smolagents 路径不导入 OpenJiuwen；OpenJiuwen 首次选择时才在同一进程初始化；
- 本地工具/Knowledge/Memory/Skill/A2A 走 LocalFunction，MCP 直连现有 endpoint；
- 内部父子 Agent同框架、无环，子 Agent作为工具递归运行；
- success/error/cancel/timeout/shutdown 后无请求级资源泄漏。

## 2. 当前自动化结果

验收结果以实际命令输出为准。最终依赖与代码状态下的结果如下：

| 范围 | 结果 | 覆盖 |
| --- | ---: | --- |
| 全量 Python runner | 10,955 passed | 272 个 backend/SDK 测试文件，0 failed，总覆盖率 83% |
| OpenJiuwen runtime | 19 passed | 0.1.16 core API、SSL config、stream cleanup、LocalFunction、MCP、A2A、子 Agent、取消、timeout、shutdown |
| Memory/Memory tools | 57 passed | 升级后的 mem0 API 调用与搜索/写入工具回归 |
| 前端 | type-check/build passed；4 passed | TypeScript、生产构建、创建默认/锁定、同框架过滤、保存/复制继承、中英文文案 |
| 部署 | passed | `deploy/tests/test_common.sh`、Compose 与仅 Runtime/MCP 的 Helm render 静态检查 |
| OpenSpec | passed | `openspec validate separate-smolagents-openjiuwen-runtimes --strict` |
| main 镜像 | passed | 两个构建期 import smoke、依赖约束检查和 `pip check` |
| 真实双框架 E2E | passed | 同一 5014 先运行 Smolagents，再懒启动 OpenJiuwen；SSE、final answer、资源注销和消息持久化成功 |
| 真实 MCP endpoint | passed | 从 `nexent-runtime` 直连 `http://nexent-mcp:5011/sse` 并发现已注册工具，无新增 MCP 进程或端口 |

全量 runner 使用逐文件隔离，避免既有测试模块对 `sys.modules` 的全局 mock 在文件间互相污染。`npm run check-all`
中的 type-check 与 production build 均通过；全仓 lint/format 仍会报告本变更范围外既有的 Agent Repository、A2A 和版本页面
格式问题，因此未将其误记为本变更通过项。

## 3. 数据库与 API 验收

### 3.1 数据库

执行 fresh init 后继续应用版本迁移，或在已有环境直接应用版本迁移，然后验证：

```sql
SELECT runtime_framework, count(*)
FROM nexent.ag_tenant_agent_t
GROUP BY runtime_framework;
```

预期历史行全部为 `smolagents`。随后分别验证：

1. 插入 `NULL` 空白 Agent成功；
2. `NULL -> openjiuwen` 成功；
3. `openjiuwen -> openjiuwen` 成功；
4. `openjiuwen -> smolagents` 和 `openjiuwen -> NULL` 触发 `AGENT_RUNTIME_FRAMEWORK_IMMUTABLE`；
5. 非法值违反 check constraint；
6. 草稿和历史版本快照字段一致。

### 3.2 API

- 新客户端显式创建两种框架均成功；
- 旧创建 payload 缺字段得到 Smolagents；
- 已有 OpenJiuwen Agent的旧更新 payload 缺字段仍保留 OpenJiuwen；
- 相同值更新成功，不同值返回 HTTP 409 和 code `030106`；
- 混合内部关系返回 HTTP 409 和 code `030107`；
- NULL 空白 Agent运行/发布前返回 code `030108`；
- 列表、详情、版本、导出和市场快照字段完整；
- 混合框架导入在第一笔写入前失败；
- run/debug payload 即使携带额外同名字段也不能覆盖持久化框架。

## 4. 前端验收

1. 进入创建页面时 selector 显示 Smolagents；
2. 保存前可切换到 OpenJiuwen，切换后已选内部子 Agent被清空；
3. 首次保存成功后 selector 禁用并显示“创建后不可修改”；
4. 刷新、切换 Agent、版本详情后仍显示正确框架；
5. 复制 Agent后新 Agent继承来源框架且立即锁定；
6. 内部子 Agent候选只显示同框架 Agent，外部 A2A 不过滤；
7. 中英文标签、不可变和冲突提示正确；
8. 非框架字段编辑和保存不受影响。

## 5. Runtime 验收

### 5.1 Lazy 与并发

- 冷启动后只运行 Smolagents，`openjiuwen` 不在已导入模块且 Runner 未启动；
- 首次 OpenJiuwen run 才 import 0.1.16 core API 并启动 Runner；
- 同一进程交替及并发运行两种框架；
- OpenJiuwen 初始化/模型/工具失败只产生 OpenJiuwen failure，不调用 `agent_run()`；
- shutdown 只关闭已初始化 provider。

### 5.2 OpenJiuwen 能力

- 纯对话与 history；
- 不同模型配置；
- Knowledge 检索与 source 事件；
- Memory 层级、共享/禁用策略及运行后写入；
- Skill sandbox、脚本执行、artifact 捕获与上传；
- 普通本地工具输入 schema 和结果事件；
- 外部 A2A 代理；
- 两层及以上同框架子 Agent，仅根产生外层 final answer；
- stop、timeout、模型错误、工具错误和进程 shutdown 清理。

### 5.3 MCP

- 连接现有 `nexent-mcp:5011`，没有新增监听端口；
- 连接 Agent 已配置的外部 SSE/Streamable HTTP endpoint；
- 一个 server 暴露额外工具时，只绑定 Agent allowlist；
- required server/tool 缺失阻止运行；optional 缺失产生 warning；
- header/token 不出现在 Agent JSON、event、异常、日志或 repr；
- 同 server 并发运行使用不同 request-scoped ID，结束后 server/tool/callback 数量回到基线。

## 6. 部署验收

运行：

```bash
bash deploy/tests/test_common.sh
```

并检查 Compose/Helm 渲染结果：

- 不含 `openjiuwen-runtime` service、subchart、profile 或 image 变量；
- 不含 `AGENT_RUNTIME_PROVIDER`、远程 Runtime URL/timeout、Capability Gateway/grant/signing key；
- `nexent-runtime` 仍使用 main 镜像、原启动命令和 5014；
- `nexent-mcp` 仍使用原进程和 5011；
- 实际启动后的监听端口与容器/Pod 数量没有新增 Runtime/MCP 项。

## 7. 0.1.16 依赖门禁

最终采用以下兼容依赖组合：

1. `backend/pyproject.toml` 和 `backend/uv.lock` 均固定为 0.1.16；
2. SDK 使用 `openai>=1.108.0`、`mem0ai==1.0.0` 和 `orjson>=3.11.5`，避免 0.1.117 的 OpenAI `<1.100.0` 上限及 3.10.0 的 orjson 冲突；
3. 最终镜像实际解析为 `openjiuwen 0.1.16`、`openai 2.46.0`、`mem0ai 1.0.0`、`orjson 3.11.9`，所有声明约束满足；
4. main 镜像的 core API 与 in-process provider 两个 import smoke 都成功；
5. 最终镜像已完成真实模型、SSE、持久化和现有 MCP endpoint E2E。

任何一项失败都不得归档 OpenSpec change，也不得通过修改 Agent框架或 fallback 掩盖故障。

## 8. 回滚验收

- 应用回滚不修改数据库中的 `runtime_framework`；
- 版本回滚只允许相同框架快照；
- 不存在部署级开关把 OpenJiuwen Agent改成 Smolagents；
- 如需框架转换，复制业务配置并创建新的目标框架 Agent；
- 回滚后 Smolagents golden、已有 OpenJiuwen Agent的明确不可用提示和数据完整性均可验证。
