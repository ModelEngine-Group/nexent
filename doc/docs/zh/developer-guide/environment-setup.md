---
title: 环境准备
---

# 环境准备

本指南拆分了全栈开发与仅使用 SDK 的两类场景，按需选择路径完成环境准备。

## 🧱 通用要求

- Python 3.10+
- Node.js 18+
- Docker & Docker Compose
- uv（Python 包管理器）
- pnpm（Node.js 包管理器）

## 🧑‍💻 全栈 Nexent 开发

### ⚙️ 基础设施部署

先启动数据库、缓存、向量库、存储等核心服务。

```bash
# 在项目根目录的 docker 目录执行
cd docker
./deploy.sh --components infrastructure --port-policy development
```

:::: info 重要提示
基础设施模式会启动 PostgreSQL、Redis、Elasticsearch、MinIO，并在项目根生成 `.env`（包含生成的密钥与本地地址）。所有服务默认指向 localhost 便于本地开发。
::::

### 🐍 后端依赖

```bash
cd backend
uv sync --all-extras
uv pip install ../sdk
```

:::: tip 说明
`--all-extras` 安装所有可选依赖（数据处理、测试等），随后安装本地 SDK 包。
::::

#### 可选：镜像加速

```bash
# 清华源
uv sync --all-extras --default-index https://pypi.tuna.tsinghua.edu.cn/simple
uv pip install ../sdk --default-index https://pypi.tuna.tsinghua.edu.cn/simple

# 阿里云
uv sync --all-extras --default-index https://mirrors.aliyun.com/pypi/simple/
uv pip install ../sdk --default-index https://mirrors.aliyun.com/pypi/simple/

# 多源（推荐）
uv sync --all-extras --index https://pypi.tuna.tsinghua.edu.cn/simple --index https://mirrors.aliyun.com/pypi/simple/
uv pip install ../sdk --index https://pypi.tuna.tsinghua.edu.cn/simple --index https://mirrors.aliyun.com/pypi/simple/
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

### 🏃 服务启动

先激活后端虚拟环境：

```bash
cd backend
source .venv/bin/activate
```

:::: warning 提示
Windows 请使用 `source .venv/Scripts/activate`。
::::

在项目根依次启动核心服务：

```bash
source .env && python backend/mcp_service.py
source .env && python backend/data_process_service.py
source .env && python backend/config_service.py
source .env && python backend/runtime_service.py
```

:::: warning 提示
需在项目根执行，并先 `source .env`。确保数据库、Redis、Elasticsearch、MinIO 已就绪。
::::

## 🧰 仅使用 SDK

若只需 SDK 而不运行全栈，可直接安装。

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

包含：

- 代码质量工具（ruff）
- 测试框架（pytest）
- 数据处理依赖（unstructured）
- 其他开发辅助依赖
