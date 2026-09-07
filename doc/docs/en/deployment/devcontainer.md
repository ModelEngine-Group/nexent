# Nexent Dev Container Usage Guide

## 1. Environment Overview

This development container configuration sets up a complete Nexent development environment, including the following components:

- Main development container (`nexent-data-process`): Based on the nexent/nexent-data-process image, with the repository code mounted into the container's `/opt` directory and a Python development environment pre-installed
- Service containers (infrastructure and application services deployed via `bash deploy.sh docker`):
  - Elasticsearch (`nexent-elasticsearch`)
  - PostgreSQL (`nexent-postgresql`)
  - MinIO (`nexent-minio`)
  - Backend Config service (`nexent-config`)
  - Web frontend (`nexent-web`)
  - Data processing service (`nexent-data-process`)

## 2. Usage Steps

### 2.1 Prerequisites

1. Install Cursor/VS Code
2. Install Dev Containers extension (`anysphere.remote-containers`)
3. Ensure Docker and Docker Compose are installed and running

### 2.2 Starting Project with Dev Container

1. Clone the project locally
2. Open project folder in Cursor/VS Code
3. Run `bash deploy.sh docker --components infrastructure,application,data-process,supabase --port-policy development` from the repository root to start base containers
4. The deploy script writes generated variables such as `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, and `ELASTICSEARCH_API_KEY` back to `deploy/env/.env`. Services in `deploy/docker/compose/docker-compose.dev.yml` load these settings automatically via `env_file`, so no manual copying is needed
5. Press `F1` or `Ctrl+Shift+P`, type `Dev Containers: Reopen in Container ...`
6. Cursor will start the development container based on configuration in `.devcontainer` directory

### 2.3 Development Workflow

1. After container starts, Cursor automatically connects to development container
2. All file editing is done within the container
3. Develop, test, and build directly in container after modifications
4. Git change management can be done directly in container using `git commit` or `git push`; however, pulling remote code in container is not recommended as it may cause path issues

## 3. Port Mapping

The following ports are forwarded via `forwardPorts` in `.devcontainer/devcontainer.json`:

- 3000: Nexent Web interface
- 5012: Data processing service

Other service ports (Backend Config service 5010, PostgreSQL 5434, MinIO API 9010, MinIO console 9011, Elasticsearch API 9210, etc.) are published directly on the host by Docker Compose under the development port policy and can be accessed directly from the host machine.

## 4. Customizing Development Environment

You can customize the development environment by modifying:

- `.devcontainer/devcontainer.json` - Plugin configuration
- `deploy/docker/compose/docker-compose.dev.yml` - Development container build configuration, requires environment variable modification for proper startup

## 5. Troubleshooting

If you encounter permission issues, you may need to run in container:

```bash
sudo chown -R $(id -u):$(id -g) /opt
```

If container startup fails, try:

1. Rebuild container: Press `F1` or `Ctrl+Shift+P`, type `Dev Containers: Rebuild Container`
2. Check Docker logs: `docker logs nexent-data-process`
3. Check if configuration in `.env` file is correct