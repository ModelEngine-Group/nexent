# Nexent FAQ 🤔

[![English](https://img.shields.io/badge/English-FAQ-blue)](FAQ.md)
[![中文](https://img.shields.io/badge/中文-FAQ-green)](FAQ_CN.md)

This FAQ addresses common questions and issues you might encounter while installing and deploying Nexent. For the basic installation steps, please refer to the [Quick Start Guide](../README.md#-have-a-try-first) in our README.

## 🚀 Installation & Setup

### 🔑 Jina API Key
- **Q: How do I get a Jina API key for embeddings?**
  - A: To use Jina-based embedding model, you'll need to:
    1. Visit [Jina AI's website](https://jina.ai/), no need to sign up
    3. Navigate to the Embedding section to get your API key
    4. Add your API key in the app

### 🐳 Docker & Docker Compose
- **Q: TODO**
  - A: TODO

### 🌐 Port Conflicts
- **Q: Port 3000 is already in use. How can I change it?**
  - A: You can modify the port in the Docker Compose configuration file.

## 🔍 Troubleshooting

### 🚫 Common Errors
- **Q: The setup wizard isn't loading at http://localhost:3000**
  - A: TODO

### 📦 Container Issues
- **Q: How do I check container logs?**
  - A: Use `docker logs <container_name>` to view logs for specific containers.

### 📧 Email Tools Configuration
- **Q: How can I enable and configure email tools?**
  - A: Our team has pre-implemented email tools based on IMAP and SMTP. To enable them:
    1. Configure email parameters in `.env` file
    2. Uncomment the email tool imports and registrations in `agent_utils.py`
    3. Switch to the email-enabled system prompt by using `code_agent_with_email.yaml`
    4. Restart the MCP service to apply changes

## ❓ Still Need Help?

If your question isn't answered here:
- Join our [Discord community](https://discord.gg/tb5H3S3wyv) for real-time support
- Check our [GitHub Issues](https://github.com/nexent-hub/nexent/issues) for similar problems
- Refer to our [Contribution Guide](../CONTRIBUTING.md) for more detailed information
