---
title: Environment Preparation
---

# Environment Preparation

Use this guide to prepare your environment before developing with Nexent. It separates full-stack project setup from SDK-only workflows so you can follow the path that fits your role.

## 🧱 Common Requirements

- Python 3.10+
- Node.js 18+
- Docker & Docker Compose
- `uv` (Python package manager)
- `pnpm` (Node.js package manager)

## 🧑‍💻 Full-Stack Nexent Development

### 1. Infrastructure Deployment

Before backend work, start core services (PostgreSQL, Redis, Elasticsearch, MinIO, etc.).

```bash
# Run from the docker directory at the project root
cd docker
./deploy.sh --mode infrastructure
```

:::: info Important Notes
Infrastructure mode launches PostgreSQL, Redis, Elasticsearch, and MinIO. The script generates required credentials and saves them in the project root `.env`. URLs are configured as localhost endpoints for easy local development.
::::

### 2. Backend Setup

```bash
# Run inside the backend directory
cd backend
uv sync --all-extras
uv pip install ../sdk
```

:::: tip Notes
`--all-extras` installs every optional dependency (data processing, testing, etc.). After syncing, install the local SDK package.
::::

#### Optional: Accelerate with Mirror Sources

If downloads are slow, use domestic mirrors:

```bash
# Tsinghua mirror
uv sync --all-extras --default-index https://pypi.tuna.tsinghua.edu.cn/simple
uv pip install ../sdk --default-index https://pypi.tuna.tsinghua.edu.cn/simple

# Alibaba Cloud mirror
uv sync --all-extras --default-index https://mirrors.aliyun.com/pypi/simple/
uv pip install ../sdk --default-index https://mirrors.aliyun.com/pypi/simple/

# Multiple mirrors (recommended)
uv sync --all-extras --index https://pypi.tuna.tsinghua.edu.cn/simple --index https://mirrors.aliyun.com/pypi/simple/
uv pip install ../sdk --index https://pypi.tuna.tsinghua.edu.cn/simple --index https://mirrors.aliyun.com/pypi/simple/
```

:::: info Mirror Source Reference
- Tsinghua: `https://pypi.tuna.tsinghua.edu.cn/simple`
- Alibaba Cloud: `https://mirrors.aliyun.com/pypi/simple/`
- USTC: `https://pypi.mirrors.ustc.edu.cn/simple/`
- Douban: `https://pypi.douban.com/simple/`
Using multiple mirrors improves success rates.
::::

### 3. Frontend Setup

```bash
# Run inside the frontend directory
cd frontend
pnpm install
pnpm dev
```

### 4. Service Startup

Activate the backend virtual environment before starting services.

```bash
# Run inside backend directory
cd backend
source .venv/bin/activate
```

:::: warning Important Notes
On Windows, activate the environment with `source .venv/Scripts/activate`.
::::

Start the backend services from the project root, in order:

```bash
# Always run from project root with environment variables loaded
source .env && python backend/mcp_service.py
source .env && python backend/data_process_service.py
source .env && python backend/config_service.py
source .env && python backend/runtime_service.py
```

:::: warning Important Notes
Each command must run from the project root and be prefixed with `source .env`. Ensure databases, Redis, Elasticsearch, and MinIO (from infrastructure mode) are healthy first.
::::

## 🧰 SDK-Only Development

If you only need the SDK (without running the entire stack), install it directly.

### 1. Install from Source

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/sdk
uv pip install -e .
```

### 2. Install with uv

```bash
uv add nexent
```

### 3. Development Extras

For SDK contributors, install with development dependencies:

```bash
cd nexent/sdk
uv pip install -e ".[dev]"
```

This adds:

- Code quality tools (ruff)
- Testing framework (pytest)
- Data processing dependencies (unstructured)
- Other developer utilities

