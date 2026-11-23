# Nexent FAQ

This FAQ addresses common questions and issues you may encounter while installing and using Nexent. For basic installation steps, see [Installation & Deployment](./installation). For basic usage instructions, see the [User Guide](../user-guide/home-page).

## 🚫 Common Errors and Operations

### 🌐 Network Connection Issues

- **Q: How can a Docker container access models deployed on the host machine, such as Ollama?**
  - A: Because `localhost` inside a container refers to the container itself, use one of the following methods to connect to a host service:

    **Option 1: Use Docker's special DNS name `host.docker.internal`**

    Applicable environments: macOS, Windows, and Linux Docker environments where this name has been configured.

      ```bash
      http://host.docker.internal:11434/v1
      ```

    **Option 2: Use the host machine's actual IP address and make sure the firewall allows access**

    ```bash
    http://[HOST_IP]:11434/v1
    ```

    **Option 3: Configure Docker Compose**

    Add the following configuration to the relevant service:

    ```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ```

### 🔌 Port Conflicts

- **Q: Port 3000 is already in use. How can I change it?**
  - A: Change the port in the Docker Compose configuration.

### 📦 Container Issues

- **Q: How do I view container logs?**
  - A: Run `docker logs <container_name>` to view the logs for a specific container.

- **Q: An agent reports that it cannot create a sandbox. How do I troubleshoot it?**
  - A: Check the following in order:
    1. Make sure the Docker service is running.
    2. Make sure the Runtime service has read-only access to `/var/run/docker.sock`.
    3. Make sure the image specified by `NEXENT_SANDBOX_DOCKER_IMAGE` in `deploy/env/.env` has been pulled.
    4. Make sure the workspace volume specified by `NEXENT_SANDBOX_WORKSPACE_VOLUME` exists.
    5. Check whether the sandbox resource limits exceed the resources available on the host.

    For a Docker deployment, inspect the default resources with:

    ```bash
    docker images nexent/nexent-sandbox
    docker volume inspect nexent-agent-workspace
    docker logs nexent-runtime --tail 100
    ```

## 🔍 Troubleshooting

### 🔢 Model Connection Issues

- **Q: Why can't my model connect?**
  - A: Check the following:
    1. **Correct API endpoint**: Make sure you are using the correct base URL.
    2. **Valid API key**: Verify that your API key has the required permissions.
    3. **Model name**: Confirm that the model identifier is correct.
    4. **Network access**: Make sure your deployment can reach the provider's servers.

    For model configuration instructions, see [Model Configuration](../user-guide/agent-development/model-configuration) in the User Guide.

- **Q: The model service reports an incompatible message format. How can I resolve it?**
  - A: Providers differ in how fully they support the OpenAI message format. Some text-only APIs accept only a string as `content` and do not accept an array of content blocks. First check that the model type and API endpoint are configured correctly, then consult the provider's protocol documentation. For example, a multimodal message may use:

  ```python
  { "role":"user", "content":[ { "type":"text", "text":"prompt" } ] }
  ```

  A text-only API may accept only:

  ```python
  { "role":"user", "content":"prompt" }
  ```

  If the provider does not support the current message format, use an API compatible with OpenAI multimodal messages or configure the model with the corresponding text-only model type.

## 🐛 Known Issues

This section lists known issues and limitations in the current Nexent release. We are actively addressing these issues and will update this section as solutions become available.

### 🔧 Software Installation Restrictions in OpenSSH Containers

**Description**: OpenSSH terminal containers and agent sandboxes are controlled execution environments. Installing system packages at runtime is not recommended. The sandbox image includes commonly used data-processing and document-generation dependencies but does not guarantee that every third-party package is available.

**Status**: This is a runtime environment security restriction.

**Impact**: Scripts that require additional system packages or administrator privileges may not run directly.

**Resolution**: Add the dependencies to a custom terminal or sandbox image in advance and select that image in the deployment configuration. Do not modify containers temporarily during production runs.

## 📝 Report an Issue

If you encounter an issue not listed here:

1. **Search existing issues** in [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues).
2. **Create a new issue** and include:
   - Steps to reproduce
   - Expected behavior
   - Actual behavior
   - System information
   - Log files, if applicable

## 💡 Need Help

If your question is not answered here:

- Join our [Discord community](https://discord.gg/tb5H3S3wyv) for real-time support
- Check [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) for similar problems
- Start a discussion in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions)
