from copy import deepcopy
from typing import Any, List, Optional


_MULTIMODAL_BLOCK_TYPES = {
    "image_url", "audio_url", "video_url",
    "input_audio", "input_image", "input_video",
}


def merge_system_messages(messages: List[Any]) -> List[Any]:
    """Join system text into one message before tracing or provider conversion."""
    def field(message, key):
        return message.get(key) if isinstance(message, dict) else getattr(message, key, None)

    systems = [message for message in messages if field(message, "role") == "system"]
    if not systems:
        return messages
    blocks = []
    string_only = True
    for message in systems:
        content = field(message, "content")
        string_only = string_only and isinstance(content, str)
        if isinstance(content, str):
            blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            blocks.extend(deepcopy(content))
        elif content is not None:
            raise TypeError("System content must be text or a list of blocks")

    # Cache annotations do not require separate text blocks. Retain the last
    # text annotation on the combined text; preserve any media blocks intact.
    text_blocks = [block for block in blocks if isinstance(block, dict) and block.get("type") == "text"]
    if len(text_blocks) == len(blocks):
        text = "\n\n".join(block["text"] for block in text_blocks)
        combined = {"type": "text", "text": text}
        for block in text_blocks:
            combined.update({key: value for key, value in block.items() if key not in {"type", "text"}})
        content = text if string_only else [combined]
    else:
        content = blocks
    merged = deepcopy(systems[0])
    if isinstance(merged, dict):
        merged["content"] = content
    else:
        merged.content = content
    result = []
    emitted = False
    for message in messages:
        if field(message, "role") == "system":
            if not emitted:
                result.append(merged)
                emitted = True
        else:
            result.append(message)
    return result


def content_has_multimodal_blocks(content: Any) -> bool:
    """True when ``content`` is a list carrying a typed media block."""
    if not isinstance(content, list):
        return False
    return any(
        isinstance(item, dict) and item.get("type") in _MULTIMODAL_BLOCK_TYPES
        for item in content
    )


def _flatten_content(raw_content: Any) -> str:
    """
    Convert structured content to plain text for providers with stricter schemas.
    """
    if isinstance(raw_content, str):
        return raw_content
    if isinstance(raw_content, list):
        parts: List[str] = []
        for item in raw_content:
            if isinstance(item, dict):
                # Prefer explicit text field if present
                if "text" in item and isinstance(item["text"], str):
                    parts.append(item["text"])
                elif "content" in item:
                    parts.append(str(item["content"]))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "".join(parts)
    return "" if raw_content is None else str(raw_content)


def prepare_messages_for_completion(normalized_messages: List[Any], model_factory: Optional[str] = None) -> List[Any]:
    """
    Prepare messages for completion based on provider requirements.

    - If `model_factory` is 'modelengine', returns a list of simple
      {"role": ..., "content": "..."} dicts where content is flattened to string.
    - Otherwise returns `normalized_messages` unchanged.

    `normalized_messages` is expected to be a list of objects that expose
    `.role` and `.content` attributes (e.g. ChatMessage) or dict-like objects.
    """
    if not model_factory:
        return normalized_messages
    if (model_factory or "").lower() == "modelengine":
        prepared: List[Any] = []
        for msg in normalized_messages:
            # support both attribute-style and dict-style messages
            role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
            content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
            prepared.append({"role": role, "content": _flatten_content(content)})
        return prepared
    return normalized_messages


def prepare_messages_for_smolagents_text_flattening(normalized_messages: List[Any]) -> List[Any]:
    """
    Normalize message content for smolagents' flatten_messages_as_text path.

    smolagents expects each message content to be a list whose first item is a
    text dict when flatten_messages_as_text=True. Plain string content otherwise
    fails with TypeError: string indices must be integers.

    Messages carrying typed media blocks (audio_url, image_url, ...) are left
    untouched: flattening them would discard the media payload an audio/video
    model needs.
    """
    for msg in normalized_messages:
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if content_has_multimodal_blocks(content):
            continue
        flattened = [{"type": "text", "text": _flatten_content(content)}]
        if isinstance(msg, dict):
            msg["content"] = flattened
        else:
            msg.content = flattened
    return normalized_messages
