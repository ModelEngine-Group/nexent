---
title: Environment Preparation
---

# Environment Preparation

This guide distinguishes between full-stack development and SDK-only usage. Complete the full-stack setup if you need to modify the web application or platform services. If you only need to use the Nexent SDK in a Python project, go directly to **SDK-Only Development**.

## 🧱 Common Requirements

- Python 3.11+
- Node.js 18.18+ and pnpm
- Docker and Docker Compose
- uv for Python package and virtual-environment management
- Git Bash, WSL, or another terminal that can run Bash scripts

::: info Windows Users
The project deployment scripts use Bash. Run deployment commands in Git Bash or WSL. Frontend and backend development commands can also be run separately in PowerShell.
:::

## 🧑‍💻 Full-Stack Nexent Development

### ⚙️ Infrastructure Deployment

From the repository root, start PostgreSQL, Redis, Elasticsearch, and MinIO:

```bash
bash deploy.sh docker --components infrastructure --port-policy development
```

::: info Important
Infrastructure mode generates a `.env` file in the repository root containing the service addresses and secrets required for local development. Do not commit this file or copy its sensitive values into documentation, logs, or chat Metadata.
:::

System-scoped runtime sandboxes are enabled by default. Keep Docker running when debugging tools or Skills that execute scripts.

### 🐍 Backend Dependencies

```bash
cd backend
uv sync --extra data-process --extra test
```

These commands create or update `backend/.venv`, install the backend dependencies, and install the local SDK in editable mode. Changes under `sdk/nexent/` do not require copying the package files again.

The `data-process` extra (and SDK `dev`) installs CPU PyTorch and Torchvision by default. Use uv 0.13.6, matching CI and image builds. Python remains 3.11; CI pins 3.11.15. The backend extras include the local SDK.

CPU and NVIDIA use the same dependencies and differ only in the selected preset index:

```bash
# From backend/: CPU is the default
uv sync --extra data-process --extra test
# Explicit CPU selection
uv sync --extra data-process --extra test --index pytorch-cpu --upgrade-package torch --upgrade-package torchvision
# NVIDIA CUDA 13.0
uv sync --extra data-process --extra test --index pytorch-nvidia --upgrade-package torch --upgrade-package torchvision
```

The project enables uv's `index-by-name` preview feature. The CPU index is first by default; `--index` promotes the selected preset. The NVIDIA index is explicit and only participates when selected. Active indexes participate in `unsafe-first-match` resolution, including dependencies other than Torch: the first source with compatible versions wins; incompatible old shared dependencies fall through to the next source. `--default-index` changes the fallback package mirror and does not override the selected PyTorch index. Base installations without document-processing extras do not install PyTorch. An existing lockfile can retain its previous Torch build despite a different index priority. The explicit commands above re-resolve Torch and Torchvision with `--upgrade-package`; do not use `--frozen` to switch variants. `uv sync` removes obsolete dependencies. CUDA installation does not verify GPU hardware or driver compatibility.

For standalone SDK development, run `uv sync --python 3.11 --extra dev` from `sdk/` for CPU, or add `--index pytorch-nvidia --upgrade-package torch --upgrade-package torchvision` for NVIDIA. Use `--index pytorch-cpu` with the same upgrade flags to switch back. There is no separate `nvidia` extra.

For SDK packages installed from a registry, wheel metadata does not carry the checkout's uv index configuration. Select the backend explicitly:

```bash
uv pip install "nexent[data-process]" --torch-backend cpu
uv pip install "nexent[data-process]" --torch-backend cu130
```

#### Optional: Use Package Mirrors

When network access is limited, specify a package mirror for uv. For example:

```bash
# Tsinghua mirror
uv sync --extra data-process --extra test --default-index https://pypi.tuna.tsinghua.edu.cn/simple

# Alibaba Cloud mirror
uv sync --extra data-process --extra test --default-index https://mirrors.aliyun.com/pypi/simple/

# Multiple sources (recommended)
uv sync --extra data-process --extra test --index pytorch-cpu --index https://pypi.tuna.tsinghua.edu.cn/simple --index https://mirrors.aliyun.com/pypi/simple/ --upgrade-package torch --upgrade-package torchvision
```

:::: info Mirror References
- Tsinghua: `https://pypi.tuna.tsinghua.edu.cn/simple`
- Alibaba Cloud: `https://mirrors.aliyun.com/pypi/simple/`
- University of Science and Technology of China: `https://pypi.mirrors.ustc.edu.cn/simple/`
- Douban: `https://pypi.douban.com/simple/`

Using multiple sources can improve installation reliability.
::::

### ⚛️ Frontend Dependencies

```bash
cd frontend
pnpm install
pnpm dev
```

The development server listens on the port configured by the project. After the terminal displays the address, open it in a browser. The page refreshes automatically when frontend code changes.

### 🏃 Start Services

Run each backend service in a separate terminal. First switch to the repository root and activate the backend virtual environment:

```bash
source backend/.venv/bin/activate
```

On Windows PowerShell:

```powershell
.\backend\.venv\Scripts\Activate.ps1
```

On Windows Git Bash:

```bash
source backend/.venv/Scripts/activate
```

Then start the services you need to debug from the repository root. The services use `python-dotenv` to read `.env` from the repository root. If an environment variable with the same name is already set in the terminal, the terminal value is preserved.

```bash
python backend/mcp_service.py
python backend/data_process_service.py
python backend/config_service.py
python backend/runtime_service.py
python backend/northbound_service.py
```

| Service | Primary Responsibility |
| --- | --- |
| `mcp_service.py` | Built-in tool and MCP tool APIs |
| `data_process_service.py` | Document parsing, chunking, and vectorization tasks |
| `config_service.py` | Model, agent, knowledge-base, and resource configuration APIs |
| `runtime_service.py` | Agent execution and streaming chat |
| `northbound_service.py` | Northbound APIs for external systems |

When debugging one module, you can start only the services it depends on. Start all core services when you need to use the complete platform.

After making changes, run the backend and SDK tests from the repository root:

```bash
source backend/.venv/bin/activate
python test/run_all_test.py
```

Run the complete frontend check with:

```bash
cd frontend
pnpm run check-all
```

## 🧰 SDK-Only Development

If you only need the SDK and do not need to run the Nexent platform, choose one of the following installation methods.

### Install from Source

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/sdk
uv pip install -e .
```

### Install with uv

```bash
uv add nexent
```

### Development Installation with Tooling

```bash
cd nexent/sdk
uv pip install -e ".[dev]"
```

Development dependencies include ruff, pytest, data-processing dependencies, and other project tools. The SDK does not read platform environment variables directly. When using it in a standalone project, pass model, storage, and tool configuration through constructors or call parameters.
