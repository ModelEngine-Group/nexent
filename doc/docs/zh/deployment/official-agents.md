# 🚀 官方智能体部署

本文介绍如何在 Nexent 主平台部署完成后，从 Nexent 仓库内置目录安装官方智能体。

官方智能体部署与 Nexent 主平台部署解耦。Nexent 平台先完成安装，随后执行官方智能体部署脚本，用户即可在智能体仓库中看到官方智能体模板。

## 一、部署前提

执行前请确认：

1. Nexent 已经完成 Docker 或 Kubernetes 部署；
2. `nexent-config` 服务已经启动并完成数据库初始化；
3. 当前代码仓库包含 `deploy/docker/assets/official-agents` 目录；
4. Docker 部署使用 Git Bash 或 WSL 执行脚本；
5. Kubernetes 部署使用能够访问目标集群的终端执行脚本。

官方智能体资源不需要额外配置环境变量，也不需要用户手工执行 Git、`docker cp` 或同步接口。

## 二、官方智能体目录结构

脚本固定读取仓库中的以下目录：

```text
deploy/docker/assets/official-agents/
├── general/
│   └── document_writing_assistant/
│       ├── agent.json
│       ├── skills/
│       └── kb/
├── medical/
│   └── medical_assistant/
│       └── agent.json
└── finance/
    └── finance_assistant/
        └── agent.json
```

- `general`、`medical` 和 `finance` 是官方智能体 Profile；
- 每个 Profile 下可以包含多个官方智能体 Bundle；
- 每个 Bundle 的根目录必须包含 `agent.json`；
- `skills/` 保存该智能体依赖的 Skill；
- `kb/` 保存官方知识库的原始文档。

部署脚本只扫描 `official-agents` 下的一级目录作为 Profile，不读取其他目录。

## 三、交互式部署

在仓库根目录执行：

```bash
bash deploy/deploy-official-agents.sh
```

脚本会自动扫描可用 Profile，并显示选择菜单：

```text
Available official Agent profiles:
  1) finance
  2) general
  3) medical

Select profiles (comma-separated numbers, or all):
```

输入单个 Profile：

```text
2
```

输入多个 Profile：

```text
2,3
```

安装全部 Profile：

```text
all
```

脚本会校验编号、目录和 `agent.json`。选择无效时会直接提示错误，不会执行复制或同步操作。

## 四、Docker 部署流程

Docker 部署时，脚本执行以下操作：

```text
扫描 deploy/docker/assets/official-agents
        ↓
交互选择 Profile
        ↓
复制选中的 Profile 到 nexent-config
        ↓
/mnt/nexent/official-agents/{profile}/
        ↓
调用容器内官方智能体同步接口
        ↓
写入 system 租户的官方智能体仓库
```

成功时会显示：

```text
Synchronized 3 official Agent bundle(s)
Official Agent deployment completed for profiles: general,medical
```

部署阶段只登记官方智能体模板，不为普通租户创建知识库，也不要求配置向量模型。

## 五、Kubernetes 部署

Kubernetes 环境执行：

```bash
bash deploy/deploy-official-agents.sh --kubernetes
```

默认使用 `nexent` 命名空间。如需使用其他命名空间：

```bash
bash deploy/deploy-official-agents.sh \
  --kubernetes \
  --namespace custom-namespace
```

Kubernetes 部署要求 `nexent-config` 使用已经配置好的持久化目录。脚本会将选中的 Profile 复制到：

```text
$NEXENT_USER_DIR/official-agents/
```

如果未设置 `NEXENT_USER_DIR`，默认使用：

```text
$HOME/nexent/official-agents/
```

## 六、部署完成后的用户操作

部署完成后，官方智能体会出现在“智能体仓库”的官方列表中。

用户需要：

1. 打开 **智能体仓库**；
2. 找到需要使用的官方智能体；
3. 点击 **复制**；
4. 根据页面提示选择模型、知识库和 Skill 配置；
5. 完成复制。

复制时：

- 当前租户内已经存在的知识库、Skill 和 MCP 可以复用；
- 不存在的依赖会按用户选择创建；
- Agent 本身属于发起复制的用户；
- 同租户其他用户可以继续复制同一个官方模板；
- 官方模板不会直接自动安装到所有租户。

## 七、部署验证

### 1. 查看容器内资源

Docker 环境可以执行：

```bash
docker exec nexent-config find /mnt/nexent/official-agents -name agent.json -print
```

### 2. 查看智能体仓库

登录 Nexent 后：

1. 打开 **智能体仓库**；
2. 切换到官方智能体列表；
3. 确认已选择的 Profile 中的模板出现；
4. 点击复制，确认能够进入配置流程。

## 八、删除官方智能体

删除官方模板需要超级管理员权限：

1. 登录超级管理员账号；
2. 进入 **资源管理**；
3. 打开 **智能体** 页面；
4. 点击 **管理官方智能体**；
5. 选择需要删除的官方模板；
6. 点击 **删除** 并确认。

删除操作会删除官方智能体仓库条目、system 租户中的官方源 Agent 和服务器上的对应官方 Bundle 文件。已经被用户复制到租户中的 Agent 副本不会被删除。

## 九、常见问题

### `official Agent directory not found`

确认当前命令是在 Nexent 仓库根目录执行，并确认以下目录存在：

```text
deploy/docker/assets/official-agents
```

### `no official Agent profiles found`

确认 `official-agents` 下至少存在一个 Profile 子目录，例如：

```text
deploy/docker/assets/official-agents/general
```

### `profile has no agent.json`

确认目录结构为：

```text
official-agents/<profile>/<agent>/agent.json
```

### `Synchronized 0 official Agent bundle(s)`

常见原因：

- 选择的 Profile 不包含有效的 `agent.json`；
- 资源目录没有复制到 `nexent-config`；
- `nexent-config` 中的官方资源目录为空；
- 当前服务使用的镜像没有包含最新同步代码。

### 复制官方智能体时没有创建知识库

官方智能体部署阶段只发布模板。知识库创建发生在用户从智能体仓库复制官方智能体时。如果首次复制包含知识库的官方智能体，请确认租户已经配置可用的向量模型。

## 十、重新部署或更新官方智能体

更新 `deploy/docker/assets/official-agents` 中的 Bundle 后，重新执行：

```bash
bash deploy/deploy-official-agents.sh
```

脚本会重新选择 Profile，并更新官方智能体仓库中的模板。已经复制到用户租户中的 Agent 副本不会被覆盖。
