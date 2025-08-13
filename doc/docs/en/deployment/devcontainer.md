# Nexent Dev Container Usage Guide

## 1. Environment Overview

This development container configuration sets up a complete Nexent development environment, including the following components:

- Main development container (`nexent-dev`): Based on nexent/nexent image with development tools
- Service containers:
  - Elasticsearch (`nexent-elasticsearch`)
  - PostgreSQL (`nexent-postgresql`)
  - MinIO (`nexent-minio`)
  - Nexent backend (`nexent`)
  - Nexent frontend (`nexent-web`)
  - Data processing service (`nexent-data-process`)

## 2. Usage Steps

### 2.1 Prerequisites

1. Install Cursor/VS Code
2. Install Dev Containers extension (`anysphere.remote-containers` and `anysphere.remote-sshRemote`)
3. Ensure Docker and Docker Compose are installed and running

### 2.2 Starting Project with Dev Container

1. Clone the project locally
2. Open project folder in Cursor/VS Code
3. Run `docker/deploy.sh` script in `infrastructure` mode to start containers
4. Enter `nexent-minio` and `nexent-elasticsearch` containers, copy `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `ELASTICSEARCH_API_KEY` environment variables to corresponding positions in `docker/docker-compose.dev.yml`
5. Press `F1` or `Ctrl+Shift+P`, type `Dev Containers: Reopen in Container ...`
6. Cursor will start the development container based on configuration in `.devcontainer` directory

### 2.3 Development Workflow

1. After container starts, Cursor automatically connects to development container
2. All file editing is done within the container
3. Develop, test, and build directly in container after modifications
4. Git change management can be done directly in container using `git commit` or `git push`; however, pulling remote code in container is not recommended as it may cause path issues

## 3. Port Mapping

The following ports are mapped in devcontainer.json:

- 3000: Nexent Web interface
- 5010: Nexent backend service
- 5012: Data processing service
- 9010: MinIO API
- 9011: MinIO console
- 9210: Elasticsearch API
- 5434: PostgreSQL

## 4. Customizing Development Environment

You can customize the development environment by modifying:

- `.devcontainer/devcontainer.json` - Plugin configuration
- `docker/docker-compose.dev.yml` - Development container build configuration, requires environment variable modification for proper startup

## 5. Troubleshooting

### 🔐 Permission Issues
If you encounter permission issues, you may need to run in container:

```bash
sudo chown -R $(id -u):$(id -g) /opt
```

If container startup fails, try:

1. Rebuild container: Press `F1` or `Ctrl+Shift+P`, type `Dev Containers: Rebuild Container`
2. Check Docker logs: `docker logs nexent-dev`
3. Check if configuration in `.env` file is correct

### 🌐 Network Connection Issues
- **Q: How can a Docker container access models deployed on the host machine (e.g., Ollama)?**
  - A: Since `localhost` inside the container refers to the container itself, use one of these methods to connect to host services:

    **Option 1: Use Docker's special DNS name `host.docker.internal`**  
    Supported environments: Mac/Windows and newer Docker Desktop versions (Linux version also supported)  
    ```bash
    http://host.docker.internal:11434/v1
    ```

    **Option 2: Use host machine's actual IP (ensure firewall allows access)**
    ```bash
    http://[HOST_IP]:11434/v1
    ```

    **Option 3: Modify Docker Compose configuration**  
    Add to your docker-compose.yaml file:
    ```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ```
