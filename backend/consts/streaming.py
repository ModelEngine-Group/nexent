"""Shared headers for server-sent-event streaming responses."""

# Streaming responses must reach the client unbuffered even when an extra
# proxy (self-hosted nginx, corporate gateway, CDN) sits in front of the
# service. X-Accel-Buffering is consumed by nginx from the response itself,
# so it protects SSE endpoints on every hop without relying on proxy config.
SSE_STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
