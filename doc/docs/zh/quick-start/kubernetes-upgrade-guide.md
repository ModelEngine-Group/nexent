# Nexent Kubernetes 升级指南

本文适用于使用 Helm 部署的 Nexent。建议在无人使用或业务低峰窗口执行。备份前必须停止业务写入，但不需要停止 Pod。

> ⚠️ 如果复制期间仍有业务写入，PostgreSQL、Elasticsearch、Redis 和 MinIO 等组件的数据可能不属于同一时间点，备份可能无法恢复。

## 1. 升级前检查和备份

先进入当前正在使用的 Nexent 仓库根目录；离线部署则进入上一版已解压部署包的根目录。执行 `kubectl` 的本地机器是备份目标，必须能访问目标集群。默认 namespace 为 `nexent`，应按实际环境调整。

执行以下命令前必须停止用户操作、接口请求和定时任务等业务写入；Pod 保持运行，不需要缩容或停止。脚本不会检测业务写入状态，也不会要求输入确认：

```bash
bash deploy/k8s/backup.sh \
  --backup-dir /mnt/backup/nexent \
  --namespace nexent
```

脚本会发现指定 namespace 中的全部 PVC，并为每个 PVC 选择一个完整挂载该卷的运行中容器。所有 PVC 都必须为 `Bound`，并且必须存在不使用 `subPath` 的完整挂载点；否则脚本会在复制前输出 `[ERROR]` 并指出未满足条件的 PVC，避免静默漏备份。使用自定义 `existingClaim` 时，脚本按集群中的实际 PVC 名处理，不依赖默认组件名称。

脚本通过容器内 `du` 回显每个 PVC 的未压缩数据量和总量，并通过本地 `df` 回显备份目录的可用空间。出现 `[PASS] Pre-upgrade space check passed.` 表示本地空间充足，随后脚本直接开始复制；空间不足时会在复制前退出。数据不会压缩，因此空间检查按文件原始大小计算。

脚本优先使用 `kubectl cp` 将各 PVC 的文件复制到本地；如果该命令失败且目标容器包含 `tar`，则使用 `kubectl exec ... tar -cf -` 流式传输并立即在本地解包，不保留 tar 文件。MinIO 等精简镜像不包含 `tar` 时，脚本会使用容器内的 Bash 和基础 coreutils 枚举目录，并通过 `kubectl exec ... cat` 逐文件流式导出；该路径在文件很多时会更慢。脚本不使用 `sudo`，不创建临时 Pod，也不生成压缩包或 SHA-256 文件。

实际备份目录的最外层使用 PVC 原名，例如 `nexent-postgresql/`、`nexent-workspace/`、`nexent-skills/` 和已启用监控组件的 PVC 名。通过 `[INFO]` 查看来源和复制进度；只有出现 `[PASS] Backup complete: <path>` 才表示指定 namespace 中的全部 PVC 已复制完成，`<path>` 是实际备份目录。出现 `[ERROR]` 时不要使用脚本回显的 `.partial` 未完成目录。

## 2. 执行升级

### 2.1 在线升级

在能够访问 GitHub 和所需镜像仓库的环境中，使用当前 Nexent 仓库执行在线升级。先确认当前分支和目标版本，再以快进方式更新。

```bash
git branch --show-current
git pull --ff-only
bash deploy.sh k8s --defaults --version X.Y.Z
```

`--defaults` 会复用已保存的 Kubernetes 部署配置并跳过交互界面。升级前应确认 `deploy/k8s/deploy.options` 中的组件、端口策略、镜像源、持久化模式和 namespace 与原环境一致。更多在线部署说明参见 [Kubernetes 安装部署](./kubernetes-installation.md#在线部署)。

### 2.2 离线升级

目标集群无法访问公网镜像仓库时，按 [Kubernetes 离线部署](./kubernetes-installation.md#离线部署) 下载与集群节点架构匹配的目标版本包，复制到能够访问目标集群的管理节点并解压：

```bash
unzip nexent-<version>-amd64.zip -d nexent-<version>
cd nexent-<version>
```

单节点且使用 Docker 容器运行时的集群，可直接加载新包镜像并升级：

```bash
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --load-images \
  --defaults \
  k8s
```

其他单节点或多节点集群，应将新包镜像推送到集群可访问的内部仓库：

```bash
bash deploy.sh \
  --reuse-from /path/to/previous/nexent \
  --push-images \
  --image-registry-prefix registry.example.com/nexent \
  --defaults \
  k8s
```

`/path/to/previous/nexent` 必须是上一版已解压部署包的实际根目录，且包含 `deploy/env/.env`。`--reuse-from` 会复用旧包的 `.env`、`monitoring.env` 和 Kubernetes 部署选项。ARM64 集群节点应使用对应的 `arm64` 包名。

升级时由 `nexent-config` 执行数据库自动迁移，其他后端服务会等待迁移达到目标状态。已合并的 SQL 文件不可修改、改名或删除。

## 3. 升级后检查

检查指定 namespace 中的 Pod 状态；以下示例使用默认 namespace `nexent`：

```bash
kubectl get pods -n nexent -o wide
```

所有 Nexent Pod 均为 `Running`，且 READY 数量符合预期，即表示检查通过。Pod 显示 `ContainerCreating` 时继续等待；显示 `CrashLoopBackOff`、`Error` 或长时间 `Pending` 时检查不通过。
