# Nexent 官方智能体部署指南

本文用于在 Nexent 已经部署并正常运行后，单独部署官方智能体资源。官方智能体部署与 Nexent 主平台部署解耦，不需要重新构建或重启 Nexent 镜像。

## 1. 部署内容

官方智能体部署脚本会完成以下工作：

1. 从 Agent Hub Git 仓库、宿主机本地目录或离线压缩包读取官方智能体资源。
2. 让用户选择一个或多个行业 Profile，例如 `medical`、`finance`。
3. 将选中的 Profile 复制到 Nexent Config 服务可读取的位置。
4. 在运行中的 `nexent-config` 容器内执行同步脚本。
5. 将合法的 `agent.json` 快照写入官方保留租户的智能体仓库记录。

部署完成后，官方智能体会出现在“智能体仓库”的官方列表中。它们不会直接安装到每个普通租户的“我的智能体”中；用户需要在智能体仓库中点击复制。复制时，Nexent 会在当前租户内准备知识库、Skill、MCP，并创建当前用户自己的 Agent。

## 2. 前置条件

### Docker 部署

- Nexent 已通过 Docker 部署并运行。
- `nexent-config` 容器存在且健康。
- 宿主机可以执行 Docker 命令。
- 使用 Agent Hub 时需要 Git 和网络；使用本地目录或离线压缩包时不需要访问 Agent Hub。

检查服务：

```bash
docker ps --format "{{.Names}}\t{{.Status}}"
docker inspect nexent-config --format '{{.State.Status}}'
```

### Kubernetes 部署

- Nexent 已通过 Helm 部署并运行。
- 当前终端已配置 `kubectl` 和目标 namespace。
- 执行部署的节点能够访问官方资源目录。
- `/mnt/nexent/official-agents` 必须是 `nexent-config` Pod 可读取的目录，通常通过持久化卷或 HostPath 挂载。

检查服务：

```bash
kubectl get pods -n nexent
kubectl get deployment nexent-config -n nexent
```

## 3. 官方资源目录格式

脚本按 Profile 扫描目录。每个 Profile 下可以包含多个官方智能体，每个智能体使用自己的目录名：

```text
official-agents/
├── medical/
│   ├── medical_assistant/
│   │   ├── agent.json
│   │   ├── skills/
│   │   │   └── triage.zip
│   │   └── kb/
│   │       └── kb-1/
│   │           ├── guideline.pdf
│   │           └── protocol.docx
│   └── surgery_assistant/
│       └── agent.json
└── finance/
    └── finance_assistant/
        └── agent.json
```

`agent.json` 是必需文件。包含知识库文档时，文件应放在对应智能体目录的 `kb/` 下；包含 Skill 时，压缩包应放在 `skills/` 下。目录名就是官方 Bundle 的名称，后续用于重新定位和幂等同步。

一个 Profile 中可以放置多个智能体，也可以一次选择多个 Profile，例如：

```text
medical,finance
```

脚本只同步选中的 Profile，不会同步其他类别。

## 3.1 从 Nexent 导出的普通 Agent 生成 Official Bundle

仓库中已经提供转换脚本：

```text
scripts/build_official_agent_bundle.py
```

它将 Nexent 导出的普通 Agent JSON 或 ZIP 转换为官方 Bundle 目录。ZIP 输入应包含：

```text
agent.zip
├── agent.json
└── skills/
    └── <skill-name>.zip
```

JSON 只能转换 Agent 配置；如果 Agent 引用了 Skill，建议使用 ZIP，以便同时携带 Skill 压缩包。

### 3.1.1 导出普通 Agent

在 Nexent 页面中进入“智能体仓库 → 我的 Agent”，对目标 Agent 执行“导出”：

- 选择 JSON：只导出 Agent 配置；
- 选择 ZIP：导出 Agent 配置和 Skill 文件。

将下载文件放到 Nexent 仓库外的临时目录，例如：

```text
/opt/agent-exports/medical_assistant.zip
```

### 3.1.2 转换为 Profile 目录

从 Nexent 仓库根目录执行：

```bash
python scripts/build_official_agent_bundle.py \
  --input /opt/agent-exports/medical_assistant.zip \
  --name medical_assistant \
  --icon 🏥 \
  --tags medical,clinical \
  --version-label V1 \
  --output deploy/docker/assets/official-agents/medical
```

执行后生成：

```text
deploy/docker/assets/official-agents/medical/medical_assistant/
├── agent.json
└── skills/
    └── <skill-name>.zip
```

这里的 `medical` 是 Profile 名称，`medical_assistant` 是 Bundle 目录名。`--output` 应指向 Profile 目录，不能只指向 `deploy/docker/assets/official-agents`，否则生成的 Bundle 不在脚本所扫描的 Profile 层级下。

### 3.1.3 带入知识库文档

转换脚本会从 Agent 工具配置中的 `index_names` 识别知识库引用，并生成 Bundle 内部的逻辑知识库名称，例如 `kb-1`。默认情况下，脚本会尝试从源 Nexent 数据库查询知识库显示名称和描述。

为官方智能体准备文档时，可以使用 `--kb-dir` 将本地文档目录复制到对应知识库：

```bash
python scripts/build_official_agent_bundle.py \
  --input /opt/agent-exports/medical_assistant.zip \
  --name medical_assistant \
  --tags medical,clinical \
  --output deploy/docker/assets/official-agents/medical \
  --kb-dir /opt/agent-exports/medical-kb
```

生成结果类似：

```text
deploy/docker/assets/official-agents/medical/medical_assistant/
├── agent.json
├── skills/
└── kb/
    └── kb-1/
        ├── guideline.pdf
        └── protocol.docx
```

一个 Bundle 有多个知识库时，可以重复指定 `--kb-dir`：

```bash
python scripts/build_official_agent_bundle.py \
  --input agent.zip \
  --output deploy/docker/assets/official-agents/medical \
  --kb-dir /opt/agent-exports/kb-1 \
  --kb-dir /opt/agent-exports/kb-2
```

如果目录名与生成的逻辑名称相同，脚本会按名称匹配；否则按知识库出现顺序匹配。也可以直接手工将文档放到生成目录的 `kb/<logical_index_name>/` 下。

### 3.1.4 无法连接源数据库时

如果源数据库不可访问，转换脚本会打印 `DB lookup skipped`，仍然生成 Bundle，但知识库显示名称会退化为生成的逻辑名称，例如 `kb-1`。这不会阻止转换，但建议在发布前手工修改 `agent.json` 中对应 `knowledge_bases` 项的 `display_name` 和 `description`，并确认工具中的 `params.index_names` 使用同一个逻辑名称。

也可以显式跳过数据库查询：

```bash
python scripts/build_official_agent_bundle.py \
  --input agent.zip \
  --output deploy/docker/assets/official-agents/medical \
  --no-db-lookup
```

`--no-db-lookup` 只影响知识库元数据查询，不会自动把源知识库文档复制进 Bundle。文档仍需通过 `--kb-dir` 或手工复制到 `kb/` 目录。

### 3.1.5 发布前检查

转换完成后，确认以下内容：

```bash
find deploy/docker/assets/official-agents/medical \
  -type f \( -name agent.json -o -name '*.zip' \) -print
```

并检查 `agent.json`：

- `agent_id` 和 `agent_info` 完整；
- 根 Agent 名称符合发布命名要求；
- `knowledge_bases[].logical_index_name` 与工具 `params.index_names` 一致；
- 文档存在于 `kb/<logical_index_name>/`；
- Skill ZIP 文件名与 Agent 的 `skill_names` 一致；
- `--tags` 已设置为希望用户在复制/上架流程中看到的标签。

检查通过后，再执行本指南第 4 节的官方智能体部署命令：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path deploy/docker/assets/official-agents \
  --profiles medical
```

## 4. 统一部署命令

在 Nexent 仓库根目录执行：

```bash
bash deploy/deploy-official-agents.sh
```

交互模式下脚本会依次询问：

1. 资源来源：Agent Hub，或本地目录/压缩包。
2. 要安装的 Profile。
Docker 是默认同步方式；Kubernetes 通过 `--kubernetes` 参数指定。

用户不需要手工执行 Git clone、`docker cp`、`kubectl cp` 或 `docker exec`。这些操作由部署脚本完成。

## 5. 从 Agent Hub 部署

默认使用 Agent Hub 的 `main` 分支：

```bash
bash deploy/deploy-official-agents.sh \
  --source hub \
  --profiles medical,finance
```

指定 Git 仓库和分支：

```bash
export OFFICIAL_AGENTS_REPO_URL="https://gitcode.com/ModelEngine/AgentsHub"

bash deploy/deploy-official-agents.sh \
  --source hub \
  --ref main \
  --profiles medical
```

脚本内部会执行等价于以下流程，但用户不需要手工执行：

```text
Git clone Agent Hub
        ↓
扫描 Profile 目录和 agent.json
        ↓
复制选中的 Profile 到临时目录
        ↓
复制到 Nexent Config 可读取的位置
        ↓
执行 backend/scripts/sync_official_agents.py
```

## 6. 从本地目录部署

本地目录必须包含 Profile 子目录。例如资源放在：

```text
/opt/agents-hub/official-agents/medical/medical_assistant/agent.json
```

执行：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path /opt/agents-hub/official-agents \
  --profiles medical
```

### Windows Git Bash

在 Windows Git Bash 中，宿主机路径建议使用 MSYS 路径格式：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path /c/Users/HAN/PycharmProjects/nexent/official-agents \
  --profiles general
```

不要把 `C:/Users/...` 直接作为容器内路径传递。`C:/...` 是宿主机路径，`/mnt/nexent/official-agents` 是容器内路径；脚本负责二者之间的复制，二者不能混用。

## 7. 从离线压缩包部署

没有网络时，可将包含 Profile 目录的 `.zip` 或 `.tar` 文件复制到现场机器，再通过本地模式部署：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path /opt/packages/official-agents.zip \
  --profiles medical,finance
```

脚本会先解压到临时目录，再执行与本地目录相同的扫描、复制和同步流程。压缩包内的路径不能包含绝对路径或 `..` 路径，否则会被拒绝。

离线部署仍然要求现场已经具备：

- Nexent 所需的 Docker 镜像或 Kubernetes 镜像；
- 正常运行的 Nexent 服务；
- 官方智能体资源压缩包；
- 官方智能体依赖的 Skill 和文档文件。

官方智能体资源包本身不等同于 Nexent 平台镜像离线包，两者需要分别准备。

## 8. Kubernetes 部署

如果使用 Kubernetes，增加 `--kubernetes` 和 namespace 参数：

```bash
bash deploy/deploy-official-agents.sh \
  --kubernetes \
  --namespace nexent \
  --source local \
  --path /opt/packages/official-agents.zip \
  --profiles medical
```

Kubernetes 模式最后会在 `nexent-config` Deployment 中执行：

```bash
kubectl exec deployment/nexent-config -n nexent -- \
  python backend/scripts/sync_official_agents.py \
  --base-dir /mnt/nexent/official-agents \
  --profiles medical
```

如果资源文件只存在于执行命令的宿主机，而没有挂载到 Pod 内，复制步骤可能成功，但同步时会显示找不到 Profile。此时需要先检查 Pod 内的目录：

```bash
kubectl exec deployment/nexent-config -n nexent -- \
  find /mnt/nexent/official-agents -maxdepth 3 -type f -name agent.json
```

## 9. 同步过程与数据库结果

同步脚本的入口是：

```text
backend/scripts/sync_official_agents.py
```

脚本实际调用 `sync_official_agents()`，完成以下处理：

1. 解析 `--profiles` 指定的 Profile。
2. 加载每个智能体目录中的 `agent.json`、Skill ZIP 和知识库文档。
3. 在官方保留租户 `__nexent_official__` 下创建或复用源 Agent。
4. 将官方 Agent 快照写入智能体仓库，并标记为 `shared`。
5. 记录官方发布租户，使前端可以显示“官方”标识。

命令输出示例：

```text
Synchronized 2 official agent bundle(s)
Official Agent deployment completed for profiles: medical
```

这里的 `2` 表示成功同步到智能体仓库的 Bundle 数量，不表示已安装到普通用户的“我的智能体”数量。

## 10. 用户侧安装流程

部署同步完成后，用户在 Nexent 页面执行：

```text
智能体仓库
    ↓
选择官方智能体
    ↓
点击复制
    ↓
选择语言模型
    ↓
如有知识库，首次安装时选择向量模型
    ↓
检查当前租户已有 Knowledge Base、Skill、MCP
    ↓
已有资源复用，不存在的资源创建
    ↓
创建当前用户的 Agent
```

知识库、Skill 和 MCP 的准备以租户为范围；Agent 本身属于当前用户。因而同租户的其他用户再次复制相同官方智能体时，可以复用已经准备好的租户资源，但仍会创建自己的 Agent 副本，并使用用户邮箱区分显示名称。

如果首次复制包含知识库的官方智能体时，当前租户没有可用向量模型，复制流程应在页面提示配置向量模型，而不是创建一个没有实际索引的占位知识库。

## 11. 验证部署结果

### Docker

查看同步日志：

```bash
docker logs nexent-config --tail 200
```

确认容器内资源文件：

```bash
docker exec nexent-config \
  find /mnt/nexent/official-agents -maxdepth 4 -type f -name agent.json
```

手工重复同步某个 Profile：

```bash
docker exec nexent-config \
  python backend/scripts/sync_official_agents.py \
  --base-dir /mnt/nexent/official-agents \
  --profiles medical
```

重复执行应更新或复用官方仓库记录，不应产生重复的官方仓库条目。

### Kubernetes

```bash
kubectl logs deployment/nexent-config -n nexent --tail=200
kubectl exec deployment/nexent-config -n nexent -- \
  find /mnt/nexent/official-agents -maxdepth 4 -type f -name agent.json
```

然后登录 Nexent，在“智能体仓库”中检查官方智能体是否出现。

## 12. 常见问题

### `profile not found`

表示 `--profiles` 中的名称不是资源根目录下的直接子目录，或本地路径传错。先确认：

```bash
find /path/to/official-agents -mindepth 1 -maxdepth 1 -type d
```

### `Official agent profile directory not found`

表示同步脚本在容器内找不到 `--base-dir` 下的 Profile。常见原因是把 Windows 宿主机路径误当成容器路径，例如：

```text
/opt/C:/Users/...
```

应让部署脚本先将宿主机目录复制到容器，再使用容器内路径：

```text
/mnt/nexent/official-agents
```

### `Synchronized 0 official agent bundle(s)`

表示目录可以访问，但没有成功写入官方仓库记录。重点检查：

1. Profile 下是否存在 `agent.json`；
2. `agent.json` 是否能被解析；
3. Bundle 中引用的 Agent、Skill、MCP 数据是否完整；
4. `nexent-config` 是否能访问数据库；
5. 日志中是否存在某个 Bundle 的异常堆栈。

### 智能体仓库显示 0 个官方智能体

先检查同步命令的输出和数据库连接，再确认当前页面请求的是最新服务实例。同步成功只代表仓库数据已写入，页面仍需重新加载配置清单。

### 复制官方智能体时知识库没有创建

确认以下条件：

- 当前用户所在租户有可用向量模型；
- 官方 Bundle 中确实存在 `knowledge_bases`；
- `kb/` 文档已经随资源包复制到容器；
- `nexent-data-process`、Elasticsearch、MinIO 正常运行；
- `nexent-config` 日志中没有知识库创建或文档入库异常。

文档型知识库的文件入库是异步过程，复制成功后短时间内可能显示“文件在入库中”。

### 如何更换行业版本

重新执行部署脚本并指定新的 Profile：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path /opt/packages/official-agents.zip \
  --profiles medical,finance
```

脚本只追加或更新选中的官方仓库条目，不会删除未选中的 Profile，也不会删除用户已经复制到“我的智能体”中的 Agent。

## 13. 卸载说明

官方智能体部署脚本没有自动删除用户资源的操作。若需要下架官方智能体，应通过仓库管理流程处理官方仓库记录；不要直接删除租户知识库、Skill 或 MCP，因为这些资源可能已经被其他用户的 Agent 使用。
