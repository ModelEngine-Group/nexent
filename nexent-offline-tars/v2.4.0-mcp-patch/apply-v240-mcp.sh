#!/usr/bin/env bash
# Mount v2.4.0 patches (SSL + metadata + artifacts parsing + security credentials).
# 7 files, idempotent per-mount.
#
# model_id 参数(可选):第一个参数或 MODEL 环境变量。
set -euo pipefail
NS="${NS:-nexent}"
MODEL="${1:-${MODEL:-}}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CM="nexent-v240-mcp"
VOL="nexent-mcp-patch"
VENV="/opt/backend/.venv/lib/python3.11/site-packages/nexent/core/agents"
AGENTS="/opt/backend/agents"
DATABASE="/opt/backend/database"
UTILS="/opt/backend/utils"
SVC="/opt/backend/services"
ALL="nexent-config nexent-runtime nexent-northbound"
EXEC="nexent-runtime nexent-northbound"

echo "==> NS=$NS  CM=$CM  model=${MODEL:-<none>}"

# sanity
for f in run_agent.py a2a_http_client.py a2a_client_service.py a2a_agent_proxy.py agent_model.py create_agent_info.py a2a_agent_db.py; do
  [ -f "$DIR/$f" ] || { echo "ERROR: missing $DIR/$f"; exit 1; }
done

# ConfigMap
echo "==> creating ConfigMap $CM"
kubectl delete cm "$CM" -n "$NS" 2>/dev/null || true
kubectl create configmap "$CM" -n "$NS" \
  --from-file=run_agent.py="$DIR/run_agent.py" \
  --from-file=a2a_http_client.py="$DIR/a2a_http_client.py" \
  --from-file=a2a_client_service.py="$DIR/a2a_client_service.py" \
  --from-file=a2a_agent_proxy.py="$DIR/a2a_agent_proxy.py" \
  --from-file=agent_model.py="$DIR/agent_model.py" \
  --from-file=create_agent_info.py="$DIR/create_agent_info.py" \
  --from-file=a2a_agent_db.py="$DIR/a2a_agent_db.py"

# helpers
ev() { local dep="$1" has; has="$(kubectl get deploy "$dep" -n "$NS" -o jsonpath='{.spec.template.spec.volumes[?(@.name=="'"$VOL"'")].name}' 2>/dev/null||true)"
  [ -z "$has" ] && kubectl patch deploy "$dep" -n "$NS" --type=json -p='[{"op":"add","path":"/spec/template/spec/volumes/-","value":{"name":"'"$VOL"'","configMap":{"name":"'"$CM"'"}}}]' >/dev/null || true; }
em() { local dep="$1" sp="$2" mp="$3" has; has="$(kubectl get deploy "$dep" -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].volumeMounts[?(@.subPath=="'"$sp"'")].name}' 2>/dev/null||true)"
  if [ -z "$has" ]; then kubectl patch deploy "$dep" -n "$NS" --type=json -p='[{"op":"add","path":"/spec/template/spec/containers/0/volumeMounts/-","value":{"name":"'"$VOL"'","mountPath":"'"$mp"'","subPath":"'"$sp"'"}}]' >/dev/null; echo "   $dep: $sp"; else echo "   $dep: $sp (skip)"; fi; }
mount_on() { local pods="$1" sp="$2" mp="$3"; for d in $pods; do ev "$d"; em "$d" "$sp" "$mp"; done; }

echo "==> mounting"
# config: SSL + metadata(config API)
mount_on "nexent-config" a2a_http_client.py "$UTILS/a2a_http_client.py"
mount_on "nexent-config" a2a_client_service.py "$SVC/a2a_client_service.py"
# runtime + northbound: all 7
mount_on "$EXEC" run_agent.py "$VENV/run_agent.py"
mount_on "$EXEC" a2a_http_client.py "$UTILS/a2a_http_client.py"
mount_on "$EXEC" a2a_client_service.py "$SVC/a2a_client_service.py"
mount_on "$EXEC" a2a_agent_proxy.py "$VENV/a2a_agent_proxy.py"
mount_on "$EXEC" agent_model.py "$VENV/agent_model.py"
mount_on "$EXEC" create_agent_info.py "$AGENTS/create_agent_info.py"
mount_on "$EXEC" a2a_agent_db.py "$DATABASE/a2a_agent_db.py"

# model_id env
echo "==> model=${MODEL:-<none>}"
for dep in $ALL; do
  if [ -n "$MODEL" ]; then kubectl set env deploy/"$dep" -n "$NS" NEXENT_A2A_SEND_MODEL="$MODEL" >/dev/null
  else kubectl set env deploy/"$dep" -n "$NS" NEXENT_A2A_SEND_MODEL- >/dev/null 2>&1||true; fi
done

# rollout
for dep in $ALL; do kubectl rollout restart deploy "$dep" -n "$NS"; done
for dep in $ALL; do kubectl rollout status deploy "$dep" -n "$NS"; done

# verify
echo "==> verify (each >=1)"
for dep in $ALL; do
  pod="$(kubectl get pods -n "$NS" -o name|grep "^pod/${dep}-"|head -1|sed 's|pod/||' || true)"
  echo "== $dep =="
  [ "$dep" != "nexent-config" ] && echo "   run_agent  : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c _ac_init_skip_verify '$VENV/run_agent.py'" 2>/dev/null||echo F)"
  echo "   http_ssl   : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c 'skip TLS' $UTILS/a2a_http_client.py" 2>/dev/null||echo F)"
  [ "$dep" = "nexent-config" ] && echo "   cfg_meta   : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c NEXENT_A2A_SEND_MODEL $SVC/a2a_client_service.py" 2>/dev/null||echo F)"
  [ "$dep" != "nexent-config" ] && {
    echo "   proxy_meta : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c NEXENT_A2A_SEND_MODEL '$VENV/a2a_agent_proxy.py'" 2>/dev/null||echo F)"
    echo "   artifacts  : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c _find_text_in_artifacts '$VENV/a2a_agent_proxy.py'" 2>/dev/null||echo F)"
    echo "   sec_hdrs   : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c _build_security_headers $AGENTS/create_agent_info.py" 2>/dev/null||echo F)"
    echo "   db_sec     : $(kubectl exec -n "$NS" "$pod" -- sh -c "grep -c security_credentials $DATABASE/a2a_agent_db.py" 2>/dev/null||echo F)"
  }
done
echo "==> done. 7 patches: SSL + metadata + artifacts + security credentials."
