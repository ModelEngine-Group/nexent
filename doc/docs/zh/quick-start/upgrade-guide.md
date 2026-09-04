# Nexent 升级指导

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

如果镜像未正确更新，可以在升级前先清理旧容器与镜像：

```bash
# 停止并删除现有容器
docker compose down

# 查看 Nexent 镜像
docker images --filter "reference=nexent/*"

# 删除 Nexent 镜像
# Windows PowerShell:
docker images -q --filter "reference=nexent/*" | ForEach-Object { docker rmi -f $_ }

# Linux/WSL:
docker images -q --filter "reference=nexent/*" | xargs -r docker rmi -f

# （可选）清理未使用的镜像与缓存
docker system prune -af
```

> ⚠️ 注意事项
> - 删除镜像不会备份业务数据；升级前仍需单独备份数据库和对象存储。
> - 若需保留数据库数据，请勿删除数据库 volume（通常位于 `/nexent/docker/volumes` 或自定义挂载路径）。
> - `docker system prune -af` 会清理当前 Docker 主机上所有未使用的镜像和构建缓存，不仅限于 Nexent。共享主机上不建议执行。

---

### 🗄️ 数据库迁移

SQL 增量不再手动执行。Docker 中只有 `nexent-config` 启动时会通过 `deploy/common/run-sql-migrations.sh` 自动按文件名顺序检查并执行 `deploy/sql/migrations/` 下的 `*.sql` 文件；其他后端容器只等待迁移记录达到目标状态。SQL 会从 `deploy/sql` 挂载到 `/opt/nexent/sql`，因此只修改 SQL 时重新执行部署即可，不需要重新构建镜像。

迁移脚本使用 SQL 文件名作为 `nexent.schema_migrations` 中的迁移 ID。已记录且 checksum 相同会跳过；已记录但 checksum 变化时会重新执行同名 SQL，并更新 checksum、执行时间、应用版本和源文件路径。

已经发布的迁移文件不可修改、重命名或删除。需要调整数据库结构时，应在 `deploy/sql/migrations/` 下新增版本化迁移文件。v2.5.0 使用合并迁移文件统一应用本版本的数据库变更。

> 💡 提示
> - 升级前请备份数据库，生产环境尤为重要。
> - 如果服务启动失败，请查看后端容器日志中的 `[sql-migrations]` 记录。
