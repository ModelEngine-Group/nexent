from typing import Any, List


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


def prepare_messages_for_completion(normalized_messages: List[Any], model_factory: str | None) -> List[Any]:
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


