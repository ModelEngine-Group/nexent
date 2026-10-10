"""Compose document summarization requests."""

from .auxiliary import AuxiliaryPrompt, compose_auxiliary_prompt, render_auxiliary_field


def compose_document_cluster_summary(
    language: str, summaries: list[str], max_words: int
) -> AuxiliaryPrompt:
    """Format each selected document before rendering the reduce request."""
    entries = [
        render_auxiliary_field(
            language, "document_cluster_summary", "document_entry",
            {"index": index + 1, "summary": summary},
        )
        for index, summary in enumerate(summaries)
    ]
    return compose_auxiliary_prompt(
        language, "document_cluster_summary",
        {"document_summaries": "\n\n".join(entries), "max_words": max_words},
    )
