# Container MCP test asset

Build this fixture only after any shared Daily batch has finished:

```bash
docker build -t nexent/nexent-mcp:latest test-e2e/infra/environment/services/container-mcp
docker run --rm --network none --entrypoint python nexent/nexent-mcp:latest -m mcp_proxy --help
```

Use the existing deployment's `NEXENT_MCP_DOCKER_IMAGE` selection. Do not edit
the product image, add a personal path or invent another environment variable.
If that configured image differs, explicitly select the authorized test image
tag when building instead of overwriting an unrelated image.

The product starts this image with the configured stdio fixture command and
its own MCP proxy. Import/CLI success is only a prerequisite: rerun
`PW-MCP-CONTAINER-01` to verify creation, health, tools and cleanup end to end.
Retain failures; do not treat HTTP 200 from a deployment stream as success.
