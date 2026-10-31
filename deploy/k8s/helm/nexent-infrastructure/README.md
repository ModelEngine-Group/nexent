# Nexent Infrastructure Helm Chart

This chart owns the `nexent-infrastructure` release and contains only Elasticsearch, PostgreSQL, Redis, MinIO, their storage resources, `nexent-infrastructure-secrets`, and `nexent-infrastructure-sql`.

Use `bash deploy.sh k8s --release-scope infrastructure` from the repository root for normal operation. The deployment script generates stable credentials, renders PostgreSQL bootstrap SQL, installs this release, and waits for all four Deployments.

Operators that manage values externally can run:

```bash
helm dependency update deploy/k8s/helm/nexent-infrastructure
helm upgrade --install nexent-infrastructure deploy/k8s/helm/nexent-infrastructure \
  --namespace nexent --create-namespace \
  -f /path/to/infrastructure-values.yaml
```

Use a distinct `nexent` release for the application chart. Do not put `ELASTICSEARCH_API_KEY` in infrastructure values; the key belongs only to the application-side `nexent-secrets` Secret.
