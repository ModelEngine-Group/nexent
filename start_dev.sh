#!/bin/bash

# 设置项目根目录路径（建议使用绝对路径或确保脚本在根目录运行）
PROJECT_ROOT="F:/PythonProject/nexent-develop"
VENV_PYTHON="backend/.venv/Scripts/python"

echo "🚀 正在通过 mintty 启动 Nexent 服务..."

# 1. 启动 MCP Service
mintty -p 100,100 -t "MCP-Service" bash -c "cd $PROJECT_ROOT && source .env && $VENV_PYTHON backend/mcp_service.py; exec bash" &

# 2. 启动 Config Service
mintty -p 500,100 -t "Config-Service" bash -c "cd $PROJECT_ROOT && source .env && $VENV_PYTHON backend/config_service.py; exec bash" &

# 3. 启动 Runtime Service
mintty -p 100,500 -t "Runtime-Service" bash -c "cd $PROJECT_ROOT && source .env && $VENV_PYTHON backend/runtime_service.py; exec bash" &


echo "✅ 4 个独立的窗口已在 $PROJECT_ROOT 路径下启动。"