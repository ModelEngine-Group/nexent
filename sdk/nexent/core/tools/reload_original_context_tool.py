import json
import logging

from smolagents.tools import Tool

logger = logging.getLogger("reload_original_context_tool")


class ReloadOriginalContextTool(Tool):
    """Tool for reloading offloaded original context content.

    When the context manager compresses conversation history, long step content
    is offloaded to an in-memory store and replaced with [[OFFLOAD:handle=...]]
    markers. The agent can call this tool to recover the full original content
    when detailed information from earlier steps is needed.
    """
    name = "reload_original_context_messages"
    description = (
        "Reload the original full content of an offloaded / archived context step. "
        "At the start of each conversation turn, a system notice lists available "
        "archived handles (e.g. 'handle=abc123: description'). "
        "Use this tool with the handle value from that notice when you need to "
        "review the detailed original content that was removed to save context space."
    )

    inputs = {
        "offload_handle": {
            "type": "string",
            "description": "The handle value from the system notice inventory (e.g. 'handle=abc123')"
        }
    }

    output_type = "string"

    def __init__(self, offload_store=None, **kwargs):
        super().__init__(**kwargs)
        self._offload_store = offload_store

    def forward(self, offload_handle: str) -> str:
        if self._offload_store is None:
            return json.dumps({"error": "Offload store is not available. Context reload is not enabled."})

        content = self._offload_store.reload(offload_handle)
        if content is None:
            return json.dumps({
                "error": f"No offloaded content found for handle '{offload_handle}'. "
                         f"The content may have been evicted from the store."
            })

        return json.dumps({
            "offload_handle": offload_handle,
            "content": content,
            "content_length": len(content),
            "message": "Original context content retrieved successfully."
        }, ensure_ascii=False)