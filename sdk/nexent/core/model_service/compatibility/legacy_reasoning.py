# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pure legacy reasoning conversions reused by SDK compatibility and outlet migration."""

import logging
from copy import deepcopy
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

logger = logging.getLogger("openai_llm")


class ReasoningConfigurationError(RuntimeError):
    """Raised when a provider rejects the configured reasoning parameters."""

    is_reasoning_configuration_error = True


class LegacyReasoningPolicy:
    """Legacy field translation only; no inference, lifecycle or transport ownership."""

    def _reasoning_wire_profile(self) -> Optional[Dict[str, Optional[str]]]:
        """Return only an explicitly known provider wire mapping.

        models.dev declares that a model has reasoning controls, but it does
        not define a universal request field for every OpenAI-compatible
        provider. Confirmed providers use their own adapter. For an unknown
        provider, an enum effort falls back to OpenAI's public
        ``reasoning_effort`` field. Numeric budgets still require an explicit
        provider adapter; an explicitly supplied thinking toggle retains the
        legacy top-level passthrough for generic compatible gateways.
        """
        capability = self.reasoning_capability or {}
        provider_id = str(
            capability.get("provider_id") or self.model_factory or ""
        ).lower()
        api_url = str(
            capability.get("matched_api") or self.api_base_url or ""
        ).lower()
        try:
            api_hostname = (
                urlsplit(api_url if "://" in api_url else f"//{api_url}").hostname
                or ""
            ).rstrip(".")
        except ValueError:
            api_hostname = ""
        if api_hostname == "aliyuncs.com" or api_hostname.endswith(".aliyuncs.com"):
            provider_id = "dashscope"
        elif api_hostname == "api.deepseek.com":
            provider_id = "deepseek"

        if capability.get("source") == "models_dev":
            if provider_id in {"alibaba", "alibaba-cn", "dashscope"}:
                return {
                    "effort": "reasoning_effort",
                    "budget": "thinking_budget",
                    "toggle": "enable_thinking",
                }
            if provider_id == "deepseek":
                return {
                    "effort": "reasoning_effort",
                    "budget": None,
                    "toggle": "thinking_object",
                }
            if provider_id in {"openai", "google"}:
                return {
                    "effort": "reasoning_effort",
                    "budget": None,
                    "toggle": None,
                }
            if capability.get("wire_format") == "reasoning_effort":
                return {
                    "effort": "reasoning_effort",
                    "budget": None,
                    "toggle": None,
                }
            return {
                "effort": "reasoning_effort",
                "budget": None,
                "toggle": None,
            }

        effort = capability.get("wire_format") or "reasoning_effort"
        if effort not in {"reasoning_effort", "thinking_toggle", "thinking_budget"}:
            # OpenAI-compatible endpoints have one public effort field. Use
            # it as the conservative fallback for an unconfirmed provider;
            # provider-specific budget/toggle fields are never inferred.
            effort = "reasoning_effort"
        budget = capability.get("budget_wire_format")
        if budget is None and effort == "thinking_budget":
            # Existing operator/catalog profiles explicitly using the
            # thinking-budget wire format use the nested thinking object.
            budget = "thinking_object"
        toggle = capability.get("toggle_wire_format")
        if toggle is None and provider_id == "deepseek":
            toggle = "thinking_object"
        if toggle is None and provider_id in {"alibaba", "alibaba-cn", "dashscope"}:
            toggle = "enable_thinking"
        return {"effort": effort, "budget": budget, "toggle": toggle}

    def _translate_thinking_flag(
        self, extra_body: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Translate the enable_thinking flag to the provider's wire format.

        Qwen-family self-hosted deployments read the flag from
        ``chat_template_kwargs.enable_thinking``. DashScope's OpenAI-compatible
        endpoint accepts the top-level ``enable_thinking`` extra field. Known
        providers use their adapter; unknown compatible gateways retain an
        explicitly supplied top-level flag for backward compatibility.
        """
        if "enable_thinking" not in extra_body:
            return extra_body
        translated = dict(extra_body)
        thinking = translated.pop("enable_thinking")
        wire_profile = self._reasoning_wire_profile()
        toggle_format = wire_profile.get("toggle") if wire_profile else None
        if toggle_format == "thinking_object":
            translated["thinking"] = {
                "type": "enabled" if thinking else "disabled"
            }
        elif toggle_format == "enable_thinking":
            translated["enable_thinking"] = thinking
        elif toggle_format == "chat_template" or (
            toggle_format is None
            and wire_profile is not None
            and (self.reasoning_capability or {}).get("source") != "models_dev"
            and "qwen" in (self.model_id or "").lower()
        ):
            chat_kwargs = translated.get("chat_template_kwargs")
            if isinstance(chat_kwargs, dict):
                translated["chat_template_kwargs"] = {
                    **chat_kwargs, "enable_thinking": thinking,
                }
            else:
                translated["chat_template_kwargs"] = {"enable_thinking": thinking}
        elif toggle_format is None:
            capability = self.reasoning_capability or {}
            provider_id = str(
                capability.get("provider_id") or self.model_factory or ""
            ).lower()
            if capability.get("status") != "unsupported" and not (
                capability.get("source") == "models_dev"
                and provider_id in {"openai", "google"}
            ):
                # Preserve the pre-merge behavior for generic OpenAI-compatible
                # gateways. This only forwards a toggle explicitly supplied by
                # the caller; it does not enable the flag for every request.
                translated["enable_thinking"] = thinking
        return translated

    def _apply_reasoning_control(self, completion_kwargs: Dict[str, Any]) -> None:
        """Apply the catalog's canonical effort using the provider wire format.

        Most OpenAI-compatible endpoints accept a top-level
        ``reasoning_effort``. A few providers expose the same concept as a
        ``thinking`` object, so the catalog declares that translation instead
        of making the runtime guess from a model name.
        """
        if (
            (self.reasoning_effort is None or self.reasoning_effort == "auto")
            and self.reasoning_budget_tokens is None
        ):
            return

        capability = self.reasoning_capability or {}
        if capability.get("status") == "unsupported":
            return
        wire_profile = self._reasoning_wire_profile()
        if wire_profile is None:
            logger.warning(
                "event=reasoning_wire_adapter_missing model_id=%s provider=%s",
                self.model_id,
                capability.get("provider_id") or self.model_factory or "unknown",
            )
            return
        wire_format = wire_profile.get("effort")

        controls = capability.get("controls")
        budget_control_declared = any(
            isinstance(control, dict) and control.get("type") == "budget_tokens"
            for control in controls or []
        )
        budget_wire_format = wire_profile.get("budget")

        # Numeric budget and enum effort are alternative controls. If both are
        # present in a historical/configured value, numeric budget wins.
        has_budget = (
            budget_control_declared
            and isinstance(self.reasoning_budget_tokens, int)
            and not isinstance(self.reasoning_budget_tokens, bool)
            and self.reasoning_budget_tokens > 0
        )
        if has_budget:
            completion_kwargs.pop("reasoning_effort", None)
            if budget_wire_format == "thinking_budget":
                extra_body = dict(completion_kwargs.get("extra_body") or {})
                extra_body["thinking_budget"] = self.reasoning_budget_tokens
                completion_kwargs["extra_body"] = self._translate_thinking_flag(extra_body)
                return
            if budget_wire_format is None:
                logger.warning(
                    "event=reasoning_budget_adapter_missing model_id=%s provider=%s",
                    self.model_id,
                    capability.get("provider_id") or self.model_factory or "unknown",
                )
                return
        elif budget_control_declared:
            # Auto means no provider reasoning parameter.
            return

        if wire_format == "reasoning_effort" and not has_budget:
            if self.reasoning_effort is not None and self.reasoning_effort != "auto":
                completion_kwargs["reasoning_effort"] = self.reasoning_effort
            return

        if wire_format is None:
            logger.warning(
                "event=reasoning_effort_adapter_missing model_id=%s provider=%s",
                self.model_id,
                capability.get("provider_id") or self.model_factory or "unknown",
            )
            return

        if budget_control_declared and self.reasoning_budget_tokens is None:
            return

        extra_body = dict(completion_kwargs.get("extra_body") or {})
        thinking = extra_body.get("thinking")
        thinking = dict(thinking) if isinstance(thinking, dict) else {}

        if self.reasoning_budget_tokens is not None:
            thinking["type"] = "enabled"
            thinking["budget_tokens"] = self.reasoning_budget_tokens
        elif self.reasoning_effort == "none":
            thinking["type"] = "disabled"
            thinking.pop("budget_tokens", None)
        else:
            thinking["type"] = "enabled"
            if wire_format == "thinking_budget":
                budgets = capability.get("effort_budgets") or {}
                budget = budgets.get(self.reasoning_effort)
                if budget is None:
                    raise ReasoningConfigurationError(
                        f"Missing thinking budget for reasoning effort: {self.reasoning_effort}"
                    )
                thinking["budget_tokens"] = budget

        extra_body["thinking"] = thinking
        completion_kwargs["extra_body"] = self._translate_thinking_flag(extra_body)



def legacy_reasoning_wire_parameters(*, model_id, base_url, model_factory, capability=None,
                                     effort=None, budget=None, extra_body=None):
    """Export actual legacy body fields without allocating a client or sending a request."""
    policy = LegacyReasoningPolicy()
    policy.model_id = model_id
    policy.api_base_url = base_url
    policy.model_factory = (model_factory or "").lower()
    policy.reasoning_capability = deepcopy(capability)
    policy.reasoning_effort = effort
    policy.reasoning_budget_tokens = budget
    parameters = {}
    if extra_body:
        parameters["extra_body"] = policy._translate_thinking_flag(deepcopy(extra_body))
    policy._apply_reasoning_control(parameters)
    body = parameters.pop("extra_body", {})
    # The OpenAI SDK merges extra_body over ordinary completion parameters.
    return deepcopy({**parameters, **body})
