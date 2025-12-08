# Nexent 升级指导

## 🚀 升级流程概览

升级 Nexent 时建议依次完成以下几个步骤：

1. 拉取最新代码
2. 执行升级脚本
3. 打开站点确认服务可用

---

## 🔄 步骤一：更新代码

更新之前，先记录下当前部署的版本和数据目录

- 当前部署版本信息的位置：`backend/consts/const.py`中的 APP_VERSION
- 数据目录信息的位置：`docker/.env`中的 ROOT_DIR

**git 方式下载的代码**

通过 git 指令更新代码

```bash
git pull
```

**zip 包等方式下载的代码**

需要去 github 上重新下载一份最新代码，并解压缩。另外，需要从之前执行部署脚本目录下 docker 目录中拷贝 deploy.options 到新代码目录下的 docker 目录中（如果不存在该文件则忽略）。

## 🔄 步骤二：执行升级

进入更新后代码目录的docker目录，执行升级脚本：

```bash
bash upgrade.sh
```

缺少 deploy.options 的情况下，会提示需要手动输入之前部署的一些配置，比如：当前部署版本、数据目录等。按照提示输入之前记录的信息即可。

> 💡 提示
> - 默认为快速部署场景，使用 `.env.example`。
> - 若需配置语音模型（STT/TTS），请提前在 `.env.example` 中补充相关变量，我们将尽快提供前端配置入口。

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

### 🗄️ 手动更新数据库

升级时如果存在部分 sql 文件执行失败，则可以手动执行更新。

#### ✅ 方法一：使用 SQL 编辑器（推荐）

1. 打开 SQL 编辑器，新建 PostgreSQL 连接。
2. 在 `/nexent/docker/.env` 中找到以下信息：
   - Host
   - Port
   - Database
   - User
   - Password
3. 填写连接信息后测试连接，确认成功后可在 `nexent` schema 中查看所有表。
4. 新建查询窗口。
5. 打开 `/nexent/docker/sql` 目录，通过失败的sql文件查看 SQL 脚本。
6. 将失败的sql文件和后续版本的sql文件依次执行。

> ⚠️ 注意事项
> - 升版本前请备份数据库，生产环境尤为重要。
> - SQL 脚本需按时间顺序执行，避免依赖冲突。
> - `.env` 变量可能命名为 `POSTGRES_HOST`、`POSTGRES_PORT` 等，请在客户端对应填写。

#### 🧰 方法二：命令行执行（无需客户端）

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
   # 我们需要执行以下命令（请注意替换占位符中的变量）
   docker exec -i nexent-postgresql psql -U [YOUR_POSTGRES_USER] -d [YOUR_POSTGRES_DB] < ./sql/v1.1.1_1030-update.sql
   docker exec -i nexent-postgresql psql -U [YOUR_POSTGRES_USER] -d [YOUR_POSTGRES_DB] < ./sql/v1.1.2_1105-update.sql
   ```

   请根据自己的部署版本，按版本顺序执行对应脚本。

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
