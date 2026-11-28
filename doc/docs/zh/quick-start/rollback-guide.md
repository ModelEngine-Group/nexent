# Nexent Docker 回滚指南

准备升级前的备份目录 `docker-时间戳/` 和当时使用的部署目录。旧部署目录中应保留原版 `deploy.sh`、`VERSION`、`deploy/env/.env`、`deploy/docker/deploy.options` 以及当时使用的 `deploy/env/monitoring.env`。备份方法见 [Docker 升级指南](./upgrade-guide)。

## 1. 停止写入

暂停用户请求和自动任务，等待在途任务结束，另存备份之后需要保留的数据。旧业务容器仍在运行时，先停止所有会写入目标目录或卷的容器。旧容器已经移除也可以恢复，最后用旧部署目录中的脚本重新创建业务容器。

## 2. 将备份恢复到原挂载位置

**每次备份只生成一个带时间戳的目录。** 假设备份时指定了 `--backup-dir /mnt/backup/nexent`，脚本会在这个父目录下新建 `docker-时间戳/`。下面是一份备份的示例结构，实际子目录取决于旧部署使用的路径和卷。

```text
/mnt/backup/nexent/
└── docker-20261126-010000/
    ├── nexent-data/             ← 原 ROOT_DIR 的全部内容
    ├── nexent/                  ← 原 NEXENT_USER_DIR 的全部内容
    └── nexent-agent-workspace/  ← 一个 Docker 命名卷的内容
```

**保存或搬运时，整份复制 `docker-20261126-010000/`。** 回滚时选用升级前日志中 `[PASS] Backup complete` 指向的那一份。、

**普通文件可直接移回原目录。** 按旧部署的 `ROOT_DIR` 和 `NEXENT_USER_DIR` 核对路径，保留挂载目录本身，清空目标目录的内容，再用 `mv` 把对应备份子目录里的内容（含隐藏文件）移进去，保留属主和权限。对备份的工作副本执行 `mv`，以便原始备份仍可使用。

以部署用户 `admin` 为例，若 `ROOT_DIR=/home/admin/nexent-data`，备份副本中 `nexent-data/skills/` 的内容就移到已清空的 `/home/admin/nexent-data/skills/`。`nexent/` 的内容移到原 `NEXENT_USER_DIR`，例如 `/home/admin/nexent/`。

上述移动方法适用于普通文件。PostgreSQL 使用经过验证的数据库备份，Elasticsearch 使用兼容的快照，两者应恢复到同一时间点。

## 3. 在旧部署目录执行部署命令

确认镜像版本与升级前一致，进入保存了旧版 `deploy.sh` 的部署目录执行命令。下面以 `/opt/nexent/previous` 为例，请替换为实际旧部署目录。

```bash
cd /opt/nexent/previous && bash deploy.sh docker
```

如需显式指定原镜像版本，可在命令末尾添加 `--version X.Y.Z`，将 `X.Y.Z` 换成原版本号。使用旧离线包且需要重新加载镜像时，在旧包根目录执行 `bash deploy.sh --load-images --defaults docker`。

部署完成后，用 `docker ps -a --filter label=com.docker.compose.project=nexent` 检查容器状态。登录并打开一段备份前的会话或附件，确认数据可读后再恢复流量和自动任务。
