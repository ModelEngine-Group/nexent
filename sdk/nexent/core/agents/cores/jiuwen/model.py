# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Jiuwen's model interface over Nexent's single model transport service."""

import json
import logging
import time
import uuid
from contextlib import aclosing
from copy import deepcopy
from types import SimpleNamespace

from jsonschema import ValidationError, validate
from openjiuwen.core.foundation.llm import Model
from openjiuwen.core.foundation.llm.schema.config import ModelRequestConfig
from openjiuwen.core.foundation.llm.schema.message import AssistantMessage, UsageMetadata
from openjiuwen.core.foundation.llm.schema.message_chunk import AssistantMessageChunk
from openjiuwen.core.foundation.llm.schema.tool_call import ToolCall as NativeToolCall

from nexent.core.agents.cores.jiuwen.clarification import (
    WORKBENCH_CONFIRMATION_REQUIRED,
    ClarificationRequested,
    InvalidClarification,
)
from nexent.core.agents.cores.jiuwen.messages import resource_view
from nexent.core.agents.cores.jiuwen.protocol import EXECUTION_TOOL, JiuwenProtocolError, parse_execution_blocks
from nexent.core.agents.output.answer import AnswerBoundaryError, normalize_public_answer
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.model_service.contracts import ModelError
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.model_service.resource_conversion import ResourceConverterRegistry
from nexent.core.model_service.service import ModelServiceError


logger = logging.getLogger(__name__)

_VERIFICATION_PENDING = "NL2AGENT_VERIFICATION_PENDING"
_GENERATION_PENDING = "NL2AGENT_GENERATION_PENDING"
_GENERATION_ACTIONS = {
    "prepare": "Follow the trusted draft state. Initialize the name only if missing, then save the description.",
    "save_description": "The name is saved. Call nl2a_save_agent_draft_fields with only the description next.",
    "discover_resources": "Call nl2a_discover_requirements for all resource needs in the original request next.",
    "prepare_search_queries": "Call nl2a_discover_requirements with search_queries for the returned requirement IDs.",
    "verify_resources": "Call nl2a_discover_requirements without arguments if needed and verify its current batch.",
    "show_resource_card": "Call nl2a_show_resource_card to resolve whether the user needs a resource confirmation.",
    "generate_prompt": "Read trusted bound resources with nl2a_read_generation_context and save the Prompt separately.",
    "finalize": "Save any missing greeting_message and example_questions, then validate the completed draft.",
    "validate": "Call nl2a_validate_agent_generation_complete now and wait for its actual result.",
}
_ARGUMENT_ERRORS = frozenset({
    "INVALID_TOOL_ARGUMENTS", "JIUWEN_NESTED_EXECUTION_BLOCK",
    "JIUWEN_INVALID_EXECUTION_BLOCK", "JIUWEN_EMPTY_EXECUTION_BLOCK", "JIUWEN_INVALID_CLARIFICATION",
})


def _text(parts):
    if any(part.get("type") != "text" or not isinstance(part.get("text"), str) for part in parts):
        raise JiuwenProtocolError("JIUWEN_RESPONSE_CONTENT_UNSUPPORTED")
    return "".join(part["text"] for part in parts)


class JiuwenServiceModel(Model):
    """Own one detached outlet; never construct or invoke a provider client."""

    def __init__(self, service, profile, scope, *, prefix=(), run_id=None, deadline=None,
                 on_step=None, on_event=None, validate_input=None, prepare_messages=None,
                 on_error=None, on_recovery=None, delegation=None, artifact_output=False, clarification=None,
                 verification_pending=None, full_generation_pending=None):
        # Model's public invoke/stream seam is used without its provider-client constructor.
        self.service = service
        self.profile = ResolvedModelProfile.model_validate(profile.model_dump())
        self.scope = scope
        self.prefix = deepcopy(prefix)
        self.run_id = run_id
        self.deadline = deadline
        self.on_step, self.on_event, self.validate_input = on_step, on_event, validate_input
        self.model_config = ModelRequestConfig(model=self.profile.identity.request_model_id)
        self.model_client_config = None
        self._client = None
        self.artifact_output = artifact_output
        self.text_protocol = not artifact_output and self.profile.capabilities.tools.status != "supported"
        self.converter = ResourceConverterRegistry().resolve(self.profile.bindings.native_converter)
        self.prepare_messages = prepare_messages
        self._agent_context = None
        self.on_error = on_error
        self.last_usage = None
        self.last_message = None
        self.on_recovery = on_recovery
        self.argument_corrections = 0
        self.response_corrections = 0
        self.verification_pending = verification_pending
        self._verification_correction_used = False
        self.full_generation_pending = full_generation_pending
        self._generation_corrections = set()
        self.logical_requests = 0
        self.delegation = delegation
        self.delegation_corrections = 0
        self._delegation_failure = None
        self.clarification = clarification
        self._clarification_form = None
        self._workbench_confirmation_required = False

    def _check_cancelled(self):
        if self.scope.cancelled:
            raise RunTerminated()
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise ModelServiceError(ModelError(category="MODEL_RUN_DEADLINE", scope="transport",
                retryable=False, safe_message="Model deadline exceeded", request_id=self.run_id or "jiuwen"))

    def _request(self, messages, tools, streaming, kwargs):
        self._check_cancelled()
        if self._delegation_failure is not None:
            raise ModelServiceError(self._delegation_failure)
        # Harness routing hints are accepted, but generation settings cannot override the snapshot.
        allowed = {"model", "temperature", "top_p", "max_tokens", "stop", "output_parser", "timeout"}
        if set(kwargs) - allowed:
            raise JiuwenProtocolError("JIUWEN_UNSUPPORTED_MODEL_OPTIONS")
        for key in allowed - {"model"}:
            if kwargs.get(key) is not None:
                raise JiuwenProtocolError("JIUWEN_RUNTIME_PARAMETER_OVERRIDE")
        if kwargs.get("model") not in (None, "", self.profile.identity.request_model_id):
            raise JiuwenProtocolError("JIUWEN_MODEL_IDENTITY_MISMATCH")
        view = self._resource_view(messages, tools)
        if self.validate_input is not None:
            self.validate_input(view)
        self.logical_requests += 1
        request = self.converter.convert(view, self.profile, stream=streaming, run_id=self.run_id).request
        if self.on_step is not None:
            self.on_step(request)
        return request

    def _resource_view(self, messages, tools):
        view = resource_view(messages, tools, prefix=self.prefix, text_protocol=self.text_protocol)
        if self.delegation is not None:
            terminal = [tool for tool in view.tool_definitions
                        if self.clarification is not None and tool.name == self.clarification.name]
            view = self.delegation.constrain(view)
            if terminal and not any(tool.name == self.clarification.name for tool in view.tool_definitions):
                view = view.model_copy(update={"tool_definitions": [*view.tool_definitions, *terminal]})
        return view

    def preview_request(self, messages, tools):
        """Use the sending conversion without attempts, effects or network IO."""
        return self.converter.convert(self._resource_view(messages, tools), self.profile,
            request_id="context-preview", run_id=self.run_id).request

    def _fail(self, request, category, *, reason=None):
        error = ModelError(
            category=category, scope="protocol", retryable=False, safe_message=category,
            request_id=request.request_id,
            diagnostic_code=reason,
        )
        raise ModelServiceError(error) from None

    def _reject_arguments(self, request, call, reason, *, rule=None, schema_path=(), missing_fields=()):
        logger.warning(
            "event=jiuwen_model_action_rejected category=INVALID_TOOL_ARGUMENTS reason=%s "
            "run_id=%s request_id=%s tool=%r call_index=%s rule=%s schema_path=%r missing_fields=%r",
            reason, self.run_id, request.request_id, call.name, call.index, rule, schema_path, missing_fields,
        )
        self._fail(request, "INVALID_TOOL_ARGUMENTS", reason=reason)

    def _completion(self, message, request, definitions):
        self._check_cancelled()
        self._clarification_form = None
        if message.refusal is not None:
            self._fail(request, "MODEL_RESPONSE_REFUSED")
        if message.finish_reason not in {"stop", "tool_calls"}:
            self._fail(request, "MODEL_RESPONSE_INCOMPLETE" if message.finish_reason == "length"
                       else "MODEL_FINISH_REASON_UNSUPPORTED")
        try:
            content, reasoning = _text(message.content_parts), _text(message.reasoning_parts)
        except JiuwenProtocolError as error:
            self._fail(request, str(error))
        if self.text_protocol and message.tool_calls:
            self._fail(request, "JIUWEN_UNEXPECTED_NATIVE_CALL")
        if self.text_protocol and message.finish_reason != "stop":
            self._fail(request, "JIUWEN_TOOL_FINISH_MISMATCH")
        if not self.text_protocol and bool(message.tool_calls) != (message.finish_reason == "tool_calls"):
            self._fail(request, "JIUWEN_TOOL_FINISH_MISMATCH")
        calls = []
        schemas = {tool.name: tool.input_schema for tool in definitions}
        for call in message.tool_calls:
            if call.name not in schemas or call.name == EXECUTION_TOOL:
                self._fail(request, "JIUWEN_UNAUTHORIZED_TOOL")
            if call.argument_error or not isinstance(call.parsed_arguments, dict):
                self._reject_arguments(request, call, call.argument_diagnostic or "arguments_unparsed")
            try:
                validate(call.parsed_arguments, schemas[call.name])
            except ValidationError as error:
                reason = {
                    "required": "arguments_required", "type": "arguments_wrong_type",
                    "additionalProperties": "arguments_extra_fields",
                    "enum": "arguments_unsupported_value", "const": "arguments_unsupported_value",
                }.get(error.validator, "arguments_schema_mismatch")
                missing = ()
                if error.validator == "required" and isinstance(error.instance, dict):
                    missing = tuple(key for key in error.validator_value if key not in error.instance)[:5]
                self._reject_arguments(
                    request, call, reason, rule=error.validator,
                    schema_path=tuple(error.absolute_schema_path)[:12], missing_fields=missing,
                )
            calls.append(NativeToolCall(id=call.provider_call_id, type="function", name=call.name,
                                        arguments=call.raw_arguments, index=call.index))
        if self.text_protocol:
            try:
                block = parse_execution_blocks(content)
            except JiuwenProtocolError as error:
                self._fail(request, str(error))
            if block is not None:
                calls.append(NativeToolCall(id="text_" + uuid.uuid4().hex, type="function", name=EXECUTION_TOOL,
                                            arguments=json.dumps({"code": block.code}), index=0))
        if not calls and not content.strip():
            self._fail(request, "MODEL_EMPTY_RESPONSE")
        if not calls and self.verification_pending is not None and self.verification_pending():
            self._fail(request, _VERIFICATION_PENDING)
        if not calls and self.full_generation_pending is not None and self.full_generation_pending():
            self._fail(request, _GENERATION_PENDING)
        if not calls and not self.artifact_output:
            try:
                normalize_public_answer(content)
            except AnswerBoundaryError as error:
                self._fail(request, str(error))
        if self.clarification is not None:
            try:
                self._clarification_form = self.clarification.form_for(calls, text_protocol=self.text_protocol)
            except InvalidClarification as error:
                logger.warning(
                    "event=jiuwen_model_action_rejected category=JIUWEN_INVALID_CLARIFICATION reason=%s "
                    "run_id=%s request_id=%s protocol=%s issues=%r",
                    error.reason, self.run_id, request.request_id,
                    "text" if self.text_protocol else "native", error.issues,
                )
                self._fail(request, str(error), reason=error.reason)
            if not self.text_protocol:
                if not calls and self.clarification.has_workbench_form_text(content):
                    self._workbench_confirmation_required = True
                if self._workbench_confirmation_required and (
                    self._clarification_form is None
                    or self._clarification_form.questions[0].id != "workbench_creation_mode"
                ):
                    self._fail(request, WORKBENCH_CONFIRMATION_REQUIRED)
        if self.delegation is not None and self._clarification_form is None:
            try:
                self.delegation.validate_calls(calls)
            except JiuwenProtocolError as error:
                self._fail(request, str(error))
        self.last_message, self.last_usage = message, message.usage
        usage = message.usage
        native_usage = None
        if usage.origin == "provider" and all(value is not None for value in (
            usage.input_tokens, usage.output_tokens, usage.total_tokens,
        )):
            native_usage = UsageMetadata(input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                                         total_tokens=usage.total_tokens)
        native = AssistantMessage(content=content, reasoning_content=reasoning or None,
                                tool_calls=calls or None, finish_reason="tool_calls" if calls else "stop",
                                usage_metadata=native_usage)
        self.last_native_message = native
        return native

    async def _invoke_once(self, messages, *, tools=None, **kwargs):
        if self.prepare_messages is not None:
            messages = await self.prepare_messages(messages, tools)
        request = self._request(messages, tools, False, kwargs)
        message = await self.service.ainvoke(request, self.profile, scope=self.scope, deadline=self.deadline,
                                             **({"agent_context": self._agent_context} if self._agent_context is not None else {}))
        definitions = resource_view(messages, tools).tool_definitions
        native = self._completion(message, request, definitions)
        if self.on_event is not None:
            self.on_event(SimpleNamespace(type="message_completed", message=message))
        if self._clarification_form is not None:
            raise ClarificationRequested(self._clarification_form)
        return native

    async def _stream_once(self, messages, *, tools=None, **kwargs):
        if self.prepare_messages is not None:
            messages = await self.prepare_messages(messages, tools)
        request = self._request(messages, tools, True, kwargs)
        definitions = resource_view(messages, tools).tool_definitions
        emitted_text, emitted_reasoning = [], []
        completed = False
        try:
            async with self.service.astream(request, self.profile, scope=self.scope, deadline=self.deadline,
                                            empty_response_policy="fail",
                                            **({"agent_context": self._agent_context} if self._agent_context is not None else {})) as events:
                async for event in events:
                    self._check_cancelled()
                    if completed:
                        self._fail(request, "MODEL_DUPLICATE_COMPLETION")
                    if self.on_event is not None and event.type not in {"message_completed", "error"}:
                        self.on_event(event)
                    if event.type == "error":
                        raise ModelServiceError(event.error)
                    if event.type == "text_delta":
                        if event.content_kind == "refusal":
                            self._fail(request, "MODEL_RESPONSE_REFUSED")
                        emitted_text.append(event.delta)
                        yield AssistantMessageChunk(content=event.delta)
                    elif event.type == "reasoning_delta":
                        emitted_reasoning.append(event.delta)
                        yield AssistantMessageChunk(content="", reasoning_content=event.delta)
                    elif event.type == "message_completed":
                        native = self._completion(event.message, request, definitions)
                        if ((emitted_text and "".join(emitted_text) != native.content)
                                or (emitted_reasoning and "".join(emitted_reasoning)
                                    != (native.reasoning_content or ""))):
                            self._fail(request, "MODEL_STREAM_COMPLETION_MISMATCH")
                        if self.on_event is not None:
                            self.on_event(event)
                        if self._clarification_form is not None:
                            raise ClarificationRequested(self._clarification_form)
                        completed = True
                        # Only complete validated calls are exposed; never forward tool_call_delta to execution.
                        yield AssistantMessageChunk(
                            content="" if emitted_text else native.content,
                            reasoning_content=None if emitted_reasoning else native.reasoning_content,
                            tool_calls=native.tool_calls, finish_reason=native.finish_reason,
                            usage_metadata=native.usage_metadata,
                        )
        except ModelServiceError:
            raise
        if not completed:
            self._fail(request, "MODEL_STREAM_INCOMPLETE")


    def _correct(self, messages, error, step_corrections):
        """Retry only validated model completions, never transports or executed actions."""
        try:
            self._check_cancelled()
        except ModelServiceError as expired:
            if self.on_error is not None:
                self.on_error(expired.error)
            raise
        if self.on_error is not None:
            self.on_error(error)
        category = error.category
        generation_action = None
        if category in _ARGUMENT_ERRORS:
            if step_corrections or self.argument_corrections >= 3:
                return None
            self.argument_corrections += 1
            kind = "arguments"
        elif category in {
            "MODEL_EMPTY_RESPONSE", "MODEL_RESPONSE_INCOMPLETE", "MODEL_STREAM_INCOMPLETE",
            "JIUWEN_INCOMPLETE_EXECUTION_BLOCK", "JIUWEN_TOOL_FINISH_MISMATCH", "JIUWEN_FINAL_OUTPUT_INVALID",
            WORKBENCH_CONFIRMATION_REQUIRED,
        } or (
            category == "MODEL_PROTOCOL_ERROR"
            and error.diagnostic_code in {"MODEL_TOOL_CALL_INVALID", "MODEL_RESPONSE_INCOMPLETE"}
        ):
            if self.response_corrections >= 1:
                return None
            self.response_corrections += 1
            kind = "response"
        elif category == _VERIFICATION_PENDING:
            if self._verification_correction_used:
                return None
            self._verification_correction_used = True
            kind = "verification"
        elif category == _GENERATION_PENDING:
            generation_action = self.full_generation_pending()
            if generation_action not in _GENERATION_ACTIONS or generation_action in self._generation_corrections:
                return None
            self._generation_corrections.add(generation_action)
            kind = "generation"
        elif category == "JIUWEN_DELEGATION_REQUIRED":
            if self.delegation is None or not self.delegation.allow_correction():
                self._delegation_failure = error
                return None
            self.delegation_corrections += 1
            kind = "delegation"
        else:
            return None
        # Invalid calls never enter native history. Reuse only the authoritative, pre-step messages.
        current = [{"role": "user", "content": messages}] if isinstance(messages, str) else deepcopy(messages)
        if category == _VERIFICATION_PENDING:
            guidance = (
                "Call nl2a_verify_requirements with the latest pending verification_batch_id and assessments "
                "for every candidate in that batch. If the batch is missing from the observations, call "
                "nl2a_discover_requirements without arguments to recover it. Do not finalize or ask for confirmation yet."
            )
        elif category == _GENERATION_PENDING:
            guidance = (
                "The user requested full Agent creation. Continue with the next authorized tool action. "
                + _GENERATION_ACTIONS[generation_action]
                + " A partial draft update is not a final response."
            )
        elif category == WORKBENCH_CONFIRMATION_REQUIRED:
            guidance = self.clarification.workbench_repair_instruction()
        else:
            guidance = "Regenerate this model step with a complete answer or a complete authorized call matching its schema."
        current.insert(0, {"role": "system", "content": (
            f"The previous model response was rejected before any action was dispatched: {category}. {guidance} "
            "Use the existing tool observations; do not repeat completed actions."
            + (" " + self.delegation.instruction if kind == "delegation" else "")
        )})
        if self.on_recovery is not None:
            self.on_recovery({"kind": kind, "category": category, "request_id": str(error.request_id),
                "logical_request": self.logical_requests, "argument_corrections": self.argument_corrections,
                "response_corrections": self.response_corrections,
                "delegation_corrections": self.delegation_corrections})
        return current

    async def invoke(self, messages, *, tools=None, **kwargs):
        self._workbench_confirmation_required = False
        owner = getattr(self.prepare_messages, "__self__", None)
        begin_context_request = getattr(owner, "begin_request", None)
        if begin_context_request is not None:
            begin_context_request()
        step_corrections = 0
        while True:
            try:
                return await self._invoke_once(messages, tools=tools, **kwargs)
            except ModelServiceError as failure:
                corrected = self._correct(messages, failure.error, step_corrections)
                if corrected is None:
                    raise
                step_corrections += failure.error.category in _ARGUMENT_ERRORS
                messages = corrected

    async def stream(self, messages, *, tools=None, **kwargs):
        self._workbench_confirmation_required = False
        owner = getattr(self.prepare_messages, "__self__", None)
        begin_context_request = getattr(owner, "begin_request", None)
        if begin_context_request is not None:
            begin_context_request()
        step_corrections = 0
        while True:
            try:
                # Public source events remain live; rejected chunks never enter native history.
                chunks = []
                async with aclosing(self._stream_once(messages, tools=tools, **kwargs)) as stream:
                    async for chunk in stream:
                        chunks.append(chunk)
                for chunk in chunks:
                    yield chunk
                return
            except ModelServiceError as failure:
                corrected = self._correct(messages, failure.error, step_corrections)
                if corrected is None:
                    raise
                step_corrections += failure.error.category in _ARGUMENT_ERRORS
                messages = corrected
