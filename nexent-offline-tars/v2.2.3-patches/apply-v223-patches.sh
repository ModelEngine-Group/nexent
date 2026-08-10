#!/usr/bin/env bash
# Mount v2.2.3 patches into runtime + northbound via a single ConfigMap + subPath
# volumeMounts. Idempotent per-mount (safe to re-run; adds only missing mounts).
# Patches:
#   nexent_agent.py        - import whitelist (os/urllib/requests/...)
#   run_agent.py           - httpx verify=False (skip MCP TLS verify)
#   a2a_agent_adapter.py   - A2A stream filter (final_answer + thinking only)
#   a2a_server_service.py  - wrap thinking into {"thinking_content":"..."} JSON block
set -euo pipefail

NS="${NS:-nexent}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CM="nexent-v223-patches"
VOL="nexent-patches"
VENV="/opt/backend/.venv/lib/python3.11/site-packages/nexent/core/agents"

echo "==> NS=$NS  ConfigMap=$CM  Volume=$VOL"

# 0) sanity: patched files present
for f in nexent_agent.py run_agent.py a2a_agent_adapter.py a2a_server_service.py; do
  [ -f "$DIR/$f" ] || { echo "ERROR: missing $DIR/$f"; exit 1; }
done

# 1) (re)create ConfigMap with the 4 patched files
echo "==> creating ConfigMap $CM"
kubectl delete cm "$CM" -n "$NS" 2>/dev/null || true
kubectl create configmap "$CM" -n "$NS" \
  --from-file=nexent_agent.py="$DIR/nexent_agent.py" \
  --from-file=run_agent.py="$DIR/run_agent.py" \
  --from-file=a2a_agent_adapter.py="$DIR/a2a_agent_adapter.py" \
  --from-file=a2a_server_service.py="$DIR/a2a_server_service.py"

# helpers: idempotent per-item add
ensure_volume() {
  local dep="$1"
  local has
  has="$(kubectl get deploy "$dep" -n "$NS" -o jsonpath='{.spec.template.spec.volumes[?(@.name=="'"$VOL"'")].name}' 2>/dev/null || true)"
  if [ -z "$has" ]; then
    echo "   $dep: add volume $VOL"
    kubectl patch deploy "$dep" -n "$NS" --type=json \
      -p='[{"op":"add","path":"/spec/template/spec/volumes/-","value":{"name":"'"$VOL"'","configMap":{"name":"'"$CM"'"}}}]' >/dev/null
  fi
}

ensure_mount() {
  local dep="$1" subpath="$2" mountpath="$3"
  local has
  has="$(kubectl get deploy "$dep" -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].volumeMounts[?(@.subPath=="'"$subpath"'")].name}' 2>/dev/null || true)"
  if [ -z "$has" ]; then
    echo "   $dep: add mount $subpath -> $mountpath"
    kubectl patch deploy "$dep" -n "$NS" --type=json \
      -p='[{"op":"add","path":"/spec/template/spec/containers/0/volumeMounts/-","value":{"name":"'"$VOL"'","mountPath":"'"$mountpath"'","subPath":"'"$subpath"'"}}]' >/dev/null
  else
    echo "   $dep: mount $subpath already present, skip"
  fi
}

# 2) apply mounts (runtime: agent files; northbound: agent files + a2a files)
echo "==> ensuring mounts"
ensure_volume nexent-runtime
ensure_mount  nexent-runtime nexent_agent.py "$VENV/nexent_agent.py"
ensure_mount  nexent-runtime run_agent.py    "$VENV/run_agent.py"

ensure_volume nexent-northbound
ensure_mount  nexent-northbound nexent_agent.py      "$VENV/nexent_agent.py"
ensure_mount  nexent-northbound run_agent.py         "$VENV/run_agent.py"
ensure_mount  nexent-northbound a2a_agent_adapter.py "/opt/backend/services/a2a_agent_adapter.py"
ensure_mount  nexent-northbound a2a_server_service.py "/opt/backend/services/a2a_server_service.py"

# 3) rollout
for dep in nexent-runtime nexent-northbound; do
  kubectl rollout restart deploy "$dep" -n "$NS"
done
for dep in nexent-runtime nexent-northbound; do
  kubectl rollout status deploy "$dep" -n "$NS"
done

# 4) verify the mounted files actually have the patches
for dep in nexent-runtime nexent-northbound; do
  pod="$(kubectl get pods -n "$NS" -o name | grep "^pod/${dep}-" | head -1 | sed 's|pod/||' || true)"
  echo "== $dep ($pod) =="
  echo "   whitelist : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c 'socket.*requests' '$VENV/nexent_agent.py'" 2>/dev/null || echo FAIL)"
  echo "   ssl-skip  : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c _ac_init_skip_verify '$VENV/run_agent.py'" 2>/dev/null || echo FAIL)"
  if [ "$dep" = "nexent-northbound" ]; then
    echo "   a2a-fltr  : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c 'for A2A consumers' /opt/backend/services/a2a_agent_adapter.py" 2>/dev/null || echo FAIL)"
    echo "   thinking  : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c thinking_content /opt/backend/services/a2a_server_service.py" 2>/dev/null || echo FAIL)"
  fi
done
echo "==> done."
echo "    Test 1: agent calling a self-signed MCP -> no SSL timeout (run_agent patch)."
echo "    Test 2: A2A stream -> thinking wrapped in {\"thinking_content\":\"...\"}, final answer raw."
