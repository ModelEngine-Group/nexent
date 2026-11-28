# Kubernetes 安装部署

## 环境准备

### 🎯 系统要求

| 资源 | 最低要求 | 推荐配置 |
|----------|---------|-------------|
| **CPU**  | 4 核 | 8 核 |
| **内存**  | 16 GiB | 64 GiB |
| **磁盘** | 100 GiB | 200 GiB |
| **架构** | x86_64 / ARM64 | 与节点架构匹配的镜像 |
| **软件** | Kubernetes 1.24+、Helm 3+、Bash 4+，kubectl 已配置 | Kubernetes 1.28+ |

> **💡 注意**：推荐配置适合完整部署。实际资源需求还取决于副本数、知识库规模和并发智能体数量，生产环境应根据压测结果设置 requests 与 limits。

### 准备 Kubernetes 集群

- **已有集群**：向集群管理员或云服务商获取可用于部署 Nexent 的 kubeconfig，在部署机上配置集群访问。
- **本机单节点试用**：按操作系统选择驱动，安装 minikube 并启动集群。创建虚拟节点时，为节点分配满足上表要求的 CPU、内存和磁盘。[minikube 官方入门指南](https://minikube.sigs.k8s.io/docs/start/)
- **自建 Linux 集群**：在节点上准备支持 CRI 的容器运行时（如 containerd），安装 kubeadm 和 kubelet。随后初始化控制平面、安装 Pod 网络插件，并按需加入工作节点。[安装 kubeadm](https://kubernetes.io/zh-cn/docs/setup/production-environment/tools/kubeadm/install-kubeadm/) · [使用 kubeadm 创建集群](https://kubernetes.io/zh-cn/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/)

### 安装管理工具并验证环境

在运行 Nexent 部署脚本的机器上准备 Bash 4 或更高版本，并安装与集群版本兼容的 kubectl 和 Helm。kubectl 用于访问集群，Helm 用于安装 Nexent 的 Chart。[Kubernetes 官方工具安装指南](https://kubernetes.io/zh-cn/docs/tasks/tools/) · [Helm 官方安装指南](https://helm.sh/zh/docs/intro/install/)

```bash
bash --version
kubectl version --client
helm version --short
kubectl config current-context
kubectl cluster-info
kubectl get nodes
kubectl get storageclass
```

确认当前上下文是目标集群，API Server 可访问，部署所用节点的状态为 `Ready`。全新安装默认通过集群的默认 StorageClass 动态创建持久卷，共享存储需要支持 `ReadWriteMany`（RWX）。如果集群没有合适的默认类，可通过 `--storage-class <存储类名称>` 指定。单节点测试可使用 `--persistence-mode local`。其他存储选项见[数据持久化](#数据持久化)。

## 🚀 快速开始

- [在线部署](#在线部署)
- [离线部署](#离线部署)

### 在线部署

#### 1. 克隆并进入目录

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent
```

首次安装到多节点集群时，先选择支持跨节点读写的存储。如果使用默认启用的本地轨迹采集，可将 `deploy/env/.env.example` 复制为新的 `deploy/env/.env`，在首次启动前设置 `TRAJECTORY_STORAGE_MODE=shared_directory`。存储要求和三副本安装命令见[部署多个 Runtime 副本](#部署多个-runtime-副本)。

#### 2. 部署

运行部署脚本：

```bash
bash deploy.sh k8s
```

默认流程在 `nexent` 命名空间安装两个 Helm release。脚本先安装 `nexent-infrastructure`（Elasticsearch、PostgreSQL、Redis、MinIO），等待四个组件就绪并初始化 Elasticsearch API Key，再部署应用 release `nexent`。首次安装应用时，脚本运行初始化 Job，执行数据库迁移并初始化系统智能体，然后启动业务服务。部署账号需要能在该命名空间管理工作负载和 Job，并能通过 `kubectl exec` 访问 PostgreSQL 和 Elasticsearch Pod。按需选择以下一种部署范围。

```bash
bash deploy.sh k8s --release-scope all
bash deploy.sh k8s --release-scope infrastructure
bash deploy.sh k8s --release-scope nexent
```

仅部署 `nexent` 时，脚本会先确认基础 release 存在且四个组件均已就绪；仅卸载基础 release 时，如果 `nexent` 仍存在则拒绝执行。检测到旧版单一 `nexent` release 仍管理基础组件时，脚本会直接报错；当前版本只支持全新双 release 部署，不执行自动迁移。

执行此命令后，系统会通过 Bash TUI 选择配置选项。可使用方向键或 `j/k` 移动，空格切换多选项，回车确认，`b`/Backspace 返回上一步，`q` 退出。

**组件组合**

| 选项 | 默认状态 | 部署内容 |
| --- | --- | --- |
| `infrastructure` | 必选 | Elasticsearch、PostgreSQL、Redis、MinIO |
| `application` | 选中 | Gateway、配置管理服务、Runtime、MCP、Web 和运维服务（Ops） |
| `data-process` | 选中 | 数据处理服务 |
| `terminal` | 可选 | OpenSSH 终端 |
| `monitoring` | 可选 | 向选定的观测平台导出数据 |

`application` 还会准备智能体沙箱镜像信息。Runtime 使用共享工作区处理上传文件和生成文件；需要保留的产物会同步到 MinIO。

**端口策略**

默认的 `development` 策略通过 NodePort 暴露 Web、Gateway、Ops 及部分内部服务，方便调试。`production` 策略将配置管理、Runtime 和基础设施等内部服务改为 ClusterIP。Web、Gateway 和 Ops 仍有 NodePort，访问地址见下文的端口表。

**镜像来源**

`general` 使用标准公开镜像仓库，是默认选项。`mainland` 使用中国大陆镜像源。`local-latest` 使用本地 `latest` 应用镜像，未指定私有仓库前缀时使用 `Never` 拉取策略，需要将镜像预先导入可能运行这些应用 Pod 的节点。

Kubernetes 使用与 Docker 相同的 `deploy/env/.env`。每次部署前，脚本会保留已有值、注释和旧版变量，并追加当前 `deploy/env/.env.example` 新增的变量。如果 `.env` 不存在，会优先复用旧版 `docker/.env`，再回退到当前模板；部署时必须存在可读的 `.env.example`。

使用 `bash deploy.sh k8s --defaults` 可跳过交互界面。脚本从 `deploy/k8s/deploy.options` 复用组件和存储等部署选项，缺少的选项采用内置默认值。应用版本取自当前仓库或部署包的 `VERSION`，也可通过 `--version` 显式指定。旧选项文件中的应用版本会被忽略。

#### ⚠️ 重要提示

1️⃣ **首次部署 v1.8.0 及以上版本时**，系统会创建 `suadmin@nexent.com` 超级管理员账号，默认密码为 `Nexent@123`，无需交互输入，创建成功后会在终端显示。可在首次部署前通过 `deploy/env/.env` 中的 `NEXENT_SUPER_ADMIN_PASSWORD` 覆盖默认值，非交互创建时终端会显示实际使用的密码。使用离线部署包并显式指定 `--config` 时，部署脚本会要求输入并确认密码，并以本次输入为准；手动输入的密码不会在终端显示。

2️⃣ 历史账号迁移、管理员账号异常和数据恢复请查阅[统一迁移与排障手册](https://github.com/ModelEngine-Group/nexent/blob/develop/deploy/sql/tools/supabase_to_postgres/README.md)。保留原账号 ID 和租户归属，按手册恢复一致的数据。

### 离线部署

目标集群无法访问公网镜像仓库时，可从 GitHub Actions 获取已经打包好的离线部署包：

1. 登录 GitHub，打开 [Build Offline Deployment Package](https://github.com/ModelEngine-Group/nexent/actions/workflows/build-offline-package.yml)。
2. 选择目标版本对应的成功运行记录，在 **Artifacts** 中下载与集群节点架构匹配的 `nexent-<version>-<platform>.zip`。
3. 将压缩包复制到可以访问目标集群的管理节点并解压。工作流产物默认保留 30 天；产物过期时，可联系维护者重新运行工作流。

将以下文件名替换为实际下载的离线包名称，再解压并进入部署目录。

```bash
unzip 'nexent-<version>-amd64.zip' -d nexent
cd nexent
```

单节点且以 Docker 作为容器运行时的集群可直接加载并部署：

```bash
bash deploy.sh --load-images k8s
```

如果管理节点上保留了此前已部署的离线包，可通过 `--reuse-from` 复用其中的环境配置和 Kubernetes 部署选项：

```bash
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --load-images \
  k8s
```

指定目录必须是已解压的旧部署包根目录，并包含 `deploy/env/.env`。脚本会保留旧环境值，补充当前模板中的新变量，并复用已有的 `monitoring.env` 和 Kubernetes 部署选项。复用旧配置时，应在新包目录运行命令，核对终端显示的应用版本是否与包内镜像一致。`--reuse-from` 可与 `--config`、`--defaults` 或 `--push-images` 组合使用。

其他单节点集群和多节点集群应将镜像推送到集群可访问的内部仓库，或使用对应容器运行时的工具，将镜像导入所有可能运行 Nexent Pod 的节点：

```bash
bash deploy.sh \
  --push-images \
  --image-registry-prefix registry.example.com/nexent \
  k8s
```

离线包中的 `manifest.yaml` 列出了组件和镜像。部署入口默认复用已有选项或使用内置默认值，添加 `--config` 可重新选择。启用可选组件前，请确认其镜像可以在目标集群中拉取或已导入节点。

### 访问您的安装

从部署机检查 release、应用和实际分配的 NodePort。默认安装完成后，两个 release 均应为 `deployed`，所选应用的 `READY` 列应达到期望副本数。

```bash
helm list -n nexent
kubectl get deployments,svc -n nexent
```

Web 默认通过 `http://节点地址:30000` 提供服务。本机临时验证时，可以运行以下命令，并在同一台机器上打开 `http://localhost:3000`。

```bash
kubectl -n nexent port-forward svc/nexent-web 3000:3000
```

**从其他机器登录时请使用 HTTPS**。Web 默认使用带 `Secure` 属性的登录 Cookie，浏览器通过普通 HTTP 访问远端节点时，可能无法保持登录状态。已有 HTTPS 入口时可直接使用其域名。也可以在部署时启用内置 Nginx，默认 HTTPS NodePort 为 `31000`。以下示例使用已有证书，将两个路径替换为部署机上的 PEM 证书和私钥文件，再访问 `https://证书中的域名:31000`。

```bash
bash deploy.sh k8s --defaults --https-mode custom \
  --https-cert-file /path/to/fullchain.pem --https-key-file /path/to/private.key
```

使用 `suadmin@nexent.com` 和首次部署时设置的密码登录，在 **租户资源** 中创建租户和租户管理员。再使用租户管理员账号登录并配置模型或智能体，详见[用户指南](../user-guide/home-page)。

## 🏗️ 服务架构

Nexent 采用微服务架构，通过 Helm Chart 进行部署：

**应用服务**

| 服务 | 描述 | 默认端口 |
|---------|-------------|--------------|
| nexent-config | 配置与管理 API | 5010 |
| nexent-runtime | 智能体运行时 API | 5014 |
| nexent-mcp | MCP 管理与工具服务 | 5011 |
| nexent-gateway | Gateway，提供北向 API 和 Web 请求入口 | 5013 |
| nexent-ops | 运维 API，提供运行指标和历史轨迹查询 | 5016 |
| nexent-web | Web 前端 | 3000 |
| nexent-data-process | 数据处理服务 | 5012 |

**基础设施服务**

| 服务 | 描述 |
|---------|-------------|
| nexent-elasticsearch | 搜索引擎和索引服务 |
| nexent-postgresql | 关系型数据库 |
| nexent-redis | 缓存、分布式锁和任务消息代理 |
| nexent-minio | S3 兼容对象存储 |

**可选服务**

| 服务 | 描述 |
|---------|-------------|
| nexent-openssh-server | AI 智能体 SSH 终端 |
| nexent-otel-collector | 启用 `monitoring` 时部署的 OpenTelemetry Collector |
| nexent-nginx | 启用内置 HTTPS 时部署的反向代理 |

## 🔌 端口映射

| 服务 | 内部端口 | NodePort | 描述 |
|---------|---------------|----------|-------------|
| Web 界面 | 3000 | 30000 | 主应用程序访问 |
| HTTPS 入口 | 3000 | 31000 | 启用内置 HTTPS 时，由 Nginx 接收 TLS 请求 |
| Gateway | 5013 | 30013 | 北向 API |
| Ops | 5016 | 30016 | 运维服务 |
| SSH 服务器 | 22 | 30022 | 启用终端组件时使用 |

内部服务通信使用 Kubernetes 内部 DNS（例如 `http://nexent-config:5010`）。

## 数据持久化

在仓库根目录运行部署命令，根据存储条件选择以下一种模式。

| 场景 | 部署方式 |
| --- | --- |
| 集群已配置支持 RWX 的默认 StorageClass | 直接运行 `bash deploy.sh k8s --defaults`。全新安装使用 `dynamic`，Kubernetes 按 PVC 申请动态创建卷。 |
| 使用指定的动态 StorageClass | 运行 `bash deploy.sh k8s --defaults --persistence-mode dynamic --storage-class my-rwx-storage`，将示例名称替换为集群中的存储类。 |
| 单节点使用宿主机目录 | 运行 `bash deploy.sh k8s --defaults --persistence-mode local`。Chart 创建使用 `hostPath` 的静态 PV。 |
| 已准备好各组件使用的 PVC | 运行 `bash deploy.sh k8s --defaults --persistence-mode existing`，并确保 PVC 名称和访问模式与部署配置一致。 |

再次部署时，显式传入的 `--persistence-mode` 优先于 `deploy/k8s/deploy.options` 中的存储模式。已有部署要沿用原存储配置，以便服务继续访问原有数据。直接使用 Helm 升级静态卷部署时，也要保留原来的 `local` 配置。

下表列出 `local` 模式使用的默认宿主机路径。

| 数据类型 | PersistentVolume | 默认宿主机路径 |
|-----------|------------------|-------------------|
| Elasticsearch | nexent-elasticsearch-pv | `/var/lib/nexent-data/nexent-elasticsearch` |
| PostgreSQL | nexent-postgresql-pv | `/var/lib/nexent-data/nexent-postgresql` |
| Redis | nexent-redis-pv | `/var/lib/nexent-data/nexent-redis` |
| MinIO | nexent-minio-pv | `/var/lib/nexent-data/nexent-minio` |
| 共享工作区 | nexent-workspace-pv | `/var/lib/nexent` |
| 共享技能目录 | nexent-skills-pv | `/var/lib/nexent-data/skills` |
| 记忆插件 | nexent-memory-plugins-pv | `/var/lib/nexent-data/memory-provider-plugins` |
| 服务日志 | nexent-logs-pv | `/var/lib/nexent-data/logs` |
| 本地轨迹 | nexent-trajectory-pv | `/var/lib/nexent-data/trajectory` |
| Web 项目配置 | nexent-project-config-pv | `/var/lib/nexent-data/project-config` |

`nexent-workspace` 默认申请 10 GiB 的 `ReadWriteMany` 存储，供应用服务交换一次运行中的输入和输出。多节点集群需要确认不同节点上的 Pod 都能读写同一份文件。

### 部署多个 Runtime 副本

Runtime 默认有 1 个副本。需要增加并发处理能力时，可以使用 `--runtime-replicas` 指定固定副本数。以下首次安装示例使用 3 个副本，请把 `my-rwx-storage` 替换为集群中支持多节点读写的 StorageClass 名称。跨节点采集本地轨迹时，还需在首次启动前按下文[监控配置](#监控配置)设置轨迹存储模式。

```bash
bash deploy.sh k8s --defaults --runtime-replicas 3 \
  --persistence-mode dynamic --storage-class my-rwx-storage
kubectl -n nexent rollout status deployment/nexent-runtime
kubectl -n nexent get deployment nexent-runtime
```

多副本可以使用支持 RWX 的动态存储类，或在 `existing` 模式下使用预建共享 PVC。默认 StorageClass 支持 RWX 时，可省略示例中的 `--storage-class`。部署账号需要能读取以下五个 PVC 及其绑定的 PV。脚本会检查两者的状态均为 `Bound`、访问模式包含 `ReadWriteMany`、卷模式为 `Filesystem`，并拒绝使用 `spec.local` 的 PV。

| 共享目录 | 默认 PVC |
| --- | --- |
| 工作区、技能、日志 | `nexent-workspace`、`nexent-skills`、`nexent-logs` |
| 记忆插件、轨迹 | `nexent-memory-plugins`、`nexent-trajectory` |

已有部署调整副本数时，沿用原存储配置，在没有运行中任务的维护窗口执行 `bash deploy.sh k8s --defaults --release-scope nexent --runtime-replicas 3`。常规部署会暂停原有业务 Pod，完成初始化后再按新配置启动。Runtime 使用 `Recreate` 更新策略，更新期间可能短暂不可用。要改回单副本，将数值设为 `1`。

已初始化且正常运行的应用，如果本次仅调整副本数，可在同一命令中添加 `--direct-upgrade`。该方式跳过整体暂停和初始化 Job。首次安装、已暂停的应用、需要重新初始化系统智能体或包含不兼容数据库变更的升级，请使用常规部署流程。

### 使用 Kubernetes SYSTEM 沙箱

Runtime 的副本数和沙箱的运行方式可以分别配置。默认沙箱提供方为 `docker`。如果希望使用集群 Pod 执行智能体的 SYSTEM 沙箱任务，需要先确认目标集群的 CNI 能实际阻断 NetworkPolicy 禁止的连接，并确保集群节点能获取沙箱镜像。

在 `deploy/k8s/helm/nexent/values.yaml` 已有的 `global` 配置块中，将 `sandboxProvider` 设为 `kubernetes`。验证网络策略生效后，将 `sandboxNetworkPolicyVerified` 设为 `true`，再运行部署脚本。工作区使用共享 RWX 存储。仅在单节点开发环境使用本地工作区时，可显式设置 `global.sandboxSingleNodeDevelopment: true`。多副本仍需满足上一节的存储要求。

每个 Runtime Pod 首次执行需要 SYSTEM 沙箱的任务时，会创建自己的沙箱 Pod。运行一次使用该沙箱的智能体后，可以查看实际创建的 Pod。

```bash
kubectl -n nexent get pods -l nexent.ai/sandbox=system
```

### 卸载 Kubernetes 部署

在仓库根目录执行 `bash uninstall.sh k8s`，脚本会依次卸载应用和基础设施 release。交互模式会询问是否删除动态 PVC，默认保留。以下命令显式保留动态 PVC、命名空间和本地数据。

```bash
bash uninstall.sh k8s --delete-pvc false --keep-namespace --keep-local-data
```

只卸载应用时添加 `--release-scope nexent`。单独卸载基础设施时使用 `--release-scope infrastructure`，并先确认应用 release 已卸载。

| 需要处理的资源 | 参数与影响 |
| --- | --- |
| 动态 PVC | `--delete-pvc false` 默认保留所选 release 的动态 PVC，并保留命名空间，即使使用 `delete` 或 `delete-all`。如果旧 release 的 Helm 清单缺少 PVC 保留策略，脚本会停止。先使用当前 Chart 按原存储配置升级该 release，再卸载。 |
| 已确认可删除的动态 PVC | `bash uninstall.sh k8s --delete-pvc true --keep-namespace` 会删除所选 release 的动态 PVC。底层卷数据由所绑定 PV 的回收策略决定，`Delete` 可能同时删除数据。 |
| 本地 hostPath 数据 | `local` 模式下，`--delete-local-data true` 删除脚本管理的宿主机数据目录，`--keep-local-data` 保留目录。`delete-all` 默认请求删除命名空间和本地数据。 |

若需保留预先创建的 PVC 或同一命名空间内的其他资源，请显式使用 `--keep-namespace`。兼容参数 `--delete-data` 和 `--delete-volumes` 控制 Helm 卸载失败后的清理行为。动态 PVC 的处理由 `--delete-pvc` 控制。

## 🔧 部署命令

```bash
# 交互式部署
bash deploy.sh k8s

# 仅升级基础或应用 release
bash deploy.sh k8s --release-scope infrastructure
bash deploy.sh k8s --release-scope nexent

# 非交互式部署默认组件
bash deploy.sh k8s --defaults --components infrastructure,application,data-process --port-policy development --image-source general

# 部署应用、数据处理和终端工具
bash deploy.sh k8s --components infrastructure,application,data-process,terminal

# 使用中国大陆镜像源部署
bash deploy.sh k8s --image-source mainland

# 使用本地 latest 镜像
bash deploy.sh k8s --image-source local-latest

# 使用 --sc 简写指定 StorageClass
bash deploy.sh k8s --persistence-mode dynamic --sc fast-storage
```

## 🔧 高级配置

### 使用上传的 MCP 镜像

需要从页面上传自定义 MCP 镜像时，先将镜像推送到集群可访问的仓库，或预加载到所有可能运行 MCP Pod 的节点。在 `deploy/env/.env` 中设置 `ENABLE_UPLOAD_IMAGE=true`，并用 `NEXENT_MCP_KUBERNETES_PRELOADED_IMAGES` 登记原始 tar 文件的 SHA-256 与镜像引用。更新部署后，Config 服务使用该映射创建 MCP Pod。配置示例见 [MCP 仓库](../user-guide/resource-repository/mcp-repository#在-kubernetes-中上传镜像)。

### 监控配置

#### 在可观测中心查看本地轨迹

使用安装脚本部署 `application` 时，默认启用本地轨迹采集。脚本读取 `deploy/env/.env` 中的 `LOCAL_FILE_MONITORING_ENABLED`（默认 `true`），并在启用采集时将 `TRAJECTORY_READ_ENABLED=true` 写入 `deploy/env/monitoring.env`。使用内置可观测中心时，保留默认组件选择即可。

1. 检查 Runtime、Ops 是否就绪，并确认轨迹 PVC 处于 `Bound` 状态。默认命名空间为 `nexent`。

   ```bash
   kubectl -n nexent get deployment nexent-runtime nexent-ops
   kubectl -n nexent get pvc nexent-trajectory
   ```

2. 确认 Config、Runtime 和 Ops 挂载同一份轨迹存储。默认容器路径为 `/mnt/nexent-data/trajectory`。多节点部署应在首次采集前在 `deploy/env/.env` 设置 `TRAJECTORY_STORAGE_MODE=shared_directory`，并使用支持跨节点文件锁和原子替换的共享文件系统。已有轨迹目录会校验首次登记的存储模式，从单节点迁移时需要同时规划数据迁移。
3. 完成一轮智能体对话并复制会话 ID，用有页面权限的运维管理员或超级管理员账号到 **可观测中心** 查询，确认能打开该轮的调用时间线。详见[可观测中心](../user-guide/observability)。

如需停止采集新对话并保留历史查询，在 `deploy/env/.env` 中设置 `LOCAL_FILE_MONITORING_ENABLED=false`，在 `deploy/env/monitoring.env` 中保留 `TRAJECTORY_READ_ENABLED=true`，再用原部署选项重新部署应用。直接管理 Helm release 时，对应的值为 `global.monitoring.localFileEnabled: false` 和 `global.monitoring.trajectoryReadEnabled: true`。

#### 向第三方平台导出轨迹

需要同时向第三方平台上报时，添加 `monitoring` 组件并指定目标。脚本会生成 Helm 配置并安装 Collector，本地采集仍由自己的开关控制。例如，以下命令在默认组件的基础上添加 Phoenix。

```bash
bash deploy.sh k8s --components infrastructure,application,data-process,monitoring --monitoring-provider phoenix
```

| 目标 | 部署后的访问方式 |
| --- | --- |
| `otlp` | 启动 OpenTelemetry Collector，默认通过调试导出器输出到 Collector 日志。 |
| `phoenix` | 部署 Phoenix，通过可达节点的 `30006` 端口打开面板。 |
| `langfuse` | 部署 Langfuse，通过可达节点的 `30001` 端口打开面板。 |
| `langsmith` | 发送到托管的 LangSmith。部署前在 `deploy/env/monitoring.env` 配置 `LANGSMITH_API_KEY`，项目名可用 `LANGSMITH_PROJECT` 指定。 |

在 `deploy/env/monitoring.env` 中可以用 `K8S_PHOENIX_NODE_PORT` 或 `K8S_LANGFUSE_NODE_PORT` 修改面板的 NodePort。远程访问时，将 `MONITORING_DASHBOARD_URL` 设置为用户浏览器可访问的地址。使用 Langfuse 时也要核对 `K8S_LANGFUSE_NEXTAUTH_URL`。部署后可运行 `kubectl -n nexent logs deployment/nexent-otel-collector` 查看上报情况。

### OAuth 登录配置

OAuth 登录使用 Nexent 本地账号。通过安装脚本部署时，在 `deploy/env/.env` 中填写服务商提供的凭据，并将回调地址设为用户浏览器可访问的 Web 地址。以下是 GitHub 登录示例。

```dotenv
OAUTH_CALLBACK_BASE_URL=https://nexent.example.com
GITHUB_OAUTH_CLIENT_ID=your_github_client_id
GITHUB_OAUTH_CLIENT_SECRET=your_github_client_secret
OAUTH_LOGIN_MODE=button
```

保存后按原选项重新部署应用。自行管理 Helm release 时，可参考下表配置对应的 values。

| Values | 对应环境变量 | 说明 |
|--------|--------------|------|
| `nexent-common.config.oauth.callbackBaseUrl` | `OAUTH_CALLBACK_BASE_URL` | Web 入口地址，回调路径会自动拼接 |
| `nexent-common.config.oauth.githubClientId` | `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth Client ID |
| `nexent-common.config.oauth.githubClientSecret` | `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth Client Secret |
| `nexent-common.config.oauth.gdeUrl` | `GDE_URL` | GDE OAuth 服务地址 |
| `nexent-common.config.oauth.gdeClientId` | `GDE_OAUTH_CLIENT_ID` | GDE OAuth Client ID |
| `nexent-common.config.oauth.gdeClientSecret` | `GDE_OAUTH_CLIENT_SECRET` | GDE OAuth Client Secret |
| `nexent-common.config.oauth.enableWechat` | `ENABLE_WECHAT_OAUTH` | 是否启用 WeChat OAuth |
| `nexent-common.config.oauth.wechatClientId` | `WECHAT_OAUTH_APP_ID` | WeChat App ID |
| `nexent-common.config.oauth.wechatClientSecret` | `WECHAT_OAUTH_APP_SECRET` | WeChat App Secret |
| `nexent-common.config.oauth.sslVerify` | `OAUTH_SSL_VERIFY` | 访问 OAuth provider 时是否校验证书 |
| `nexent-common.config.oauth.caBundle` | `OAUTH_CA_BUNDLE` | 自定义 CA bundle 路径 |
| `nexent-common.config.oauth.loginMode` | `OAUTH_LOGIN_MODE` | `disabled`、`button` 或 `force` |

`loginMode` 默认为 `button`。`force` 模式下，没有可用 Provider 时禁用 OAuth，同时启用多个 Provider 时回退到登录按钮；CAS `force` 模式优先于 OAuth 自动登录。

Provider 回调地址：

| Provider | 回调地址 |
|----------|----------|
| GitHub | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=github` |
| GDE | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=gde` |
| WeChat | `{OAUTH_CALLBACK_BASE_URL}/api/user/oauth/callback?provider=wechat` |

本地 NodePort 默认回调示例为 `http://localhost:30000/api/user/oauth/callback?provider=github`。生产环境应改为公网 HTTPS 域名，并在 OAuth provider 控制台中登记相同地址。

### CAS 登录配置

CAS 单点登录使用 Nexent 本地账号。通过安装脚本部署时，在 `deploy/env/.env` 中填写 CAS 服务地址和用户浏览器可访问的 Nexent Web 地址，两个地址均省略末尾的 `/`。

```dotenv
CAS_ENABLED=true
CAS_SERVER_URL=https://cas.example.com/cas
CAS_CALLBACK_BASE_URL=https://nexent.example.com
CAS_LOGIN_MODE=force
CAS_LOGOUT_URL=/logout
```

保存后按原选项重新部署应用。自行管理 Helm release 时，可参考下表配置对应的 values。

| Values | 对应环境变量 | 说明 |
|--------|--------------|------|
| `nexent-common.config.cas.enabled` | `CAS_ENABLED` | 是否启用 CAS |
| `nexent-common.config.cas.serverUrl` | `CAS_SERVER_URL` | CAS Server 根地址 |
| `nexent-common.config.cas.validatePath` | `CAS_VALIDATE_PATH` | serviceValidate 路径，默认 `/p3/serviceValidate` |
| `nexent-common.config.cas.callbackBaseUrl` | `CAS_CALLBACK_BASE_URL` | Web 入口地址，CAS 回调路径会自动拼接 |
| `nexent-common.config.cas.loginMode` | `CAS_LOGIN_MODE` | `disabled`、`button` 或 `force` |
| `nexent-common.config.cas.userAttribute` | `CAS_USER_ATTRIBUTE` | 用户标识属性。为空时使用 `<cas:user>` |
| `nexent-common.config.cas.emailAttribute` | `CAS_EMAIL_ATTRIBUTE` | 邮箱属性 |
| `nexent-common.config.cas.roleAttribute` | `CAS_ROLE_ATTRIBUTE` | 角色属性 |
| `nexent-common.config.cas.defaultRole` | `CAS_DEFAULT_ROLE` | CAS 角色缺失、为空或不受支持时使用的 Nexent 默认角色，默认 `USER` |
| `nexent-common.config.cas.tenantAttribute` | `CAS_TENANT_ATTRIBUTE` | 租户属性 |
| `nexent-common.config.cas.defaultTenantId` | `CAS_DEFAULT_TENANT_ID` | CAS 未返回租户属性或属性为空时使用的默认租户 |
| `nexent-common.config.cas.roleMapJson` | `CAS_ROLE_MAP_JSON` | CAS 角色到 Nexent 角色的 JSON 映射 |
| `nexent-common.config.cas.sessionMaxAgeSeconds` | `CAS_SESSION_MAX_AGE_SECONDS` | CAS 本地会话最长有效期 |
| `nexent-common.config.cas.localSessionMaxAgeSeconds` | `LOCAL_SESSION_MAX_AGE_SECONDS` | Nexent 本地会话有效期 |
| `nexent-common.config.cas.heartbeatUrl` | `CAS_HEARTBEAT_URL` | 用户活动触发的 CAS Server 心跳 GET 地址；为空时禁用 |
| `nexent-common.config.cas.heartbeatIntervalSeconds` | `CAS_HEARTBEAT_INTERVAL_SECONDS` | CAS 活跃用户最小心跳间隔，默认 300 秒 |
| `nexent-common.config.cas.heartbeatCookieName` | `CAS_HEARTBEAT_COOKIE_NAME` | 复制到心跳 `X-Auth-Token` Header 的前端可读 Cookie 名称 |
| `nexent-common.config.cas.renewBeforeSeconds` | `CAS_RENEW_BEFORE_SECONDS` | 距离过期多少秒内触发无感续期 |
| `nexent-common.config.cas.renewTimeoutSeconds` | `CAS_RENEW_TIMEOUT_SECONDS` | 无感续期等待超时时间 |
| `nexent-common.config.cas.syntheticEmailDomain` | `CAS_SYNTHETIC_EMAIL_DOMAIN` | CAS 未返回邮箱时生成邮箱使用的域名 |
| `nexent-common.config.cas.logoutUrl` | `CAS_LOGOUT_URL` | CAS 登出地址。为空时 Nexent 主动退出不调用 CAS Server 登出接口 |
| `nexent-common.config.cas.sslVerify` | `CAS_SSL_VERIFY` | 访问 CAS Server 时是否校验证书 |
| `nexent-common.config.cas.caBundle` | `CAS_CA_BUNDLE` | 自定义 CA bundle 路径 |

CAS 心跳仅在 CAS 用户本地会话有效、页面可见且发生用户活动时运行。首次活动立即发送 GET，之后所有浏览器标签页共享配置的最小间隔。配置的 Cookie 可读取时，请求携带 `X-Auth-Token: <cookie-name>=<cookie-value>`；读取不到时仍发送请求但不带该 Header。由于浏览器直接访问心跳地址，认证源必须通过 CORS 允许 Nexent Origin、GET、OPTIONS 和 `X-Auth-Token`。心跳失败不会退出用户，也不会刷新本地 JWT。

常用 CAS 地址：

| 用途 | 地址 |
|------|------|
| Nexent 登录入口 | `{CAS_CALLBACK_BASE_URL}/api/user/cas/login?redirect=/` |
| CAS service 回调 | `{CAS_CALLBACK_BASE_URL}/api/user/cas/callback` |
| CAS 无感续期回调 | `{CAS_CALLBACK_BASE_URL}/api/user/cas/renew_callback` |
| CAS 单点登出回调 | `POST {CAS_CALLBACK_BASE_URL}/api/user/cas/logout_callback` |

Apereo CAS 使用 JSON Service Registry 时，可以新增一个服务注册文件，例如 `Nexent-10001.json`。文件需要放到 CAS 部署配置的 service registry 目录中，`id` 必须全局唯一。本地 NodePort 示例：

```json
{
  "@class": "org.apereo.cas.services.RegexRegisteredService",
  "serviceId": "http://localhost:30000.*",
  "name": "Nexent CAS Client",
  "id": 10001,
  "description": "Nexent CAS SSO client",
  "evaluationOrder": 1,
  "logoutType": "BACK_CHANNEL",
  "logoutUrl": "http://localhost:30000/api/user/cas/logout_callback"
}
```

生产环境建议保持 `CAS_SSL_VERIFY=true`；自签名证书优先配置 `CAS_CA_BUNDLE`，仅本地验证时再临时设置 `CAS_SSL_VERIFY=false`。

#### CAS 对接 ModelEngine

当使用 CAS 协议对接 ModelEngine 时，建议通过 values 文件配置 Nexent，避免 `CAS_ROLE_MAP_JSON` 在命令行中转义复杂。

创建 `cas-modelengine-values.yaml`：

```yaml
nexent-common:
  config:
    cas:
      enabled: true
      serverUrl: "https://<ModelEngine IP>:5443/SSOSvr"
      validatePath: "/p3/serviceValidate"
      callbackBaseUrl: "http://<Nexent IP>:30000"
      loginMode: "force"
      userAttribute: "userName"
      emailAttribute: "email"
      roleAttribute: "userType"
      defaultRole: "USER"
      tenantAttribute: "tenant_id"
      defaultTenantId: "tenant_id"
      roleMapJson: '{"1":"ADMIN","3":"DEV"}'
      sessionMaxAgeSeconds: 3600
      localSessionMaxAgeSeconds: 3600
      heartbeatUrl: "https://<ModelEngine IP>:5443/<heartbeat-path>"
      heartbeatIntervalSeconds: 300
      heartbeatCookieName: "<cookie-name>"
      renewBeforeSeconds: 300
      renewTimeoutSeconds: 10
      syntheticEmailDomain: "cas.local"
      logoutUrl: "/logout?service=http://<Nexent IP>:30000"
      sslVerify: false
      caBundle: ""
```

同时，需要进入 OMS 容器添加 CAS client 的注册配置文件，参考如下步骤：

```bash
# 创建注册配置文件，将 JSON 部分输入文件并保存
vim Nexent-10000001.json
{
  "@class": "org.apereo.cas.services.CasRegisteredService",
  "serviceId": "http://<Nexent IP>:30000.*",
  "name": "Nexent CAS Client",
  "id": 1000001,
  "description": "Nexent CAS SSO client",
  "evaluationOrder": 1,
  "logoutType": "BACK_CHANNEL",
  "logoutUrl": "http://<Nexent IP>:30000/api/user/cas/logout_callback"
}

# 执行如下命令，将配置文件拷贝到容器中
kubectl cp Nexent-10000001.json model-engine/$(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}'):/opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
kubectl exec -i -n model-engine $(kubectl get pods -n model-engine -l app=oms --no-headers | awk '{print $1}') -- chown tomcat:fusioncube /opt/huawei/fce/apps/platform/webapps/SSOSvr/WEB-INF/classes/services/Nexent-10000001.json
```

## 🔍 故障排查

### 查看 Pod 状态

```bash
kubectl get pods -n nexent
kubectl describe pod <pod-name> -n nexent
```

### 查看日志

安装命令会在终端显示当前阶段和本次日志文件的路径。Helm 操作、Pod 就绪等待以及可取得的初始化 Job 输出写入部署目录下的 `logs/deploy/deploy-YYYYMMDD-HHMMSS.log`。部署失败时，可根据终端给出的退出码和日志路径定位失败步骤。需要排查服务启动后的问题时，再查看对应 Pod 的日志。

```bash
kubectl logs -n nexent -l app=nexent-config
kubectl logs -n nexent -l app=nexent-web
kubectl logs -n nexent -l app=nexent-elasticsearch
```

### 重启服务

```bash
kubectl rollout restart deployment/nexent-config -n nexent
kubectl rollout restart deployment/nexent-runtime -n nexent
```

### Elasticsearch 初始化失败

先查看 Elasticsearch Pod 的状态和日志。修好存储、资源或访问权限问题后，在仓库根目录重新运行应用部署，脚本会再次检查 Elasticsearch、准备 API Key 并继续初始化。

```bash
bash deploy.sh k8s --defaults --release-scope nexent
```

### Pod 等待绑定存储

如果 Pod 长时间处于 `Pending`，请查看 PVC 和 Pod 事件。默认动态模式下，先确认集群有默认 StorageClass，或已用 `--storage-class` 指定支持 RWX 的存储类，再检查可用容量和卷绑定情况。多副本时还应确认五个 Runtime 共享卷都已绑定。

```bash
kubectl -n nexent get pvc
kubectl -n nexent get events --sort-by=.lastTimestamp
```

## 💡 需要帮助

- 浏览 [常见问题](./faq) 了解常见安装问题
- 在我们的 [Discord 社区](https://discord.gg/tb5H3S3wyv) 提问
- 在 [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) 中提交错误报告或功能建议
