#!/usr/bin/env bash
set -euo pipefail

NS="${NS:-nexent}"
DEPLOYMENTS="${DEPLOYMENTS:-nexent-runtime nexent-northbound}"
CERT="${CERT:-/root/CampusCA.pem}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_FILE="${SCRIPT_DIR}/ca-patch.json"

echo "==> namespace:   $NS"
echo "==> deployments: $DEPLOYMENTS"
echo "==> cert:        $CERT"
echo "==> patch file:  $PATCH_FILE"

# 0) sanity check
[ -f "$CERT" ]        || { echo "ERROR: cert not found: $CERT"; exit 1; }
[ -f "$PATCH_FILE" ]  || { echo "ERROR: patch not found: $PATCH_FILE"; exit 1; }

# 1) (re)create ConfigMap from the CA cert
if kubectl get cm campus-ca -n "$NS" >/dev/null 2>&1; then
  echo "==> cm campus-ca exists, recreating"
  kubectl delete cm campus-ca -n "$NS"
fi
kubectl create configmap campus-ca -n "$NS" --from-file=ca.crt="$CERT"

# 2) patch deployments (idempotent: skip if volume already present)
for D in $DEPLOYMENTS; do
  HAS_VOL="$(kubectl get deploy "$D" -n "$NS" -o jsonpath='{.spec.template.spec.volumes[?(@.name=="campus-ca")].name}' 2>/dev/null || true)"
  if [ -n "$HAS_VOL" ]; then
    echo "==> $D: campus-ca volume already present, skip patch"
  else
    echo "==> $D: applying patch"
    kubectl patch deployment "$D" -n "$NS" --type=json --patch-file="$PATCH_FILE"
  fi
done

# 3) rollout
for D in $DEPLOYMENTS; do
  kubectl rollout restart deployment "$D" -n "$NS"
done
for D in $DEPLOYMENTS; do
  kubectl rollout status  deployment "$D" -n "$NS"
done

# 4) verify env + mounted cert in each pod
for P in $DEPLOYMENTS; do
  POD="$(kubectl get pods -n "$NS" -o name | grep "^pod/${P}-" | head -1 | sed 's|pod/||' || true)"
  echo "== $P ($POD) =="
  kubectl exec -n "$NS" "$POD" -- sh -c 'echo "SSL_CERT_FILE=$SSL_CERT_FILE"; ls -l "$SSL_CERT_FILE" 2>/dev/null && openssl x509 -in "$SSL_CERT_FILE" -noout -subject 2>/dev/null' || true
  echo
done
echo "==> done. Now test: 1) a normal chat (no MCP) -> model still works?  2) an MCP agent -> no cert error?"
