#!/bin/bash
# Script to initialize Elasticsearch API key for Nexent

NAMESPACE=nexent

# Get elastic password from secret
ELASTIC_PASSWORD=$(kubectl get secret nexent-secrets -n $NAMESPACE -o jsonpath='{.data.ELASTIC_PASSWORD}' | base64 -d)

echo "Waiting for Elasticsearch to be ready..."

# Wait for Elasticsearch to be healthy
until kubectl exec -n $NAMESPACE deploy/nexent-elasticsearch -- curl -s -u "elastic:$ELASTIC_PASSWORD" "http://localhost:9200/_cluster/health" 2>/dev/null | grep -q '"status":"green"\|"status":"yellow"'; do
  echo "Elasticsearch is unavailable - sleeping"
  sleep 5
done
echo "Elasticsearch is ready - generating API key..."

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
