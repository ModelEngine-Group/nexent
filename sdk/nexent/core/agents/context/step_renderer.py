"""Token estimation and safe retry truncation used by history summarization."""
from .config import ContextManagerConfig


class StepRenderer:
    def __init__(self, config: ContextManagerConfig):
        self.config = config

    def estimate_text_tokens(self, text: str) -> int:
        return max(0, int(len(text) / self.config.chars_per_token))

    def truncate_text_to_tokens(self, text: str, max_tokens: int) -> str:
        limit = max(0, int(max_tokens * self.config.chars_per_token))
        if len(text) <= limit:
            return text
        marker = "\n...[summary input truncated]...\n"
        if limit <= len(marker):
            return text[:limit]
        half = (limit - len(marker)) // 2
        return text[:half] + marker + text[-half:]
