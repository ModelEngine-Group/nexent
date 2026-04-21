# Nexent Kubernetes 升级指导

## 🚀 升级流程概览

在 Kubernetes 上升级 Nexent 时，建议依次完成以下几个步骤：

1. 拉取最新代码
2. 执行 Helm 部署脚本
3. 打开站点确认服务可用

---

## 🔄 步骤一：更新代码

更新之前，先记录下当前部署的版本和数据目录信息。

- 当前部署版本信息的位置：`backend/consts/const.py` 中的 `APP_VERSION`
- 数据目录信息的位置：`k8s/helm/nexent/values.yaml` 中的 `global.dataDir`

**git 方式下载的代码**

通过 git 指令更新代码：

```bash
git pull
```

**zip 包等方式下载的代码**

1. 需要去 GitHub 上重新下载一份最新代码，并解压缩。
2. 将之前执行部署脚本目录下 `k8s/helm` 目录中的 `.deploy.options` 文件拷贝到新代码目录的 `k8s/helm` 目录中。（如果不存在该文件则忽略此步骤）。

## 🔄 步骤二：执行升级

进入更新后代码目录的 `k8s/helm` 目录，执行部署脚本：

```bash
cd k8s/helm
./deploy-helm.sh apply
```

脚本会自动检测您之前的部署设置（版本、镜像源等）。如果 `.deploy.options` 文件不存在，系统会提示您输入配置信息。

> 💡 提示
> - 若需配置语音模型（STT/TTS），请在对应的 `values.yaml` 中修改相关配置，或通过命令行参数传入。

---

## 🌐 步骤三：验证部署

部署完成后：

1. 在浏览器打开 `http://localhost:30000`
2. 参考 [用户指南](../user-guide/home-page) 完成智能体配置与验证

---

## 🗄️ 手动更新数据库

升级时如果存在部分 SQL 文件执行失败，或需要手动执行增量 SQL 脚本时，可以通过以下方法进行更新。

### 📋 查找 SQL 脚本

SQL 迁移脚本位于仓库的：

```
docker/sql/
```

请查看 [升级指南](./upgrade-guide.md) 或版本发布说明，确认需要执行哪些 SQL 脚本。

### ✅ 方法一：使用 SQL 编辑器（推荐）

1. 打开 SQL 编辑器，新建 PostgreSQL 连接。
2. 从正在运行的 PostgreSQL Pod 中获取连接信息：

   ```bash
   # 获取 PostgreSQL Pod 名称
   kubectl get pods -n nexent -l app=nexent-postgresql

   # 端口转发以便本地访问 PostgreSQL
   kubectl port-forward svc/nexent-postgresql 5433:5432 -n nexent &
   ```

3. 连接信息：
   - Host: `localhost`
   - Port: `5433`（转发的端口）
   - Database: `nexent`
   - User: `root`
   - Password: 可在 `k8s/helm/nexent/charts/nexent-common/values.yaml` 中查看

4. 填写连接信息后测试连接，确认成功后可在 `nexent` schema 中查看所有表。
5. 按版本顺序执行所需的 SQL 文件。

> ⚠️ 注意事项
> - 升级前请备份数据库，生产环境尤为重要。
> - SQL 脚本需按时间顺序执行，避免依赖冲突。

### 🧰 方法二：使用 kubectl exec（无需客户端）

通过 stdin 重定向直接在主机上执行 SQL 脚本：

1. 获取 PostgreSQL Pod 名称：

   ```bash
   kubectl get pods -n nexent -l app=nexent-postgresql -o jsonpath='{.items[0].metadata.name}'
   ```

2. 直接从主机执行 SQL 文件：

   ```bash
   kubectl exec -i <pod-name> -n nexent -- psql -U root -d nexent < ./sql/v1.1.1_1030-update.sql
   ```

   或者如果想交互式查看输出：

   ```bash
   cat ./sql/v1.1.1_1030-update.sql | kubectl exec -i <pod-name> -n nexent -- psql -U root -d nexent
   ```

**示例 - 依次执行多个 SQL 文件：**

```bash
# 获取 PostgreSQL Pod 名称
POSTGRES_POD=$(kubectl get pods -n nexent -l app=nexent-postgresql -o jsonpath='{.items[0].metadata.name}')

# 按顺序执行 SQL 文件
kubectl exec -i $POSTGRES_POD -n nexent -- psql -U root -d nexent < ./sql/v1.8.0_xxxxx-update.sql
kubectl exec -i $POSTGRES_POD -n nexent -- psql -U root -d nexent < ./sql/v2.0.0_0314_add_context_skill_t.sql
```

> 💡 提示
> - 执行前建议先备份数据库：

   ```bash
   POSTGRES_POD=$(kubectl get pods -n nexent -l app=nexent-postgresql -o jsonpath='{.items[0].metadata.name}')
   kubectl exec nexent/$POSTGRES_POD -n nexent -- pg_dump -U root nexent > backup_$(date +%F).sql
   ```

> - 对于 Supabase 数据库（仅完整版本），请使用 `nexent-supabase-db` Pod：

   ```bash
   SUPABASE_POD=$(kubectl get pods -n nexent -l app=nexent-supabase-db -o jsonpath='{.items[0].metadata.name}')
   kubectl cp docker/sql/xxx.sql nexent/$SUPABASE_POD:/tmp/update.sql
   kubectl exec -it nexent/$SUPABASE_POD -n nexent -- psql -U postgres -f /tmp/update.sql
   ```

---

## 🔍 故障排查

### 查看部署状态

```bash
kubectl get pods -n nexent
kubectl rollout status deployment/nexent-config -n nexent
```

### 查看日志

```bash
kubectl logs -n nexent -l app=nexent-config --tail=100
kubectl logs -n nexent -l app=nexent-web --tail=100
```

### 手动 SQL 更新后重启服务（如需要）

如果您手动执行了 SQL 脚本，需要重启受影响的服务：

```bash
kubectl rollout restart deployment/nexent-config -n nexent
kubectl rollout restart deployment/nexent-runtime -n nexent
```

### 重新初始化 Elasticsearch（如需要）

```bash
cd k8s/helm
bash init-elasticsearch.sh
```
