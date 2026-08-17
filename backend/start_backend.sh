#!/bin/bash
export PYTHONPATH=/home/jason/Workspace/Huawei-Agentic/worktrees/external_memory_contract/sdk:/home/jason/Workspace/Huawei-Agentic/worktrees/external_memory_contract/backend:$PYTHONPATH
exec /home/jason/Workspace/Huawei-Agentic/nexent/backend/.venv/bin/python -m uvicorn apps.config_app:app --host 0.0.0.0 --port 5010 --reload-dir /home/jason/Workspace/Huawei-Agentic/worktrees/external_memory_contract/backend
