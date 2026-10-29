FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /usr/local/bin/

# mcp-proxy 0.12 imports request_ctx, which the MCP SDK 2.x removed.
# This image is a test asset, not the Nexent application image.
RUN uv pip install --system --no-cache "mcp==1.27.1" "mcp-proxy==0.12.0" \
    && python -m mcp_proxy --help >/dev/null

CMD ["python3"]
