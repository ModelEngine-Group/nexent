---
title: 环境准备
---

# 环境准备

本指南区分全栈开发和仅使用 SDK 两类场景。若需要修改 Web 页面或平台服务，请完成全栈环境准备；若只需要在 Python 项目中使用 Nexent SDK，可直接查看“仅使用 SDK”。

## 🧱 通用要求

- Python 3.11+
- Node.js 18.18+ 与 pnpm
- Docker 与 Docker Compose
- uv（Python 包和虚拟环境管理器）
- Git Bash、WSL 或其他可以执行 Bash 脚本的终端

::: info Windows 用户
项目部署脚本使用 Bash。可以在 Git Bash 或 WSL 中执行部署命令；前端和后端开发命令也可以分别在 PowerShell 中执行。
:::

## 🧑‍💻 全栈 Nexent 开发

### ⚙️ 基础设施部署

先在项目根目录启动 PostgreSQL、Redis、Elasticsearch 和 MinIO：

```bash
bash deploy.sh docker --components infrastructure --port-policy development
```

::: info 重要提示
基础设施模式会在项目根目录生成 `.env`，其中包含本地开发所需的服务地址和密钥。不要提交该文件，也不要把其中的敏感值复制到文档、日志或聊天 Metadata 中。
:::

系统级运行沙箱默认启用。若需要调试会执行脚本的工具或 Skill，请保持 Docker 服务可用。

### 🐍 后端依赖

```bash
cd backend
uv sync --extra data-process --extra test
```

以上命令会创建或更新 `backend/.venv`，安装后端依赖，并以可编辑模式安装本地 SDK。修改 `sdk/nexent/` 后无需重复复制包文件。

`data-process` extra（以及 SDK `dev`）默认选择 CPU 版 PyTorch 和 Torchvision。请使用与 CI、镜像构建一致的 uv 0.11.7。backend extras 已包含本地 SDK，无需再次单独安装。

需要 NVIDIA CUDA 13.0 依赖时，使用替代配置：

```bash
# 在 backend/ 下执行
uv sync --extra nvidia --extra test
```

`data-process` 与 `nvidia` 互斥，不要使用 `--all-extras`。`uv sync` 会移除仅属于上一配置的依赖。两者均不选择时，基础安装不会引入 PyTorch。普通依赖可以使用镜像源，PyTorch CPU/CUDA wheel 仍使用显式配置的官方索引。安装 CUDA 依赖不代表已验证 GPU 硬件或驱动兼容性。

独立开发 SDK 时，在 `sdk/` 下执行 `uv pip install -e ".[dev]"` 使用 CPU，或 `uv pip install -e ".[quality,performance,nvidia]"` 使用 NVIDIA。独立 `uv pip` 安装切换配置时请使用全新虚拟环境；它与 `uv sync` 不同，会保留无关的已安装依赖。NVIDIA 配置替代 SDK 的 `data_process`/`dev`。


从包仓库安装已发布的 SDK 时，wheel 元数据不会携带源码目录中的 uv 索引配置，需要明确选择后端：

```bash
uv pip install "nexent[data-process]" --torch-backend cpu
uv pip install "nexent[nvidia]" --torch-backend cu130
```

#### 可选：镜像加速

网络受限时，可以为 uv 指定镜像。例如：

```bash
# 清华源
uv sync --extra data-process --extra test --default-index https://pypi.tuna.tsinghua.edu.cn/simple

# 阿里云
uv sync --extra data-process --extra test --default-index https://mirrors.aliyun.com/pypi/simple/

# 多源（推荐）
uv sync --extra data-process --extra test --index https://pypi.tuna.tsinghua.edu.cn/simple --index https://mirrors.aliyun.com/pypi/simple/
```

:::: info 镜像参考
- 清华：`https://pypi.tuna.tsinghua.edu.cn/simple`
- 阿里：`https://mirrors.aliyun.com/pypi/simple/`
- 中科大：`https://pypi.mirrors.ustc.edu.cn/simple/`
- 豆瓣：`https://pypi.douban.com/simple/`
多源组合可提升成功率。
::::

### ⚛️ 前端依赖

```bash
cd frontend
pnpm install
pnpm dev
```

开发服务器默认监听项目配置的端口。终端显示访问地址后，用浏览器打开该地址即可查看页面；修改前端代码后会自动刷新。

### 🏃 服务启动

每个后端服务都应在独立终端中启动。先切换到项目根目录并激活后端虚拟环境：

```bash
source backend/.venv/bin/activate
```

Windows PowerShell 使用：

```powershell
.\backend\.venv\Scripts\Activate.ps1
```

Windows Git Bash 使用：

```bash
source backend/.venv/Scripts/activate
```

随后在项目根目录启动需要调试的服务。服务会通过 `python-dotenv` 读取项目根目录的 `.env`；若终端中已经设置同名环境变量，则保留终端中的值。

```bash
python backend/mcp_service.py
python backend/data_process_service.py
python backend/config_service.py
python backend/runtime_service.py
python backend/northbound_service.py
```

| 服务 | 主要职责 |
| --- | --- |
| `mcp_service.py` | 内置工具与 MCP 工具接口 |
| `data_process_service.py` | 文档解析、分片和向量化任务 |
| `config_service.py` | 模型、智能体、知识库和资源配置接口 |
| `runtime_service.py` | 智能体运行与流式问答 |
| `northbound_service.py` | 面向外部系统的北向 API |

只调试某一模块时，可以仅启动它依赖的服务；需要完整体验平台功能时，应启动全部核心服务。

完成修改后，可在项目根目录运行后端与 SDK 测试：

```bash
source backend/.venv/bin/activate
python test/run_all_test.py
```

前端改动使用以下命令进行完整检查：

```bash
cd frontend
pnpm run check-all
```

## 🧰 仅使用 SDK

若只需 SDK 而不运行 Nexent 平台，可选择以下安装方式。

### 源码安装

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/sdk
uv pip install -e .
```

### 使用 uv 安装

```bash
uv add nexent
```

### 开发者安装（含工具链）

```bash
cd nexent/sdk
uv pip install -e ".[dev]"
```

开发依赖包含 ruff、pytest、数据处理依赖和其他项目工具。SDK 不直接读取平台环境变量；在独立项目中使用时，请通过构造参数或调用参数传入模型、存储和工具配置。
