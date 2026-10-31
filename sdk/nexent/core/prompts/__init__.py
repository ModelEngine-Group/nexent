"""Read SDK-owned prompt resources by their language and purpose."""

import re
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

import yaml


_RESOURCE_SEGMENT = re.compile(r"[a-z][a-z0-9_]*\Z")


def load_prompt(language: str, relative_path: str) -> dict[str, Any]:
    """Load one YAML mapping relative to its language directory."""
    if language not in {"zh", "en"}:
        raise ValueError(f"Unsupported prompt language: {language}")
    if not isinstance(relative_path, str):
        raise ValueError("Prompt path must be a safe relative YAML path")
    path_without_suffix = relative_path.removesuffix(".yaml")
    segments = path_without_suffix.split("/")
    if not all(_RESOURCE_SEGMENT.fullmatch(segment) for segment in segments):
        raise ValueError("Prompt path must be a safe relative YAML path")

    resource_name = f"{language}/{'/'.join(segments)}.yaml"
    resource = files(__package__).joinpath(resource_name)
    with resource.open("r", encoding="utf-8") as stream:
        prompt = yaml.safe_load(stream)
    if not isinstance(prompt, dict) or not prompt:
        raise ValueError(f"Prompt resource {resource_name} must be a non-empty mapping")
    return prompt


def render_prompt_text(source: str, parameters: Mapping[str, Any]) -> str:
    """Render prompt text with explicit runtime values and strict missing keys."""
    from jinja2 import Environment, StrictUndefined

    if not isinstance(source, str):
        raise TypeError("prompt source must be text")
    if not isinstance(parameters, Mapping):
        raise TypeError("prompt parameters must be a mapping")
    environment = Environment(
        undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True,
    )
    return environment.from_string(source).render(**parameters)


__all__ = ["load_prompt", "render_prompt_text"]
