FROM python:3.11-slim

# mcp-proxy 0.12 imports request_ctx, which the MCP SDK 2.x removed.
# This image is a test asset, not the Nexent application image.
RUN pip install --no-cache-dir "mcp==1.27.1" "mcp-proxy==0.12.0" \
    && python -m mcp_proxy --help >/dev/null

CMD ["python3"]
