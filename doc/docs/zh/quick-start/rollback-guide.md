# Nexent Docker 回滚指南

准备升级前的备份目录 `docker-时间戳/` 和当时使用的部署目录。旧部署目录中应保留原版 `deploy.sh`、`VERSION`、`deploy/env/.env`、`deploy/docker/deploy.options` 以及当时使用的 `deploy/env/monitoring.env`。备份方法见 [Docker 升级指南](./upgrade-guide)。

## 1. 停止写入

暂停用户请求和自动任务，等待正在执行的任务结束。保留当前数据，确认备份完成后新增的会话、文件等是否需要另存。恢复前停止仍在使用目标目录或卷的容器。

## 2. 将备份恢复到原挂载位置

使用备份日志中 `[PASS] Backup complete` 指向的目录。对照旧部署配置，将普通文件恢复到对应的空目录或空卷，并保留文件权限。

| 备份中的内容 | 恢复位置 |
| --- | --- |
| 两个以原宿主机目录名保存的子目录，默认是 `nexent-data/` 和 `nexent/` | 分别恢复到旧配置的 `ROOT_DIR` 和 `NEXENT_USER_DIR` |
| 以 Docker 命名卷名称保存的子目录，例如 `nexent-agent-workspace/` | 将目录内容恢复到旧部署挂载的对应命名卷 |

数据库和索引应恢复到同一时间点。PostgreSQL 使用经过验证的数据库备份，Elasticsearch 使用兼容的快照。直接复制运行中的数据目录无法保证一致性。

## 3. 在旧部署目录执行部署命令

确认镜像版本与升级前一致，将以下路径替换为原部署目录并执行命令。

```bash
cd /path/to/previous/nexent && bash deploy.sh docker --defaults
```

如需显式指定原镜像版本，可在命令末尾添加 `--version X.Y.Z`，将 `X.Y.Z` 换成原版本号。使用旧离线包且需要重新加载镜像时，在旧包根目录执行 `bash deploy.sh --load-images --defaults docker`。

部署完成后，用 `docker ps -a --filter label=com.docker.compose.project=nexent` 检查容器状态。登录并打开一段备份前的会话或附件，确认数据可读后再恢复流量和自动任务。
