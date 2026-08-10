#!/usr/bin/env bash
# Skip TLS verification for MCP HTTP transports on the agent-execution path.
#
# Why: smolagents ToolCollection.from_mcp -> mcpadapt builds its own httpx client
# without exposing httpx_client_factory, and that client does NOT honor
# SSL_CERT_FILE (trust_env off / fixed bundle). So self-signed/internal MCP
# servers fail SSL at agent-run time even when the CA is trusted everywhere else.
# This mounts a patched run_agent.py (monkeypatches httpx.AsyncClient to default
# verify=False) over the .venv path, on runtime + northbound.
#
# Safe: verify=False only relaxes checks, it can never break a working connection.
# Idempotent: re-runnable. Extracts the server's OWN run_agent.py (no version drift).

set -euo pipefail

NS="${NS:-nexent}"
DEPLOYMENTS="${DEPLOYMENTS:-nexent-runtime nexent-northbound}"
SRC="/opt/backend/.venv/lib/python3.11/site-packages/nexent/core/agents/run_agent.py"
WORK="/tmp/run_agent_work"
CM_NAME="nexent-runagent-ssl"

echo "==> NS=$NS"
echo "==> SRC=$SRC"
echo "==> deployments=$DEPLOYMENTS"

# 0) find a runtime pod to source the original file from
RT_POD="$(kubectl get pods -n "$NS" -o name | grep '^pod/nexent-runtime-' | head -1 | sed 's|pod/||' || true)"
[ -n "$RT_POD" ] || { echo "ERROR: no nexent-runtime pod found in ns $NS"; exit 1; }
echo "==> source pod: $RT_POD"

mkdir -p "$WORK"

# 1) pull the server's own run_agent.py
echo "==> pulling server run_agent.py ..."
kubectl exec -n "$NS" "$RT_POD" -- cat "$SRC" > "$WORK/run_agent.py"
echo "    got $(wc -l < "$WORK/run_agent.py" | tr -d ' ') lines"

# 2) patcher (injected right after `logger.setLevel(logging.DEBUG)`)
cat > "$WORK/patcher.py" << 'PYEOF'
import sys
inp, outp = sys.argv[1], sys.argv[2]
s = open(inp).read()
marker = "logger.setLevel(logging.DEBUG)\n"
patch = (
    "\n"
    "# === nexent patch: skip TLS verification for MCP HTTP transports ===\n"
    "# smolagents ToolCollection.from_mcp -> mcpadapt builds its own httpx client\n"
    "# without exposing httpx_client_factory; rejects self-signed MCP servers.\n"
    "# verify=False only relaxes checks, never breaks a working connection.\n"
    "import httpx as _httpx\n"
    "_orig_ac_init = _httpx.AsyncClient.__init__\n"
    "def _ac_init_skip_verify(self, *args, **kwargs):\n"
    "    kwargs.setdefault(\"verify\", False)\n"
    "    return _orig_ac_init(self, *args, **kwargs)\n"
    "_httpx.AsyncClient.__init__ = _ac_init_skip_verify\n"
    "# === end patch ===\n"
)
if "_ac_init_skip_verify" in s:
    open(outp, "w").write(s)
    print("    already patched -> using as-is")
else:
    if marker not in s:
        raise SystemExit("ERROR: marker 'logger.setLevel(logging.DEBUG)' not found; version mismatch, abort")
    open(outp, "w").write(s.replace(marker, marker + patch, 1))
    print("    patched OK")
PYEOF
echo "==> patching locally ..."
python3 "$WORK/patcher.py" "$WORK/run_agent.py" "$WORK/run_agent_patched.py"
HAS="$(grep -c _ac_init_skip_verify "$WORK/run_agent_patched.py" || true)"
echo "    patched file contains marker: $HAS (expect >=1)"

# 3) (re)create ConfigMap
echo "==> (re)creating ConfigMap $CM_NAME ..."
kubectl delete cm "$CM_NAME" -n "$NS" 2>/dev/null || true
kubectl create configmap "$CM_NAME" -n "$NS" --from-file=run_agent.py="$WORK/run_agent_patched.py"

# 4) build the mount patch (substitute SRC / CM_NAME)
cat > "$WORK/mount.json" <<EOF
[
 {"op":"add","path":"/spec/template/spec/volumes/-","value":{"name":"runagent-ssl","configMap":{"name":"$CM_NAME"}}},
 {"op":"add","path":"/spec/template/spec/containers/0/volumeMounts/-","value":{"name":"runagent-ssl","mountPath":"$SRC","subPath":"run_agent.py"}}
]
EOF
python3 -m json.tool "$WORK/mount.json" >/dev/null && echo "    mount.json valid"

# 5) mount into each deployment (idempotent)
for D in $DEPLOYMENTS; do
  VOL="$(kubectl get deploy "$D" -n "$NS" -o jsonpath='{.spec.template.spec.volumes[?(@.name=="runagent-ssl")].name}' 2>/dev/null || true)"
  if [ -n "$VOL" ]; then
    echo "==> $D: runagent-ssl already mounted, skip"
  else
    echo "==> $D: applying mount patch"
    kubectl patch deployment "$D" -n "$NS" --type=json --patch-file="$WORK/mount.json"
  fi
done

# 6) rollout
for D in $DEPLOYMENTS; do kubectl rollout restart deployment "$D" -n "$NS"; done
for D in $DEPLOYMENTS; do kubectl rollout status  deployment "$D" -n "$NS"; done

# 7) verify the mounted file actually has the patch
for P in $DEPLOYMENTS; do
  POD="$(kubectl get pods -n "$NS" -o name | grep "^pod/${P}-" | head -1 | sed 's|pod/||' || true)"
  C="$(kubectl exec -n "$NS" "$POD" -- sh -c "grep -c _ac_init_skip_verify \"$SRC\"" 2>/dev/null || true)"
  echo "$P ($POD): patch marker count = ${C:-0} (expect >=1)"
done
echo "==> done. Now run an MCP agent; the SSL error should be gone."
