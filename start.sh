#!/bin/bash

KEYS=("ROOT_DIR" "NEXENT_MCP_DOCKER_IMAGE" "MINIO_ACCESS_KEY" 
"MINIO_SECRET_KEY" "JWT_SECRET" "SECRET_KEY_BASE" "VAULT_ENC_KEY" 
"SUPABASE_KEY" "SERVICE_ROLE_KEY" "ELASTICSEARCH_API_KEY")

for k in "${KEYS[@]}"; do
    val=$(grep "^$k=" deploy/env/.env | cut -d= -f2-)
    if [ -n "$val" ]; then
        grep -q "^$k=" .env \
          && sed -i "s|^$k=.*|$k=$val|" .env \
          || echo "$k=$val" >> .env
    fi
done

sed -i 's|^SUPABASE_URL=.*|SUPABASE_URL=http://localhost:8000/|' .env
sed -i 's|^API_EXTERNAL_URL=.*|API_EXTERNAL_URL=http://localhost:8000/|' .env

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "" > app.log
if [ -f "backend/.venv/Scripts/python.exe" ]; then
    VENV_PYTHON="backend/.venv/Scripts/python.exe"
elif [ -f "backend/.venv/bin/python" ]; then
    VENV_PYTHON="backend/.venv/bin/python"
else
    echo "ERROR: venv Python not found..."
    exit 1
fi

"$VENV_PYTHON" backend/runtime_service.py   # 或 config_service.py
