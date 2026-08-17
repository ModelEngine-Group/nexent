# 外部记忆插件开发与使用指南

Nexent 外部记忆插件用于把第三方记忆服务接入 Agent 的记忆检索与会话写入流程。插件由一个清单文件和一个 Python Provider 实现组成，不需要修改 Nexent SDK 的检索协议。

## 工作方式

外部记忆有两个独立能力：

- `searchable`：会话开始和 `search_memory` 工具执行时检索第三方记忆，并与内置记忆一起注入 Agent 上下文。
- `ingestible`：会话结束后把提取出的记忆单元写入第三方服务。

部署级总开关 `EXTERNAL_MEMORY_SEARCH_ENABLED` 和 `EXTERNAL_MEMORY_INGEST_ENABLED` 默认均为 `false`。Provider 配置中的 `enabled` 是租户级、实例级开关；只有总开关和实例开关同时启用，正常会话链路才会调用插件。管理页面的“测试检索/测试写入”用于连通性检查，会绕过实例的 `enabled` 状态。

## 插件目录结构

每个插件位于 `MEMORY_PROVIDER_PLUGINS_DIR` 下的独立目录中：

```text
memory-provider-plugins/
└── example-provider/
    ├── plugin.yaml
    └── provider.py
```

容器内固定扫描目录是 `/mnt/nexent-data/memory-provider-plugins`，对应 Nexent 数据目录中的 `memory-provider-plugins` 子目录。Docker 使用宿主机目录挂载，Kubernetes 使用独立 PV/PVC。内置 Mem0 参考实现位于 `backend/memory_provider_plugins/mem0/`，但第三方插件应放入部署实例的 `nexent-data/memory-provider-plugins`，不需要复制进源码目录、提交 Git 或重新构建 Nexent 镜像。

配置服务和 Agent runtime 必须看到同一路径及相同目录内容。Loader 会执行插件入口中的 Python 代码，因此只能安装经过审核、来源可信的插件，并使用文件系统权限限制谁能修改插件目录。

## 编写 plugin.yaml

```yaml
name: example-provider
version: "1.0.0"
description: "Example external memory provider"
entry_point: "provider.py"
class_name: "ExampleProvider"
implements:
  - searchable
  - ingestible
config_schema:
  - key: api_key
    label: "API Key"
    type: secret
    required: true
  - key: base_url
    label: "API Base URL"
    type: string
    required: false
    default: "https://memory.example.com"
```

必填字段为 `name`、`version`、`entry_point`、`class_name` 和 `implements`。`implements` 只接受 `searchable`、`ingestible`，可只实现其中之一。`config_schema` 驱动前端动态表单和后端参数校验；Provider 构造函数收到的配置键不带数据库中的 `plugin.` 前缀。

敏感配置使用 `type: secret`。Nexent 在读取配置时会掩码显示，但 Provider 运行时会收到原值。不要把 API Key 写入代码、日志、异常消息、测试快照或 OTel 属性。

## 实现 Provider

协议定义在 `sdk/nexent/memory/providers/base.py`，数据模型定义在 `sdk/nexent/memory/models.py`。方法必须是异步方法。

```python
from nexent.memory.models import (
    MemoryIngestRequest,
    MemoryIngestResult,
    MemorySearchRequest,
    MemorySearchResult,
)


class ExampleProvider:
    def __init__(self, config: dict):
        self.api_key = config["api_key"]
        self.base_url = config.get("base_url", "https://memory.example.com")
        self.timeout = int(config.get("timeout_seconds", 30))

    @property
    def provider_name(self) -> str:
        return "example-provider"

    async def search(
        self,
        request: MemorySearchRequest,
        limit: int = 5,
        filters: dict | None = None,
    ) -> list[MemorySearchResult]:
        ...

    async def ingest(self, request: MemoryIngestRequest) -> MemoryIngestResult:
        ...
```

### 检索映射

向第三方服务传递 `query`、`user_id`、可选的 `agent_id` 和 `conversation_id`，并尊重 `limit`。返回值中的每一项应映射为：

- `external_id`：第三方记忆的稳定 ID。
- `content`：可直接提供给 Agent 的文本。
- `score`：浮点相关度分数。
- `source`：稳定的 Provider 名称。
- `is_external=True`。
- `metadata`：不含凭据的扩展字段。

不要把其他租户或用户的数据并入结果。第三方服务不支持某个作用域时，应在文档中明确降级规则。

### 写入映射

逐个处理 `MemoryIngestRequest.units`，并为每个单元返回 `UnitIngestResult`。汇总 `accepted_count`、`rejected_count` 和整体 `status`：全部成功为 `ok`，部分成功为 `partial`，全部失败为 `error`。向第三方传递 `idempotency_key` 或 `event_id`，避免重试导致重复记忆。

### 错误分类

使用 `nexent.memory.providers.retry` 中的异常：

- `RetryableProviderError`：超时、连接失败、HTTP 429、HTTP 5xx。
- `NonRetryableProviderError`：HTTP 401/403、无效请求或不可恢复的配置问题。
- `DegradableProviderError`：调用失败但可以安全忽略并继续 Agent 会话的场景。

异常应携带 `ProviderError`，并选择稳定的 `ProviderErrorCode`。外部 Provider 服务会统一执行重试、降级、错误记录和 OTel 观测；插件不应记录记忆正文或鉴权信息。

## Mem0 示例

参考实现：

- `backend/memory_provider_plugins/mem0/plugin.yaml`
- `backend/memory_provider_plugins/mem0/provider.py`
- `test/backend/memory_provider_plugins/test_mem0_provider.py`

Mem0 插件实现 `searchable` 和 `ingestible`，使用 `Authorization: Token ...` 调用托管 API：

- 检索：`POST /v1/memories/search/`
- 写入：`POST /v1/memories/`
- 可选组织头：`X-Org-Id`

它把 Nexent 的 `user_id`、`agent_id` 和 `conversation_id` 分别映射到 Mem0 的 `user_id`、`agent_id` 和 `run_id`。当同时按用户和 Agent 检索为空时，会回退到仅用户作用域检索。401/403 被归类为不可重试，429/5xx 和网络故障被归类为可重试。

## 单元测试：禁止依赖真实服务

CI 中必须 mock HTTP 边界，不能读取真实 API Key，也不能访问真实外部记忆服务。Mem0 示例使用 `httpx.MockTransport`：

```python
import httpx


def install_transport(monkeypatch, handler):
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client(**kwargs):
        return original_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
```

至少覆盖：清单加载、构造、检索成功与空结果、写入成功与部分成功、作用域映射、401/403、429、5xx、超时、连接失败，以及响应字段缺失。建议命令：

```bash
source backend/.venv/bin/activate
pytest test/backend/services/test_memory_provider_plugin_loader.py -v
pytest test/backend/memory_provider_plugins/test_mem0_provider.py -v \
  --cov=backend.memory_provider_plugins.mem0.provider --cov-report=term-missing
```

新增或修改模块的覆盖率目标不低于 90%。真实服务验证只能作为显式授权的集成测试，不能替代网络隔离的 UT。

## 安装与配置

1. 按下文方法找到当前部署使用的 `nexent-data` 根目录。
2. 把插件完整目录复制到其 `memory-provider-plugins/<plugin-name>` 子目录。
3. 重启配置服务和 Agent runtime，使各自的插件加载器重新扫描已有固定目录。
4. 在“记忆管理 → 外部记忆服务”中新增 Provider，选择插件并填写动态配置。
5. 先保持 Provider 禁用，执行“测试检索”和“测试写入”。
6. 测试通过后启用 Provider，并在部署配置中打开所需总开关。
7. 发起 Agent 会话，通过唯一测试标记分别验证内置记忆和外部记忆检索。

Docker/Compose 部署：部署脚本默认把 `ROOT_DIR` 设为 `$HOME/nexent-data`，也可能由 `--root-dir` 参数或 `deploy/env/.env` 中的 `ROOT_DIR` 覆盖。因此插件宿主机位置为：

```bash
${ROOT_DIR}/memory-provider-plugins/<plugin-name>
```

可执行以下命令确认实际值，不要假定它始终位于当前代码目录：

```bash
grep '^ROOT_DIR=' deploy/env/.env
```

Kubernetes 本地存储模式：默认宿主机位置来自 Helm `global.sharedStorage.memoryPlugins.localPath`，当前默认值为 `/var/lib/nexent-data/memory-provider-plugins`。其他 StorageClass 模式下，插件位于 `global.sharedStorage.memoryPlugins.existingClaim` 指向的 PVC（默认 `nexent-memory-plugins`）中，而不是某个固定宿主机目录。配置服务和 runtime 都把该 PVC 挂载到容器内 `/mnt/nexent-data/memory-provider-plugins`。

直接运行后端进程时，应保持同一目录结构，并显式指定容器外的数据目录，例如：

```bash
export MEMORY_PROVIDER_PLUGINS_DIR="$HOME/nexent-data/memory-provider-plugins"
```

也可以通过 `GET /memory/provider-plugins` 检查插件是否被发现，通过 `/memory/providers` 系列接口管理配置。所有接口均按认证令牌中的租户隔离。

## 可观测性与排障

外部调用产生名为 `nexent.memory.external_provider` 的 span，以及请求数、耗时、搜索结果数和写入接受/拒绝数指标。常用属性包括 `operation`、`provider`、`outcome`、`error_code` 和 span 上的 `provider_config_id`。

排障顺序：

1. 确认插件出现在 `/memory/provider-plugins`；否则检查目录、清单、入口文件和启动日志。
2. 确认测试接口成功；`unauthorized` 通常表示凭据格式、组织 ID 或目标环境不匹配。
3. 确认 Provider 实例 `enabled=true`，并确认对应部署总开关为 `true`。
4. 检查 OTel span 的 `outcome` 和 `error_code`，但不要把查询或凭据加入观测字段。
5. 检查用户、Agent 和会话作用域映射是否与第三方数据一致。

OTel 不可用时业务调用仍应继续；若看不到 span，应检查遥测启用状态和 OTLP exporter 配置，而不是据此判断插件未执行。
