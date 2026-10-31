# Nexent 项目长期备忘

## 分支与合并规约
- 分支流：feature/hotfix → develop → main（发版时）
- **任何分支合入 main/develop 一律选 "Create a merge commit"，禁止 Squash**。squash 会导致祖先断裂，同一分支下次再合必然重现冲突（v2.6.0 #3942、v2.6.1 #3971/#3993 多次踩坑）
- main 接受 hotfix 后，需当天把 main 回流进 develop，否则 develop→main 会持续冲突

## Release Notes 风格（用户明确偏好）
- **不要写「移除了 xxx」「新增了 xxx」**。破坏性变更（如 HITL 移除）统一表述为「重构优化人在回路问题」；其余用「优化 xxx」「修复 xxx」
- 章节用：重构优化 / Refactoring & Improvements、Bug 修复 / Bug Fixes、文档与部署变化 / Docs & Deployment Changes
- 每条 bullet 中英双语，中文在前，` / ` 分隔
- 工具：nexent-release-notes skill（用户级），脚本 `scripts/release_diff.py` 收集 git 证据

## 本地部署环境
- 部署在 WSL（Ubuntu），数据目录 `/home/byzha/nexent-data`（WSL 文件系统，非 Windows）
- 部署脚本必须在 WSL 内执行：`cd /mnt/c/code/nexent && bash deploy.sh --defaults docker --image-source mainland`
- 国内拉镜像用 `--image-source mainland`（腾讯云 ccr.ccs.tencentyun.com/nexent-hub/*），general 源（DockerHub + daocloud 加速器）会 403
- WSL 的 `~/.docker/config.json` 若含 `credsStore: desktop.exe` 会导致拉镜像报 credentials 错误，需清空
- **密钥配置在 `deploy/env/.env`（git 忽略）**：丢失可从运行容器恢复——`docker inspect <c> --format '{{range .Config.Env}}{{println .}}{{end}}'` 提取（anon key 在 nexent-web 容器名 SUPABASE_KEY，service key 在 supabase-kong-mini）；`.env.example` 复制作底 + 追加恢复段
- 镜像版本注意：develop 代码 VERSION 可能领先于腾讯云源已发布镜像（如 2026-09-29 代码 v2.7.0 但源上最新仅 v2.6.1），此时需 `--app-version v2.6.1` 显式指定，否则 compose 找不到镜像
- **要部署比镜像源更新的代码 → 本地构建 + `--image-source local-latest`**：Git Bash 直接 `cd 仓库 && docker buildx build -f deploy/images/dockerfiles/<name>/Dockerfile --load .`（勿用 skill 脚本的 Git Bash 分支，有 cd 子 shell bug）；需 `export PATH="/c/Program Files/Docker/Docker/resources/bin:$PATH"` 防 credentials 报错；国内网络构建坑：Debian security 源 502（sed 换清华）、nodejs.org TLS 中断（换 npmmirror）、sandbox jupyter pip 漏 MIRROR 参数（sed 补 `-i $MIRROR`），构建完 `git checkout --` 还原 Dockerfile
- **发版镜像可能个别漏推**（2026-09-30 v2.7.0：main/data-process/mcp/sandbox 都推了，唯独 web 漏推）：部署前逐个 `docker manifest inspect` 检查；缺的镜像可本地构建后直接 tag 成官方镜像名（如 `ccr.ccs.tencentyun.com/nexent-hub/nexent-web:v2.7.0`）即可正常部署
- **部署报容器名冲突（"already in use"）→ 先清残留**：`docker ps -a` 找 Created/Exited 的半成品容器删掉再重跑；不清会导致 compose 兼容模式给新容器加 hash 前缀（如 80e5a8cbf0d8_nexent-config），进而让 create-su.sh 等按固定名 `docker exec nexent-config` 的脚本失败（表象是 "No response received from Supabase"，实际是找不到容器）

## 环境坑（Windows + Git Bash）
- `wsl` 命令被安全策略禁用时，可直写 `//wsl.localhost/Ubuntu/...` 访问 WSL 文件；**执行命令用 `"/c/Windows/System32/bash.exe" -c "..."` 可进 WSL**（输出开头有一行 UTF-16 乱码是 wsl 代理提示，不影响执行）；WSL 内 docker 与 Windows Docker Desktop 同一 daemon
- **merge/checkout 大更新后必须 `git status --short` 检查 " D" 状态**：本机曾出现 208 个 deploy 文件从磁盘消失但索引完好，`git restore -- <dir>` 可恢复（2026-09-29 踩坑）
- **refs/remotes/origin/ 目录可能整个不存在**（全在 packed-refs），此时 update-ref 静默失败（返回 0 但 ref 不变）；修复：先 `mkdir -p .git/refs/remotes/origin` 再直接写 ref 文件
- **主仓库 .git 曾遭神秘破坏（2026-09-30）**：`.git/refs/` 整个目录被反复删除（疑似 .git 里残留的 opencode/mw_recover_idx 等工具的后台行为）、shallow 文件出现、部分对象丢失。修复套路：mkdir refs/heads + 写 develop ref + 写 HEAD → 删 .git/shallow → `git fetch --refetch` → `git update-ref -d` 删指向缺失对象的坏分支。**git 突然报 "not a git repository" 时先查 refs 目录是否被删**
- 临时仓库反复 reset 会导致 `refs/heads` 被清空、`packed-refs` 不生效；`.git/index.lock` 可能被进程占用无法删除
- 绕过方案：用 `GIT_INDEX_FILE` 独立索引 + `git merge-tree --write-tree` + `git commit-tree` 直接构造合并树和双父提交
- **构造临时 commit 一律在独立 clone（如 C:\nexent-m4）里做，绝不要在主仓库 C:\code\nexent 操作**——2026-09-28 主仓库因残留构造操作导致 HEAD 对象丢失（fatal: bad object HEAD），修复：备份工作区 → update-ref 到 fetch 后的 origin/develop → reset --mixed
- packed-refs 里的 remote refs 可能是旧快照，判断远端状态前必须先 `git fetch`
- **本机 git 写 loose ref 经常静默失败**（fetch 显示成功但 ref 仍解析到 packed-refs 旧值），`reset --hard origin/xxx` 前必须先 `git rev-parse origin/xxx` 确认指向；坏了就手工写 `.git/refs/...` 文件修复
- `git clone` 到 `/c/temp/...` 会静默失败，用 `C:\temp\...` 或仓库内路径
- 重定向到 `/tmp` 在 Git Bash for Windows 下会失败，输出文件要放仓库内
- 本地沙箱（sitecustomize.py）会拦截删除目录到回收站，导致 test_run_agent 等测试本地假阳性（同内容改文件名就过）；**本地测试失败 ≠ CI 失败，必须先在 develop 基线上对照归因**
