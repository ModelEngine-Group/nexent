"""System-injected tool that generates and validates A2UI v0.9 surfaces."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from importlib import resources
from typing import Any, Callable

import yaml
from pydantic import Field
from pydantic.fields import FieldInfo
from smolagents.tools import Tool

from ..a2ui import A2UI_CATALOG_ID, A2UI_PROTOCOL_VERSION, A2UIValidationError, validate_a2ui_messages
from ..agents.agent_model import ModelConfig
from ..models.openai_llm import OpenAIModel
from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolCategory, ToolSign


logger = logging.getLogger(__name__)

_PROMPT_KEYS = ("system_prompt", "user_prompt", "repair_prompt")


def _prompt_language(language: Any) -> str:
    normalized_language = language.strip().lower() if isinstance(language, str) else ""
    return "zh" if normalized_language.startswith("zh") else "en"


def _load_prompt(language: Any = "en") -> dict[str, str]:
    prompt_language = _prompt_language(language)
    prompt_file = resources.files("nexent.core.prompts").joinpath(f"a2ui_generator_{prompt_language}.yaml")
    with prompt_file.open("r", encoding="utf-8") as file_obj:
        prompt = yaml.safe_load(file_obj)

    if not isinstance(prompt, dict):
        raise ValueError("A2UI generator prompt configuration must be an object")

    for key in _PROMPT_KEYS:
        value = prompt.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"A2UI generator prompt configuration is missing {prompt_language}.{key}")
    return prompt


def _extract_json(text: str) -> Any:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S).strip()
    decoder = json.JSONDecoder()
    start = min((index for index in (cleaned.find("{"), cleaned.find("[")) if index >= 0), default=-1)
    if start < 0:
        raise A2UIValidationError("Generator did not return JSON")
    value, _ = decoder.raw_decode(cleaned, start)
    return value


class GenerateA2UITool(Tool):
    """Generate a safe A2UI surface through an isolated model call."""

    name = "generate_a2ui"
    description = (
        "Generate an interactive UI when structured presentation or user input is more useful than plain text. "
        "When the current user explicitly asks to create, generate, regenerate, or show an interactive UI, "
        "you must invoke this tool for that turn even if a similar UI was generated earlier. "
        "Each invocation creates a new independent surface. "
        "Do not claim that a UI was generated unless this tool returns status 'rendered'. "
        "The UI is validated and cannot execute business operations directly."
    )
    inputs = {
        "description": {"type": "string", "description": "What the UI should communicate or collect"},
        "data": {"type": "object", "description": "Structured data to display or bind"},
        "expectedOutput": {"type": "string", "description": "Expected user-visible result and interactions"},
    }
    output_type = "string"
    category = ToolCategory.UI.value
    tool_sign = ToolSign.UI_OPERATION.value
    source = "local"
    labels = ["ui"]

    def __init__(
        self,
        model_config: ModelConfig = Field(description="Resolved root model configuration", exclude=True),
        observer: MessageObserver = Field(description="Main run observer", exclude=True),
        model_factory: Callable[[ModelConfig], Any] | None = Field(default=None, exclude=True),
    ) -> None:
        super().__init__()
        if isinstance(model_factory, FieldInfo):
            model_factory = model_factory.default
        self.model_config = model_config
        self.observer = observer
        self._model_factory = model_factory

    def _create_model(self) -> Any:
        if self._model_factory is not None:
            return self._model_factory(self.model_config)
        config = self.model_config
        return OpenAIModel(
            observer=MessageObserver(),
            model_id=config.model_name,
            api_key=config.api_key,
            api_base=config.url,
            temperature=config.temperature,
            top_p=config.top_p,
            ssl_verify=config.ssl_verify if config.ssl_verify is not None else True,
            model_factory=config.model_factory,
            display_name=f"{config.cite_name}:a2ui",
            extra_body=config.extra_body,
            max_output_tokens=config.max_output_tokens,
            timeout_seconds=config.timeout_seconds,
        )

    @staticmethod
    def _response_text(response: Any) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in content)
        return str(content or "")

    def forward(self, description: str, data: dict, expectedOutput: str) -> str:
        started_at = time.perf_counter()
        if not isinstance(data, dict):
            raise ValueError("data must be an object")
        if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > 64 * 1024:
            raise ValueError("data exceeds 64 KiB")

        prompts = _load_prompt(getattr(self.observer, "lang", None))
        user_prompt = prompts["user_prompt"].format(
            description=description,
            data=json.dumps(data, ensure_ascii=False),
            expected_output=expectedOutput,
        )
        model = self._create_model()
        input_tokens = 0
        output_tokens = 0

        def invoke_generator(prompt_messages: list[dict[str, str]]) -> str:
            nonlocal input_tokens, output_tokens
            response = model(prompt_messages, response_format={"type": "json_object"})
            input_tokens += int(getattr(model, "last_input_token_count", 0) or 0)
            output_tokens += int(getattr(model, "last_output_token_count", 0) or 0)
            return self._response_text(response)

        messages = [
            {"role": "system", "content": prompts["system_prompt"]},
            {"role": "user", "content": user_prompt},
        ]
        response_text = invoke_generator(messages)

        surface_id = f"surface-{uuid.uuid4()}"
        attempts = 1
        try:
            normalized = validate_a2ui_messages(
                _extract_json(response_text),
                surface_id=surface_id,
            )
        except (A2UIValidationError, json.JSONDecodeError) as first_error:
            logger.warning("event=a2ui_schema_failure attempt=1 error=%s", first_error)
            attempts = 2
            repair = prompts["repair_prompt"].format(error=str(first_error), previous_output=response_text)
            repair_messages = [
                {"role": "system", "content": prompts["system_prompt"]},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": response_text},
                {"role": "user", "content": repair},
            ]
            repaired_text = invoke_generator(repair_messages)
            try:
                normalized = validate_a2ui_messages(
                    _extract_json(repaired_text),
                    surface_id=surface_id,
                )
            except (A2UIValidationError, json.JSONDecodeError) as final_error:
                logger.warning(
                    "event=a2ui_generation_failed duration_ms=%.2f attempts=2 "
                    "input_tokens=%s output_tokens=%s error=%s",
                    (time.perf_counter() - started_at) * 1000,
                    input_tokens,
                    output_tokens,
                    final_error,
                )
                raise

        for message in normalized:
            envelope = {
                "protocolVersion": A2UI_PROTOCOL_VERSION,
                "catalogId": A2UI_CATALOG_ID,
                "surfaceId": surface_id,
                "message": message,
            }
            self.observer.add_message("", ProcessType.A2UI, json.dumps(envelope, ensure_ascii=False))
        logger.info(
            "event=a2ui_generation_complete duration_ms=%.2f attempts=%s surface_id=%s "
            "message_count=%s input_tokens=%s output_tokens=%s",
            (time.perf_counter() - started_at) * 1000,
            attempts,
            surface_id,
            len(normalized),
            input_tokens,
            output_tokens,
        )
        return json.dumps(
            {"status": "rendered", "surfaceId": surface_id, "messageCount": len(normalized)},
            ensure_ascii=False,
        )
