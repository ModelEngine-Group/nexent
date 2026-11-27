# Nexent Kubernetes 回滚指南

准备升级前的备份目录 `k8s-时间戳/` 和当时使用的部署目录。旧部署目录中应保留原版 `deploy.sh`、`VERSION`、Helm Chart、`deploy/env/.env`、`deploy/k8s/deploy.options` 以及当时使用的 `deploy/env/monitoring.env`。备份方法见 [Kubernetes 升级指南](./kubernetes-upgrade-guide)。

## 1. 停止写入

确认 `kubectl` 指向原集群和目标命名空间。暂停用户请求和自动任务，等待在途任务结束，另存备份之后需要保留的数据。将仍在写入目标卷的工作负载停下来，确认 Pod 已停止写入。恢复数据时无需保留原业务 Pod，后续部署会重新创建。

## 2. 将备份恢复到对应的持久卷

**每次备份只生成一个带时间戳的目录**，保存在执行脚本的管理机上。假设备份时指定了 `--backup-dir /mnt/backup/nexent`，脚本会在这个父目录下新建 `k8s-时间戳/`，将指定命名空间中各 PVC 的文件放在其中。以下仅展示几个子目录。

```text
/mnt/backup/nexent/
└── k8s-20261126-010000/
    ├── nexent-postgresql/
    ├── nexent-workspace/
    └── nexent-skills/
```

**保存或搬运时，整份复制 `k8s-20261126-010000/`。** 回滚时选用升级前日志中 `[PASS] Backup complete` 指向的那一份。

用 `kubectl -n nexent get pvc` 核对旧部署的 PVC 和绑定的 PV，命名空间按实际值替换。恢复普通文件时，保留 PVC 和挂载点，只清空目标数据目录的内容。

- **节点本地目录（hostPath）**：在存放数据的节点上，可直接用 `mv` 将备份工作副本中对应子目录的内容移回原路径。例如，默认本地存储配置下，`nexent-skills/` 的内容移到 `/var/lib/nexent-data/skills/`。

上述移动方法适用于普通文件。PostgreSQL 使用经过验证的数据库备份，Elasticsearch 使用兼容的快照，两者应恢复到同一时间点。

## 3. 在旧部署目录执行部署命令

核对旧配置中的命名空间、存储模式和 PVC，确认旧目录的 `VERSION` 与升级前的镜像标签一致，集群节点也能获取该镜像。以下命令在保存了旧版 `deploy.sh` 和 Helm Chart 的部署目录执行，以 `/opt/nexent/previous` 为例。

```bash
cd /opt/nexent/previous && bash deploy.sh k8s
```

如需显式指定原镜像版本，可在命令末尾添加 `--version X.Y.Z`，将 `X.Y.Z` 换成原版本号。单节点 Docker 运行时使用旧离线包时，可在旧包根目录执行 `bash deploy.sh --load-images --defaults k8s`。其他运行时或多节点集群请按 [Kubernetes 离线部署](./kubernetes-installation#离线部署)准备旧版本镜像。

部署完成后，用 `kubectl -n nexent get deploy,pods,pvc` 检查应用是否就绪、卷是否已绑定。使用其他命名空间时替换 `nexent`。登录并打开一段备份前的会话或附件，确认数据可读后再恢复流量和自动任务。
