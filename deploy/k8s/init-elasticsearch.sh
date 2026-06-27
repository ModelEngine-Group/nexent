#!/bin/bash
# Script to initialize Elasticsearch API key for Nexent

NAMESPACE=nexent
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ROOT_ENV_FILE="${ROOT_ENV_FILE:-$DEPLOY_ROOT/env/.env}"
DEPLOYMENT_COMMON="$DEPLOY_ROOT/common/common.sh"

if [ -f "$DEPLOYMENT_COMMON" ]; then
  # shellcheck source=/dev/null
  source "$DEPLOYMENT_COMMON"
fi

decode_base64() {
  if base64 --help 2>&1 | grep -q -- '--decode'; then
    base64 --decode
  else
    base64 -D
  fi
}

get_secret_value() {
  local key="$1"
  local encoded_value
  encoded_value=$(kubectl get secret nexent-secrets -n $NAMESPACE -o jsonpath="{.data.${key}}" 2>/dev/null || true)
  [ -n "$encoded_value" ] || return 1
  printf '%s' "$encoded_value" | decode_base64
}

validate_api_key() {
  local api_key="$1"
  local http_code
  [ -n "$api_key" ] || return 1
  http_code=$(kubectl exec -n $NAMESPACE deploy/nexent-elasticsearch -- sh -c "curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: ApiKey $api_key' 'http://localhost:9200/_security/_authenticate'" 2>/dev/null || true)
  [ "$http_code" = "200" ]
}
write_api_key_output() {
  local api_key="$1"
  if [ -n "${ELASTICSEARCH_API_KEY_OUTPUT_FILE:-}" ]; then
    umask 077
    printf '%s' "$api_key" > "$ELASTICSEARCH_API_KEY_OUTPUT_FILE"
  else
    echo "ELASTICSEARCH_API_KEY=$api_key"
  fi
}

sync_api_key_to_root_env() {
  local api_key="$1"

  if [ "${NEXENT_SYNC_ES_KEY_TO_ENV:-true}" != "true" ]; then
    return 0
  fi

  if command -v deployment_update_env_var_file >/dev/null 2>&1; then
    deployment_update_env_var_file "$ROOT_ENV_FILE" "ELASTICSEARCH_API_KEY" "$api_key"
  else
    touch "$ROOT_ENV_FILE"
    local escaped_value
    escaped_value=$(printf '%s' "$api_key" | sed -e 's/\\/\\\\/g' -e 's/&/\\&/g')
    if grep -q '^ELASTICSEARCH_API_KEY=' "$ROOT_ENV_FILE"; then
      sed -i.bak "s~^ELASTICSEARCH_API_KEY=.*~ELASTICSEARCH_API_KEY=\"${escaped_value}\"~" "$ROOT_ENV_FILE"
      rm -f "${ROOT_ENV_FILE}.bak"
    else
      printf 'ELASTICSEARCH_API_KEY="%s"\n' "$api_key" >> "$ROOT_ENV_FILE"
    fi
  fi

  echo "ELASTICSEARCH_API_KEY synchronized to $ROOT_ENV_FILE."
}

# Get elastic password from secret
ELASTIC_PASSWORD=$(get_secret_value "ELASTIC_PASSWORD")

echo "Waiting for Elasticsearch to be ready..."

# Wait for Elasticsearch to be healthy
until kubectl exec -n $NAMESPACE deploy/nexent-elasticsearch -- curl -s -u "elastic:$ELASTIC_PASSWORD" "http://localhost:9200/_cluster/health" 2>/dev/null | grep -q '"status":"green"\|"status":"yellow"'; do
  echo "Elasticsearch is unavailable - sleeping"
  sleep 5
done
echo "Elasticsearch is ready."

EXISTING_API_KEY="$(get_secret_value "ELASTICSEARCH_API_KEY" 2>/dev/null || true)"
if [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" != "true" ] && [ "${DEPLOYMENT_REFRESH_ES_KEY:-false}" != "true" ] && [ -n "$EXISTING_API_KEY" ]; then
  echo "Validating existing ELASTICSEARCH_API_KEY..."
  if validate_api_key "$EXISTING_API_KEY"; then
    echo "Existing ELASTICSEARCH_API_KEY is valid; keeping current Helm-managed value."
    write_api_key_output "$EXISTING_API_KEY"
    exit 0
  fi
  echo "Existing ELASTICSEARCH_API_KEY is invalid; generating a replacement."
elif [ "${DEPLOYMENT_ROTATE_SECRETS:-false}" = "true" ] || [ "${DEPLOYMENT_REFRESH_ES_KEY:-false}" = "true" ]; then
  echo "ELASTICSEARCH_API_KEY refresh requested; generating a replacement."
fi

echo "Generating API key..."

# Generate API key
API_KEY_JSON=$(kubectl exec -n $NAMESPACE deploy/nexent-elasticsearch -- sh -c "curl -s -u 'elastic:$ELASTIC_PASSWORD' 'http://localhost:9200/_security/api_key' -H 'Content-Type: application/json' -d '{\"name\":\"nexent_api_key\",\"role_descriptors\":{\"nexent_role\":{\"cluster\":[\"all\"],\"index\":[{\"names\":[\"*\"],\"privileges\":[\"all\"]}]}}}'")

echo "API Key Response: $API_KEY_JSON"

# Extract API key using sed instead of jq
ENCODED_KEY=$(echo "$API_KEY_JSON" | sed 's/.*"encoded":"\([^"]*\)".*/\1/')

echo "Extracted key: $ENCODED_KEY"

if [ -n "$ENCODED_KEY" ] && [ "$ENCODED_KEY" != "$API_KEY_JSON" ]; then
  echo "Generated ELASTICSEARCH_API_KEY: $ENCODED_KEY"

  write_api_key_output "$ENCODED_KEY"
  sync_api_key_to_root_env "$ENCODED_KEY"
  echo "ELASTICSEARCH_API_KEY generated; Helm will update nexent-secrets."
else
  echo "Failed to extract API key from response"
  echo "Full response: $API_KEY_JSON"
  exit 1
fi
