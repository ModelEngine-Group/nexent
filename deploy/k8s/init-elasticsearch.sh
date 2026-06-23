#!/bin/bash
# Script to initialize Elasticsearch API key for Nexent

NAMESPACE=nexent

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
    echo "Existing ELASTICSEARCH_API_KEY is valid; keeping current secret."
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

  # Update secret using base64 encoding (use -w 0 to avoid line wrapping on Linux, tr -d '\n' for Windows)
  ENCODED_KEY_BASE64=$(echo -n "$ENCODED_KEY" | base64 -w 0 2>/dev/null || echo -n "$ENCODED_KEY" | base64 | tr -d '\n')

  kubectl patch secret nexent-secrets -n $NAMESPACE -p="{\"data\":{\"ELASTICSEARCH_API_KEY\":\"$ENCODED_KEY_BASE64\"}}"

  echo "Secret updated successfully"
else
  echo "Failed to extract API key from response"
  echo "Full response: $API_KEY_JSON"
  exit 1
fi
