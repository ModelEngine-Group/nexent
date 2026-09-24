# 🚀 官方智能体部署

本文介绍如何在 Nexent 主平台部署完成后，单独获取并同步官方智能体。

## 一、部署概述

官方智能体部署与 Nexent 主平台部署相互独立：

- Nexent 主安装只负责启动平台服务并准备官方资源挂载目录；
- 官方智能体部署脚本负责获取、筛选和复制指定行业的官方资源；
- 同步脚本负责将资源登记到智能体仓库；
- 部署阶段不会为租户创建知识库，也不会要求配置向量模型；
- 用户从智能体仓库复制官方智能体时，才会按需创建或复用知识库、Skill 和 MCP。

## 二、前置条件

执行官方智能体部署前，请确认：

1. Nexent 已经完成 Docker 或 Kubernetes 部署；
2. `nexent-config` 服务已经启动并可以正常访问数据库；
3. 执行脚本的机器可以访问 Nexent 项目目录；
4. 从 Agent Hub 获取资源时，机器已安装 Git；如果选中的资源包含 Git LFS 文件，还需要安装并配置 Git LFS；
5. 离线环境不需要 Git，但必须提前准备官方智能体目录或压缩包。

进入 Nexent 代码仓库根目录执行以下命令：

```bash
cd nexent
```

`deploy/deploy-official-agents.sh` 会自动完成资源复制和容器内同步，用户不需要手工执行 `git clone`、`docker cp` 或 `sync_official_agents.py`。

## 三、官方资源目录结构

部署脚本按照“Profile → Agent Bundle”的结构扫描资源。每个官方智能体 Bundle 的根目录必须包含一个 `agent.json`：

```text
official-agents/
├── general/
│   ├── document_writing_assistant/
│   │   ├── agent.json
│   │   ├── knowledge_base/
│   │   └── skills/
│   └── official_test/
│       └── agent.json
├── medical/
│   └── medical_assistant/
│       └── agent.json
└── finance/
    └── finance_assistant/
        └── agent.json
```

如果 Agent Hub 使用行业目录组织资源，例如：

```text
AgentsHub/
└── 行业智能体/
    ├── 医疗/
    └── 金融/
```

则使用 `--profile-root "行业智能体"` 指定 Profile 根目录，并使用实际目录名称作为 `--profiles` 参数。

## 四、从 Agent Hub 在线部署

默认仓库地址为：

```text
https://gitcode.com/ModelEngine/AgentsHub
```

默认分支为 `main`。例如，从 Hub 部署 `general` Profile：

```bash
bash deploy/deploy-official-agents.sh \
  --source hub \
  --ref main \
  --profiles general
```

如果 Hub 的 Profile 位于中文目录下，例如 `行业智能体/金融`：

```bash
bash deploy/deploy-official-agents.sh \
  --source hub \
  --ref main \
  --profile-root "行业智能体" \
  --profiles "金融"
```

一次部署多个 Profile 时，用逗号分隔：

```bash
bash deploy/deploy-official-agents.sh \
  --source hub \
  --ref main \
  --profile-root "行业智能体" \
  --profiles "医疗,金融"
```

### 4.1 使用其他 Hub 地址

可以通过环境变量覆盖默认仓库地址和分支：

```bash
export OFFICIAL_AGENTS_REPO_URL="https://gitcode.com/ModelEngine/AgentsHub"
export OFFICIAL_AGENTS_REPO_REF="main"

bash deploy/deploy-official-agents.sh \
  --source hub \
  --profiles general
```

脚本不会把 Git 凭证写入 Nexent 配置或日志。

### 4.2 Hub 下载范围

脚本不会把整个 Agent Hub 的工作区内容全部检出到部署目录：

1. 先以浅克隆方式获取指定 ref 的仓库元数据；
2. 根据 `--profile-root` 和 `--profiles` 设置稀疏检出路径；
3. 只对选中的 Profile 执行 Git LFS 下载；
4. 将选中的 Profile 复制到 Nexent 官方资源目录。

因此，未选择的行业 Profile 不会被复制到 Nexent，也不会触发其 LFS 文件下载。

## 五、从本地目录部署

联网机器或交付包已经准备好资源目录时，可以直接使用本地目录：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path /opt/agentshub/official-agents \
  --profiles general
```

Windows Git Bash 可以使用 Windows 路径或 `/c` 路径：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path "C:/Users/HAN/PycharmProjects/nexent/official-agents" \
  --profiles general
```

也可以使用 Git Bash 风格路径：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path "/c/Users/HAN/PycharmProjects/nexent/official-agents" \
  --profiles general
```

如果本地目录下还有一层行业目录，需要指定 `--profile-root`：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path /opt/agentshub \
  --profile-root "行业智能体" \
  --profiles "金融"
```

## 六、从本地压缩包部署

本地源也可以是 `.zip` 或 tar 压缩包。脚本会自动解压到临时目录，校验压缩包路径安全性，然后按与本地目录相同的流程扫描：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path /opt/packages/official-agents.zip \
  --profiles medical
```

压缩包内的目录层级必须与 `--profile-root` 和 `--profiles` 参数匹配。例如，压缩包内容为 `行业智能体/金融/...` 时，应执行：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path /opt/packages/agents.zip \
  --profile-root "行业智能体" \
  --profiles "金融"
```

本地目录和本地压缩包在部署语义上等价，区别只在于资源交付形式。

## 七、交互式部署

不传 `--source` 或 `--profiles` 时，脚本会交互式询问资源来源和 Profile：

```bash
bash deploy/deploy-official-agents.sh
```

脚本会依次完成：

1. 选择 Agent Hub 或本地目录/压缩包；
2. 扫描可用 Profile；
3. 选择一个或多个 Profile；
4. 校验每个 Profile 至少包含一个 `agent.json`；
5. 复制选中的资源；
6. 调用容器内同步脚本。

## 八、Docker 部署流程

Docker 模式下，脚本的内部流程如下：

```text
宿主机 deploy-official-agents.sh
    │
    ├─ 从 Hub 获取资源，或读取本地目录/压缩包
    ├─ 只筛选用户选择的 Profile
    ├─ 复制到 nexent-config:/mnt/nexent/official-agents/
    └─ docker exec nexent-config
         python backend/scripts/sync_official_agents.py
```

官方资源最终存放在 `nexent-config` 容器的：

```text
/mnt/nexent/official-agents/{profile}/{bundle}/
```

同步脚本读取已挂载的 `agent.json`、Skill、MCP 和原始文档，并将官方智能体登记到官方智能体仓库。它不会执行 Git 操作，也不会在部署阶段创建租户知识库。

部署成功时，终端应显示类似结果：

```text
Synchronized 3 official agent bundle(s)
Official Agent deployment completed for profiles: general
```

## 九、Kubernetes 部署

Kubernetes 环境使用相同的资源来源和 Profile 选择方式，并增加 `--kubernetes` 参数：

```bash
bash deploy/deploy-official-agents.sh \
  --source local \
  --path /opt/agentshub/official-agents \
  --profiles general \
  --kubernetes \
  --namespace nexent
```

执行前请确认：

- 当前 `kubectl` context 指向目标集群；
- `nexent-config` 对应的部署已就绪；
- 官方资源目录能够写入 Nexent 使用的工作目录或 PVC；
- `--namespace` 与 Nexent 实际命名空间一致。

## 十、部署完成后的用户安装

官方智能体同步完成后，用户可以在 **智能体仓库** 中复制官方智能体。

复制时：

- 用户需要选择当前租户可用的语言模型；
- 带有官方文档知识库的智能体，在需要创建知识库时选择向量模型；
- 如果同租户已有同名 Skill 或知识库，用户可以选择复用或创建副本；
- 创建完成的 Agent 属于当前用户，可继续编辑；
- 官方模板删除不会删除已经复制到租户中的用户副本。

因此，部署官方资源不等于把官方 Agent 自动安装到所有用户或所有租户。部署只发布官方模板，具体安装由用户从智能体仓库发起。

## 十一、验证部署结果

### 11.1 检查 Docker 容器中的资源

```bash
docker exec nexent-config \
  find /mnt/nexent/official-agents -name agent.json -print
```

检查同步脚本输出：

```bash
docker logs nexent-config --tail 200
```

### 11.2 检查页面

登录 Nexent 后：

1. 打开 **智能体仓库**；
2. 确认选中的 Profile 中的官方智能体出现；
3. 确认卡片显示“官方”标识；
4. 点击复制，确认可以看到模型选择和资源冲突处理选项。

## 十二、删除官方智能体

官方智能体删除功能仅用于删除官方模板，只有超级管理员可以执行。租户管理员、开发者和普通用户不能删除官方模板。

> ⚠️ **重要提示**：删除操作会移除官方智能体仓库条目、官方源 Agent 记录以及服务器上的官方 Bundle 文件。已经被用户复制到租户中的 Agent 副本不会被删除，也不会被回滚。

### 12.1 删除操作步骤

1. 使用超级管理员账号登录 Nexent。
2. 进入 **资源管理** 页面。
3. 打开 **智能体** 页签。
4. 点击 **管理官方智能体**。
5. 在官方智能体列表中找到要删除的模板。
6. 点击该模板对应的 **删除** 按钮。
7. 在确认弹窗中检查智能体名称和删除影响，确认后继续。

删除成功后，该官方智能体不会再出现在智能体仓库中，用户也不能继续从仓库复制新的实例。

### 12.2 删除范围

删除官方模板时，系统会清理以下内容：

| 内容 | 是否删除 | 说明 |
| --- | :---: | --- |
| 官方智能体仓库条目 | ✅ | 不再对用户展示和提供复制 |
| 官方源 Agent | ✅ | 删除官方保留租户中的源 Agent |
| 官方 Bundle 文件 | ✅ | 删除配置的官方资源目录中的对应文件或目录 |
| 已复制到租户的 Agent | ❌ | 保留用户副本及其编辑内容 |
| 用户租户中的知识库、Skill、MCP | ❌ | 不删除用户复制时创建或复用的资源 |

### 12.3 删除后的验证

删除后可以进行以下检查：

1. 刷新 **智能体仓库**，确认对应官方模板不再显示；
2. 使用超级管理员返回 **管理官方智能体**，确认模板已从列表中移除；
3. 对 Docker 部署检查官方 Bundle 文件是否已清理：

   ```bash
   docker exec nexent-config \
     find /mnt/nexent/official-agents -iname '*<bundle-name>*' -print
   ```

4. 如果用户之前已经复制过该 Agent，进入对应租户的 **我的智能体**，确认用户副本仍然存在。

不要直接删除数据库记录或手工删除容器文件。管理页面会同时处理仓库记录、源 Agent 和 Bundle 文件，避免出现数据库和文件状态不一致。

## 十三、重新部署或更新 Profile

更新 Agent Hub 中的官方资源后，可以重复执行相同命令：

```bash
bash deploy/deploy-official-agents.sh \
  --source hub \
  --ref main \
  --profile-root "行业智能体" \
  --profiles "金融"
```

重复部署会更新官方仓库模板，不会覆盖用户已经复制到租户中的 Agent。需要删除官方模板时，应通过超级管理员的官方智能体管理功能执行，避免直接删除容器内资源造成数据库和文件不一致。

## 十四、常见问题

### 14.1 `profile not found`

通常是 Profile 根目录层级不匹配。检查：

- `--path` 是否指向包含 Profile 的目录；
- 是否需要增加 `--profile-root`；
- `--profiles` 是否使用实际目录名；
- 中文目录名是否使用引号包裹。

### 14.2 `Synchronized 0 official agent bundle(s)`

检查选中的 Profile 下是否存在以 Bundle 为根目录的 `agent.json`。如果 `agent.json` 位于更深层目录，说明资源目录结构或 `--profile-root` 配置不正确。

### 14.3 `duplicate official agent bundle`

说明同一个 Profile 扫描到了多个同名 Bundle，常见原因是上一次复制留下了嵌套目录。清理资源源目录中的重复 Bundle 后重新部署。脚本在复制选中 Profile 前会清理目标 Profile，避免旧的嵌套目录继续参与同步。

### 14.4 Git LFS 下载失败

如果提示 `smudge filter lfs failed`、`Access forbidden` 或 `project lfs not enabled`：

1. 检查远端仓库是否启用了 Git LFS；
2. 检查当前账号是否有 LFS 对象访问权限；
3. 在有权限的机器上准备完整本地目录或压缩包；
4. 在目标环境改用 `--source local` 部署。

### 14.5 `Remote branch main not found`

先检查远端实际分支：

```bash
git ls-remote --heads https://gitcode.com/ModelEngine/AgentsHub
```

然后使用实际存在的 ref：

```bash
bash deploy/deploy-official-agents.sh \
  --source hub \
  --ref main \
  --profiles general
```

### 14.6 页面没有显示官方智能体

依次检查：

1. 脚本是否输出了大于 0 的同步数量；
2. `nexent-config` 中是否存在目标 Profile 的 `agent.json`；
3. 容器日志中是否有 Bundle 校验或数据库错误；
4. 浏览器是否使用 `Ctrl + F5` 强制刷新；
5. 是否登录到了正确的租户。
