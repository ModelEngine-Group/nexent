# Nexent 升级指导

生产环境升级前，请先完成 [备份、升级与回滚指导](./backup-upgrade-rollback.md) 中的备份与恢复演练，并确认回滚窗口。本文仅介绍部署入口的基本用法。

## 🚀 升级流程概览

升级 Nexent 时，建议依次完成以下步骤：

1. 拉取最新代码
2. 执行升级脚本
3. 打开站点确认服务可用

---

## 🔄 步骤一：更新代码

更新前，先记录当前版本和数据目录，并备份 PostgreSQL、MinIO 及其他重要数据。

- 当前部署版本信息的位置：根目录 `VERSION`
- 数据目录信息的位置：`deploy/env/.env` 中的 `ROOT_DIR`

**git 方式下载的代码**

确认当前位于用于部署的分支，然后以快进方式拉取代码：

```bash
git branch --show-current
git pull --ff-only
```

**zip 包等方式下载的代码**

从 GitHub 下载目标版本并解压。然后将旧部署目录中的 `deploy/docker/deploy.options` 复制到新代码的相同位置；如果该文件不存在，可跳过此步骤。也可以在部署时使用 `--reuse-from` 直接复用旧目录的环境配置和部署选项。

## 🔄 步骤二：执行升级

在更新后的代码仓库根目录执行 Docker 部署入口：

```bash
bash deploy.sh docker
```

如果缺少 `deploy.options`，脚本会要求重新选择组件、端口策略和镜像来源。请选择与原环境一致的配置。

> 💡 提示
> - 升级时会保留 `deploy/env/.env` 中的已有值、注释、顺序和旧版独有变量，并追加当前 `deploy/env/.env.example` 新增的变量。如果 `.env` 不存在，会优先复用旧版 `docker/.env`，再回退到当前模板。加载镜像或启动服务前必须存在可读的 `.env.example`。
> - v2.5.0 会补充沙箱相关变量，并拉取 `nexent-sandbox` 镜像。若使用私有仓库或离线环境，请确认沙箱镜像也已同步。

## 🌐 步骤三：验证部署

部署完成后：

1. 在浏览器打开 `http://localhost:3000`
2. 检查 Config、Runtime、MCP、Northbound、Web 和 Data Process 等已选服务是否正常运行
3. 确认 `nexent-agent-workspace` 卷存在，且 Runtime 可以创建沙箱执行环境
4. 参考 [用户指南](../user-guide/home-page) 完成智能体配置与问答验证

## 可选操作

### 🧹 清理旧版本镜像

只有在升级验收通过、回滚观察期结束、旧镜像已独立归档后，才按具体镜像 ID 清理确认不再需要的镜像。镜像没有更新时，先核对镜像源、版本、实际镜像 ID 及 `local-latest` 配置，不要通过批量删除镜像准备升级。

升级及回滚期间保留旧镜像和持久卷，不执行 `docker system prune -af`、`down -v` 或 volume prune。完整恢复方法参见 [备份、升级与回滚指导](./backup-upgrade-rollback.md)。

---

### 🗄️ 数据库迁移

SQL 增量不再手动执行。Docker 中只有 `nexent-config` 启动时会通过 `deploy/common/run-sql-migrations.sh` 自动按文件名顺序检查并执行 `deploy/sql/migrations/` 下的 `*.sql` 文件；其他后端容器只等待迁移记录达到目标状态。SQL 会从 `deploy/sql` 挂载到 `/opt/nexent/sql`，因此只修改 SQL 时重新执行部署即可，不需要重新构建镜像。

迁移脚本使用 SQL 文件名作为 `nexent.schema_migrations` 中的迁移 ID。已记录且 checksum 相同会跳过；已记录但 checksum 变化时会重新执行同名 SQL，并更新 checksum、执行时间、应用版本和源文件路径。

已经发布的迁移文件不可修改、重命名或删除。需要调整数据库结构时，应在 `deploy/sql/migrations/` 下新增版本化迁移文件。v2.5.0 使用合并迁移文件统一应用本版本的数据库变更。

> 💡 提示
> - 升级前请备份数据库，生产环境尤为重要。
> - 如果服务启动失败，请查看后端容器日志中的 `[sql-migrations]` 记录。
