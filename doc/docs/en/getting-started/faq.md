# Nexent FAQ

This FAQ addresses common questions and issues you might encounter while installing and using Nexent. For the basic installation steps, please refer to the [Installation & Development](./installation). For basic using instructions, please refer to the [User Guide](../user-guide/home-page).

## 🚫 Common Errors & Operations

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

### 🔌 Port Conflicts

- **Q: Port 3000 is already in use. How can I change it?**
  - A: You can modify the port in the Docker Compose configuration file.

### 📦 Container Issues

- **Q: How do I check container logs?**
  - A: Use `docker logs <container_name>` to view logs for specific containers.

## 🔍 Troubleshooting

### 🔢 Model Connection Issues

- **Q: Why can't my model connect?**
  - A: Check the following:
    1. **Correct API endpoint**: Ensure you're using the right base URL
    2. **Valid API key**: Verify your API key has proper permissions
    3. **Model name**: Confirm the model identifier is correct
    4. **Network access**: Ensure your deployment can reach the provider's servers

    For model setup instruction, see [Model Management](../user-guide/model-management) in User Guide.

- **Q: Multi-turn chats fail when using the official DeepSeek API. How can I resolve this?**
  - A: The official DeepSeek API only accepts text payloads, but Nexent sends multimodal payloads, so multi-turn calls are rejected. Use a provider such as SiliconFlow that exposes DeepSeek models with multimodal compatibility. Our requests look like:
  ```python
  { "role":"user", "content":[ { "type":"text", "text":"prompt" } ] }
  ```
  whereas DeepSeek expects:
  ```python
  { "role":"user", "content":"prompt" }
  ```

## 💡 Need Help

If your question isn't answered here:

- Join our [Discord community](https://discord.gg/tb5H3S3wyv) for real-time support
- Check our [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) for similar problems
- Open a thread in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions).
