# Nexent Helm Chart

This directory contains a Helm chart for deploying Nexent on Kubernetes.

## Prerequisites

- Kubernetes cluster (e.g., Minikube, K3s, Docker Desktop)
- Helm 3+

## Usage

### Deploying the chart

1. Navigate to the `k8s/helm` directory:
   ```bash
   cd k8s/helm
   ```

2. Run the deployment script:
   ```bash
   ./deploy-helm.sh apply
   ```

   This script will:
   - Ask for the data directory path (where persistent data will be stored)
   - Create the necessary directories on the host
   - Deploy the Helm chart with the specified configuration

### Customizing the deployment

You can customize the deployment by editing `nexent/values.yaml` or by passing values via the command line:

```bash
helm upgrade --install nexent nexent \
  --set images.backend.tag=v1.0.0 \
  --set global.dataDir=/custom/path
```

### Uninstalling

To uninstall while preserving data:
```bash
./deploy-helm.sh delete
```

To uninstall and delete all data:
```bash
./deploy-helm.sh delete-all
```

## Configuration

The following tables list the configurable parameters of the Nexent chart and their default values.

### Global Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.namespace` | Kubernetes namespace | `nexent` |
| `global.dataDir` | Host path for persistent data | `/data/nexent` |

### Images

| Parameter | Description | Default |
|-----------|-------------|---------|
| `images.backend.repository` | Backend image repository | `nexent/nexent` |
| `images.backend.tag` | Backend image tag | `latest` |
| `images.web.repository` | Web image repository | `nexent/nexent-web` |
| `images.web.tag` | Web image tag | `latest` |
| `images.dataProcess.repository` | Data process image repository | `nexent/nexent-data-process` |
| `images.dataProcess.tag` | Data process image tag | `latest` |

### Resources

Resource limits and requests can be adjusted in `values.yaml` for each component:
- Backend services (config, runtime, mcp, northbound)
- Web service
- Data process service
- Infrastructure (Elasticsearch, PostgreSQL, Redis, MinIO)
