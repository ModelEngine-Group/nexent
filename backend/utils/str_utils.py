from typing import List


def remove_think_tags(text: str) -> str:
    """
    Remove thinking tags from text

    Args:
        text: Input text that may contain thinking tags

    Returns:
        str: Text with thinking tags removed
    """
    return text.replace("<think>", "").replace("</think>", "")


def add_no_think_token(messages: List[dict]):
    if messages[-1]["role"] == "user":
        messages[-1]["content"] += " /no_think"
