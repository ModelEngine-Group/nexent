# Nexent Kubernetes 回滚指南

准备升级前的备份目录 `k8s-时间戳/` 和当时使用的部署目录。旧部署目录中应保留原版 `deploy.sh`、`VERSION`、Helm Chart、`deploy/env/.env`、`deploy/k8s/deploy.options` 以及当时使用的 `deploy/env/monitoring.env`。备份方法见 [Kubernetes 升级指南](./kubernetes-upgrade-guide)。

## 1. 停止写入

确认 `kubectl` 指向原集群和目标命名空间。暂停用户请求和自动任务，等待正在执行的任务结束。保留当前数据，确认备份完成后新增的会话、文件等是否需要另存。恢复前停止仍在写入目标卷的工作负载。

## 2. 将备份恢复到对应的持久卷

使用备份日志中 `[PASS] Backup complete` 指向的目录。备份保存在当时执行 `kubectl` 的管理机上，每个子目录以实际的 PVC 名称命名。按旧配置核对 PVC 和绑定的卷，将普通文件恢复到对应的空卷并保留文件权限。例如，`k8s-时间戳/nexent-workspace/` 对应原命名空间中的 `nexent-workspace` 工作区卷。

数据库和索引应恢复到同一时间点。PostgreSQL 使用经过验证的数据库备份，Elasticsearch 使用兼容的快照。直接复制运行中的数据目录无法保证一致性。

## 3. 在旧部署目录执行部署命令

核对旧配置中的存储模式、命名空间和 PVC 绑定，确认应用将挂载已恢复的卷。使用 `--defaults` 时，核对旧目录的 `VERSION` 与升级前实际使用的镜像标签，并确认集群节点能获取旧镜像。将以下路径替换为原部署目录并执行命令。

```bash
cd /path/to/previous/nexent && bash deploy.sh k8s --defaults
```

如需显式指定原镜像版本，可在命令末尾添加 `--version X.Y.Z`，将 `X.Y.Z` 换成原版本号。单节点 Docker 运行时使用旧离线包时，可在旧包根目录执行 `bash deploy.sh --load-images --defaults k8s`。其他运行时或多节点集群请按 [Kubernetes 离线部署](./kubernetes-installation#离线部署)准备旧版本镜像。

部署完成后，用 `kubectl -n nexent get deploy,pods,pvc` 检查应用是否就绪、卷是否已绑定。使用其他命名空间时替换 `nexent`。登录并打开一段备份前的会话或附件，确认数据可读后再恢复流量和自动任务。
