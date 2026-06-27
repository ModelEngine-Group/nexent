# Nexent Kubernetes 升级指导

## 🚀 升级流程概览

在 Kubernetes 上升级 Nexent 时，建议依次完成以下几个步骤：

1. 拉取最新代码
2. 执行 Helm 部署脚本
3. 打开站点确认服务可用

---

## 🔄 步骤一：更新代码

更新之前，先记录下当前部署的版本和数据目录信息。

- 当前部署版本信息的位置：根目录 `VERSION`
- 本地卷目录信息的位置：各 Helm 子 chart 的 `storage.hostPath`，默认位于 `/var/lib/nexent-data/nexent-*`

**git 方式下载的代码**

通过 git 指令更新代码：

```bash
git pull
```

**zip 包等方式下载的代码**

1. 需要去 GitHub 上重新下载一份最新代码，并解压缩。
2. 将之前部署目录 `deploy/k8s` 下的 `deploy.options` 文件拷贝到新代码目录的 `deploy/k8s` 目录中。（如果不存在该文件则忽略此步骤）。

## 🔄 步骤二：执行升级

在更新后的代码仓库根目录执行 Kubernetes 部署入口：

```bash
bash deploy.sh k8s
```

脚本会自动检测您之前保存的部署设置（组件组合、端口策略、镜像来源等）。如果 `deploy.options` 文件不存在，系统会提示您输入配置信息。

> 💡 提示
> - 若需配置语音模型（STT/TTS），请在对应的 `values.yaml` 中修改相关配置，或通过命令行参数传入。

---

## 🌐 步骤三：验证部署

部署完成后：

1. 在浏览器打开 `http://localhost:30000`
2. 参考 [用户指南](../user-guide/home-page) 完成智能体配置与验证

---

## 🗄️ 数据库迁移

SQL 增量不再手动执行。Kubernetes 中只有 `nexent-config` 启动时会通过 `deploy/common/run-sql-migrations.sh` 自动按文件名顺序检查并执行 `deploy/sql/migrations/` 下的 `*.sql` 文件；其他后端服务只等待迁移记录达到目标状态。部署脚本会将 `deploy/sql` 渲染到共享 SQL ConfigMap，并挂载到 `/opt/nexent/sql`，因此只修改 SQL 时重新执行部署即可，不需要重新构建镜像。

迁移脚本使用 SQL 文件名作为 `nexent.schema_migrations` 中的迁移 ID。已记录且 checksum 相同会跳过；已记录但 checksum 变化时会重新执行同名 SQL，并更新 checksum、执行时间、应用版本和源文件路径。

> 💡 提示
> - 执行前建议先备份数据库：

   ```bash
   POSTGRES_POD=$(kubectl get pods -n nexent -l app=nexent-postgresql -o jsonpath='{.items[0].metadata.name}')
   kubectl exec nexent/$POSTGRES_POD -n nexent -- pg_dump -U root nexent > backup_$(date +%F).sql
   ```

> - Supabase 初始化 SQL 由部署脚本从 `deploy/sql/supabase/` 渲染到 Helm values，不需要手动复制执行。

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

### 迁移重试后重启服务

```bash
kubectl rollout restart deployment/nexent-config -n nexent
kubectl rollout restart deployment/nexent-runtime -n nexent
```

### 重新初始化 Elasticsearch（如需要）

```bash
bash deploy/k8s/init-elasticsearch.sh
```
