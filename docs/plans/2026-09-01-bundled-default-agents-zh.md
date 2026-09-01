# 内置官方智能体实现计划

> **执行提示：** 实现本计划时，按任务逐项执行；行为变化遵循 TDD，先写失败测试，再实现最小改动。

**目标：** 让行业专属官方智能体在 Nexent 安装后自动出现在智能体仓库中，官方条目平台级只读，租户复制后拥有普通智能体的完整编辑和上架权限。

**架构：** 官方智能体内容由独立资源仓库维护，发布时将选定 profile 注入 Nexent 安装包。后端启动时安全加载 ZIP，在保留租户下创建或更新源智能体和仓库快照；仓库查询同时返回当前租户条目与官方条目，复制沿用现有导入流程。

**技术栈：** Python、FastAPI、SQLAlchemy/PostgreSQL、pytest、TypeScript/React、Docker Compose、Kubernetes/Helm、Bash 部署测试。

---

## 任务 1：增加官方 profile 和保留租户配置

**文件：**

- 修改：`backend/consts/const.py`
- 修改：`deploy/env/.env.example`
- 测试：`test/backend/consts/test_const.py`

**步骤：**

1. 为保留官方租户、系统用户、profile 和资源路径编写失败测试。
2. 运行 `pytest test/backend/consts/test_const.py -q`，确认测试因配置不存在而失败。
3. 增加 `OFFICIAL_AGENT_TENANT_ID`、`OFFICIAL_AGENT_USER_ID`、profile 和路径配置；只解析选定 profile，不扫描其他行业目录。
4. 补充 `.env.example` 配置说明并重新运行测试。
5. 提交：`feat(agents): configure official agent profile`。

## 任务 2：实现安全的官方 bundle 加载器

**文件：**

- 新建：`backend/services/official_agent_bundle_service.py`
- 按需修改：`backend/consts/model.py`
- 新建测试：`test/backend/services/test_official_agent_bundle_service.py`

**步骤：**

1. 编写 profile 目录、ZIP、`agent.json`、技能、知识库种子、非法 JSON 和路径穿越测试。
2. 运行 `pytest test/backend/services/test_official_agent_bundle_service.py -q`，确认失败。
3. 实现目录枚举、临时目录解压、路径安全校验、快照校验、技能加载、文本/二进制知识库种子加载。
4. 确保加载器不写入 Nexent 源码目录，并运行测试确认通过。
5. 提交：`feat(agents): load official agent bundles safely`。

## 任务 3：实现保留租户下的启动同步

**文件：**

- 新建：`backend/services/official_agent_sync_service.py`
- 修改：`backend/database/agent_db.py`
- 修改：`backend/database/agent_repository_db.py`
- 按需修改：`backend/services/agent_service.py`
- 新建测试：`test/backend/services/test_official_agent_sync_service.py`

**步骤：**

1. 编写首次同步、重复同步、版本更新、资源缺失、单 bundle 失败隔离和稳定 `agent_id` 测试。
2. 运行同步服务测试，确认失败。
3. 实现按 bundle 隔离的同步：查找并复用保留租户下的源智能体，缺失时才创建，使用现有仓库 upsert 更新快照。
4. 将同步任务接入数据库就绪后的后端生命周期，确保不会并发产生重复源智能体。
5. 运行：`pytest test/backend/services/test_official_agent_sync_service.py test/backend/database/test_agent_db.py -q`。
6. 提交：`feat(agents): sync official templates on startup`。

## 任务 4：让现有智能体仓库展示官方条目

**文件：**

- 修改：`backend/database/agent_repository_db.py`
- 修改：`backend/services/agent_repository_service.py`
- 按需修改：`backend/apps/agent_repository_app.py`
- 修改测试：`test/backend/services/test_agent_repository_service.py`
- 修改测试：`test/backend/app/test_agent_repository_app.py`

**步骤：**

1. 编写官方条目可见、可查看、可复制，以及不可编辑/审核/下架/删除的失败测试。
2. 运行相关服务和端点测试，确认当前租户范围校验导致失败。
3. 扩展列表和详情读取范围，允许当前租户读取官方保留租户条目；保留所有管理写操作的普通租户归属校验。
4. 确保导入目标始终是当前认证用户和当前租户，官方源智能体不出现在租户“我的智能体”列表。
5. 运行相关 pytest 测试并确认通过。
6. 提交：`feat(repository): expose official agent templates`。

## 任务 5：在现有仓库页面标识官方条目

**文件：**

- 修改：`frontend/types/agentRepository.ts`
- 修改：`frontend/app/[locale]/agent-space/` 下相关列表和详情组件
- 修改：`frontend/public/locales/zh/common.json`
- 修改：`frontend/public/locales/en/common.json`

**步骤：**

1. 编写官方标识、复制按钮和隐藏管理按钮的前端测试。
2. 实现官方 badge、国际化文本和操作按钮控制；复制流程保持不变。
3. 运行前端测试及 `pnpm tsc --noEmit`，确认无新增 TypeScript 错误。
4. 提交：`feat(repository): label official agent templates`。

## 任务 6：将行业资源包注入 Docker/Kubernetes/离线安装包

**文件：**

- 修改：`deploy/offline/build_offline_package.sh`
- 修改：`deploy/docker/deploy.sh`
- 修改：`deploy/docker/compose/docker-compose.yml`
- 修改：`deploy/docker/compose/docker-compose.prod.yml`
- 修改：`deploy/k8s/deploy.sh`
- 按需修改：`deploy/k8s/helm/nexent/`
- 修改：`deploy/env/.env.example`
- 修改测试：`deploy/tests/test_build_offline_package.sh` 及相关部署测试

**步骤：**

1. 编写 profile 选择、只打包选定行业、Docker 只读挂载、Kubernetes 注入和缺失 profile 测试。
2. 运行 `bash deploy/tests/test_build_offline_package.sh`，确认当前功能缺失导致失败。
3. 增加外部资源包输入，将选定 profile 复制到最终安装包，持久化配置，并以只读方式挂载到 `OFFICIAL_AGENTS_PATH`。
4. 确保 Docker 和 Kubernetes 使用一致的运行时路径，且 Nexent 源码仓库不包含官方 bundle 内容。
5. 运行部署测试并确认通过。
6. 提交：`feat(deploy): package industry agent profiles`。

## 任务 7：执行完整验证

运行以下验证：

```bash
pytest test/backend/services/test_official_agent_bundle_service.py \
  test/backend/services/test_official_agent_sync_service.py \
  test/backend/services/test_agent_repository_service.py \
  test/backend/app/test_agent_repository_app.py -q

bash deploy/tests/test_build_offline_package.sh

cd frontend
pnpm tsc --noEmit
```

此外运行相关后端导入测试、Docker/Kubernetes shell 测试，并区分已有失败与本次引入的失败。

最终自检：

- 官方 bundle 未加入 Nexent 源码仓库；
- 未增加数据库字段、表或 migration；
- 官方源智能体只属于保留租户；
- 租户复制后使用自己的租户 ID，并拥有普通权限；
- 官方条目全局可读但管理写操作受保护；
- 只加载配置的行业 profile；
- 未暂存工作树中已有的用户文件。
