#!/usr/bin/env bash
# Persistently set NORTHBOUND_EXTERNAL_URL for nexent (方案B: 改 chart + deploy.sh),
# and apply immediately to the running cluster.
#
# Why two file edits: deploy.sh renders northboundExternalUrl from the
# NORTHBOUND_EXTERNAL_URL env (default ""), which OVERRIDES the chart's
# values.yaml default. So we set BOTH:
#   1. chart values.yaml  -> persists for raw `helm upgrade`
#   2. deploy.sh default  -> persists for `deploy.sh` runs (when env unset)
# Env still wins if explicitly set (env_or_default semantics).
#
# Usage:  bash set-northbound-url.sh <url>
#   e.g.  bash set-northbound-url.sh http://71.9.15.12:30013/api
# Run from the nexent repo root (where deploy/ lives).
set -euo pipefail

URL="${1:-}"
NS="${NS:-nexent}"

if [ -z "$URL" ]; then
  echo "Usage: $0 <url>   (e.g. http://71.9.15.12:30013/api)"
  exit 1
fi
if [ ! -d deploy/k8s/helm ]; then
  echo "ERROR: run this from the nexent repo root (deploy/k8s/helm not found here)."
  exit 1
fi

VALUES="deploy/k8s/helm/nexent/charts/nexent-common/values.yaml"
DEPLOY_SH="deploy/k8s/deploy.sh"

echo "==> NORTHBOUND_EXTERNAL_URL = $URL"

# --- 1. chart values.yaml: config.services.northboundExternalUrl ---
python3 - "$VALUES" "$URL" <<'PY'
import sys, re, pathlib
path, url = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
s = p.read_text(encoding="utf-8")
pat = re.compile(r'^(\s*northboundExternalUrl:\s*).*$', re.M)
if not pat.search(s):
    sys.exit("ERROR: northboundExternalUrl line not found in " + path)
new = pat.sub(lambda m: f'{m.group(1)}"{url}"  # set by set-northbound-url.sh', s, count=1)
p.write_text(new, encoding="utf-8")
print("   patched chart:  " + path)
PY

# --- 2. deploy.sh: env_or_default NORTHBOUND_EXTERNAL_URL "" -> "<url>" ---
python3 - "$DEPLOY_SH" "$URL" <<'PY'
import sys, pathlib
path, url = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
s = p.read_text(encoding="utf-8")
old = 'env_or_default NORTHBOUND_EXTERNAL_URL ""'
new = f'env_or_default NORTHBOUND_EXTERNAL_URL "{url}"'
if old not in s:
    print("   WARN: deploy.sh default pattern not found (already changed?). Skipping deploy.sh edit.")
else:
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    print("   patched deploy: " + path)
PY

# --- 3. apply immediately to the running cluster (if already deployed) ---
echo "==> applying to live cluster (ns=$NS)"
if kubectl get cm nexent-config -n "$NS" >/dev/null 2>&1; then
  kubectl patch configmap nexent-config -n "$NS" --type merge \
    -p "{\"data\":{\"NORTHBOUND_EXTERNAL_URL\":\"$URL\"}}" >/dev/null
  kubectl rollout restart deploy/nexent-northbound -n "$NS" >/dev/null
  echo "   live ConfigMap patched + northbound restarting"
else
  echo "   (nexent-config ConfigMap not found in ns $NS — skipping live apply; it'll take effect on next deploy.sh/helm)"
fi

cat <<DONE
==> done.
   Persistent in: $VALUES  +  $DEPLOY_SH
   Next deploy.sh / helm upgrade will carry this URL (env unset -> uses $URL; env set -> env wins).
   Verify:
     curl -s ${URL%/api}/nb/a2a/<endpoint_id>/.well-known/agent-card.json | python3 -m json.tool | grep -A8 supportedInterfaces
DONE