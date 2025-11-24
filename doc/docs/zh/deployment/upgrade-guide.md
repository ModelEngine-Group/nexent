# Nexent 升级指导

## 🚀 升级流程概览

升级 Nexent 时建议依次完成以下四个步骤：

1. 清理旧版本容器与镜像
2. 拉取最新代码并执行部署脚本
3. 同步数据库结构
4. 打开站点确认服务可用

---

## 🧹 步骤一：清理旧版本镜像

为避免缓存或版本冲突，先清理旧容器与镜像：

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

## 🔄 步骤二：更新代码并部署

```bash
git pull
cd nexent/docker
cp .env.example .env
bash deploy.sh
```

> 💡 提示
> - 默认为快速部署场景，可直接使用 `.env.example`。
> - 若需配置语音模型（STT/TTS），请在 `.env` 中补充相关变量，我们将尽快提供前端配置入口。

---

## 🗄️ 步骤三：同步数据库

升级后需要执行数据库迁移脚本，使 schema 保持最新。

### ✅ 方法一：使用 SQL 编辑器（推荐）

1. 打开 SQL 编辑器，新建 PostgreSQL 连接。
2. 在 `/nexent/docker/.env` 中找到以下信息：
   - Host
   - Port
   - Database
   - User
   - Password
3. 填写连接信息后测试连接，确认成功后可在 `nexent` schema 中查看所有表。
4. 新建查询窗口。
5. 打开 `/nexent/docker/sql` 目录，按文件名中的日期顺序查看 SQL 脚本。
6. 根据上次部署日期，依次执行之后的每个 SQL 文件。

> ⚠️ 注意事项
> - 升版本前请备份数据库，生产环境尤为重要。
> - SQL 脚本需按时间顺序执行，避免依赖冲突。
> - `.env` 变量可能命名为 `POSTGRES_HOST`、`POSTGRES_PORT` 等，请在客户端对应填写。

### 🧰 方法二：命令行执行（无需客户端）

1. 进入 Docker 目录：

   ```bash
   cd nexent/docker
   ```

2. 从 `.env` 中获取数据库连接信息，例如：

   ```bash
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_DB=nexent
   POSTGRES_USER=root
   POSTGRES_PASSWORD=your_password
   ```

3. 通过容器执行 SQL 脚本（示例）：

   ```bash
   # 假如现在是11月6日，上次更新版本的时间是10月20日
   # 此时新增了1030-update.sql和1105-update.sql两个文件
   # 我们需要执行以下命令（请注意替换占位符中的变量）
   docker exec -i nexent-postgresql psql -U [YOUR_POSTGRES_USER] -d [YOUR_POSTGRES_DB] < ./sql/1030-update.sql
   docker exec -i nexent-postgresql psql -U [YOUR_POSTGRES_USER] -d [YOUR_POSTGRES_DB] < ./sql/1105-update.sql
   ```

   请根据自己的部署时间，按时间顺序执行对应脚本。

> 💡 提示
> - 若 `.env` 中定义了数据库变量，可先导入：
>
>   **Windows PowerShell:**
>   ```powershell
>   Get-Content .env | Where-Object { $_ -notmatch '^#' -and $_ -match '=' } | ForEach-Object { $key, $value = $_ -split '=', 2; [Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim(), 'Process') }
>   ```
>
>   **Linux/WSL:**
>   ```bash
>   export $(grep -v '^#' .env | xargs)
>   # 或使用 set -a 自动导出所有变量
>   set -a; source .env; set +a
>   ```
>
> - 执行前建议先备份：
>
>   ```bash
>   docker exec -i nexent-postgres pg_dump -U [YOUR_POSTGRES_USER] [YOUR_POSTGRES_DB] > backup_$(date +%F).sql
>   ```

---

## 🌐 步骤四：验证部署

部署完成后：

1. 在浏览器打开 `http://localhost:3000`
2. 参考 [用户指南](https://doc.nexent.tech/zh/user-guide/home-page) 完成智能体配置与验证
