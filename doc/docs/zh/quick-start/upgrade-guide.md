# Nexent 升级指导

## 🚀 升级流程概览

升级 Nexent 时建议依次完成以下几个步骤：

1. 拉取最新代码
2. 执行升级脚本
3. 打开站点确认服务可用

---

## 🔄 步骤一：更新代码

更新之前，先记录下当前部署的版本和数据目录

- 当前部署版本信息的位置：根目录 `VERSION`
- 数据目录信息的位置：`deploy/env/.env`中的 ROOT_DIR

**git 方式下载的代码**

通过 git 指令更新代码

```bash
git pull
```

**zip 包等方式下载的代码**

需要去 github 上重新下载一份最新代码，并解压缩。另外，需要从之前执行部署脚本目录下 docker 目录中拷贝 deploy.options 到新代码目录下的 docker 目录中（如果不存在该文件则忽略）。

## 🔄 步骤二：执行升级

在更新后的代码仓库根目录执行 Docker 部署入口：

```bash
bash deploy.sh docker
```

缺少 deploy.options 的情况下，会提示需要重新选择部署配置，例如组件组合、端口策略、镜像来源等。按照您之前的部署方式重新选择即可。

> 💡 提示
> - 已有 `deploy/env/.env` 会原样保留；如果不存在，部署脚本会优先复用旧的根目录 `.env` 或 `docker/.env`，再回退到 `deploy/env/.env.example` 或旧模板。
> - 若需配置语音模型（STT/TTS），请在 `deploy/env/.env` 中补充相关变量，我们将尽快提供前端配置入口。

## 🌐 步骤三：验证部署

部署完成后：

1. 在浏览器打开 `http://localhost:3000`
2. 参考 [用户指南](https://doc.nexent.tech/zh/user-guide/home-page) 完成智能体配置与验证

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
> - 删除镜像前请先备份重要数据。
> - 若需保留数据库数据，请勿删除数据库 volume（通常位于 `/nexent/docker/volumes` 或自定义挂载路径）。

---

### 🗄️ 数据库迁移

SQL 增量不再手动执行。Docker 中只有 `nexent-config` 启动时会通过 `deploy/common/run-sql-migrations.sh` 自动按文件名顺序检查并执行 `deploy/sql/migrations/` 下的 `*.sql` 文件；其他后端容器只等待迁移记录达到目标状态。SQL 会从 `deploy/sql` 挂载到 `/opt/nexent/sql`，因此只修改 SQL 时重新执行部署即可，不需要重新构建镜像。

迁移脚本使用 SQL 文件名作为 `nexent.schema_migrations` 中的迁移 ID。已记录且 checksum 相同会跳过；已记录但 checksum 变化时会重新执行同名 SQL，并更新 checksum、执行时间、应用版本和源文件路径。

> 💡 提示
> - 升级前请备份数据库，生产环境尤为重要。
> - 如果服务启动失败，请查看后端容器日志中的 `[sql-migrations]` 记录。
