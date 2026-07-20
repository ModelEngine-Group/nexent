from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from smolagents.models import ChatMessage, MessageRole
from smolagents.utils import truncate_content

from ...monitor import get_monitoring_manager
from ..utils.observer import MessageObserver, ProcessType
from .agent_model import AgentVerificationConfig, GuardrailConfig, GuardrailRule


@dataclass
class VerificationCheck:
    name: str
    passed: bool
    reason: str = ""
    fix_hint: str = ""


@dataclass
class VerificationResult:
    passed: bool
    severity: str
    event: str
    score: float = 1.0
    phase: str = "pass"
    failed_criteria: List[str] = field(default_factory=list)
    repair_instruction: str = ""
    user_visible_note: str = ""
    checks: List[VerificationCheck] = field(default_factory=list)

    def to_payload(self, round_number: int = 0, message: Optional[str] = None) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "event": self.event,
            "round": round_number,
            "severity": self.severity,
            "score": round(float(self.score), 3),
            "failed_criteria": self.failed_criteria,
            "repair_instruction": self.repair_instruction,
            "user_visible_note": self.user_visible_note,
            "message": message or self.user_visible_note or self.repair_instruction,
            "passed": self.passed,
        }


class _SilentObserver:
    """Observer shim used to prevent verifier LLM tokens from appearing in chat UI."""

    current_mode = ProcessType.MODEL_OUTPUT_THINKING

    def add_model_new_token(self, _new_token):
        return None

    def add_model_reasoning_content(self, _reasoning_content):
        return None

    def flush_remaining_tokens(self):
        return None


GuardrailSource = Literal["new_input", "history", "tool_input", "tool_output"]

EffectiveAction = Literal["pass", "mask", "block", "terminate"]


class SeverityResolver:
    """Resolve ``(user_severity, source) -> effective_action``.

    Honors user intent unless the source can't block, per ``_BLOCK_TABLE``
    (block + new_input -> terminate, history/tool_output -> mask, tool_input
    -> block). mask/pass are source-independent. Hardcoded safety invariant,
    not user-configurable.
    """

    _BLOCK_TABLE: Dict[str, str] = {
        "new_input": "terminate",
        "history": "mask",
        "tool_input": "block",
        "tool_output": "mask",
    }

    @staticmethod
    def resolve(user_severity: str, source: str) -> str:
        """Resolve (user_severity, source) to the effective action.

        Args:
            user_severity: Severity the user configured (block/mask/pass).
            source: Where the content came from (new_input/history/tool_input/tool_output).

        Returns:
            The effective action (pass/mask/block/terminate).
        """
        if user_severity == "block":
            return SeverityResolver._BLOCK_TABLE.get(source, "mask")
        if user_severity in ("mask", "pass"):
            return user_severity
        # Unknown severity: fail-open.
        return "pass"

    @staticmethod
    def is_downgraded(user_severity: str, effective_action: str) -> bool:
        """True if the effective action differs from the user's severity.

        Args:
            user_severity: Severity the user configured.
            effective_action: Action resolved by ``resolve``.

        Returns:
            True if the resolver changed the user's severity.
        """
        return effective_action != user_severity


@dataclass
class GuardrailDecision:
    """The full result of one guardrail checkpoint evaluation.

    Carries both the verification result (for emit/feedback, unchanged in
    shape from before) and the resolved effective action + masked payload
    (for the executor to act on).
    """

    source: str
    user_severity: str
    effective_action: str
    downgraded: bool
    rule_name: str
    matched_texts: List[str]
    verification_result: "VerificationResult"
    # Masked payload, populated when effective_action == "mask":
    masked_messages: Optional[List[Dict[str, Any]]] = None
    cleaned_content: Optional[str] = None
    masked_args: Optional[tuple] = None
    masked_kwargs: Optional[Dict[str, Any]] = None

    @property
    def passed(self) -> bool:
        """True if the run may continue past this checkpoint."""
        return self.effective_action in ("pass", "mask")

    @property
    def message(self) -> str:
        """The user-visible note, or the repair instruction if absent."""
        vr = self.verification_result
        return vr.user_visible_note or vr.repair_instruction


class GuardrailEngine:
    """Pattern-matching guardrail engine for LLM input and tool output screening.

    Pre-compiles regex patterns (first match wins). All public methods are
    fail-open -- engine errors degrade to a pass so the guardrail never
    becomes an attack surface.

    Args:
        config: Guardrail configuration loaded from AgentVerificationConfig.
    """

    def __init__(self, config: GuardrailConfig) -> None:
        self._rules: List[tuple] = []
        self._default_action: str = config.default_action
        # Token substituted for matched spans when effective_action == "mask".
        self._mask_token: str = "***"
        # Circuit-breaker state: a repeated identical (rule, matched_text, source) block upgrades to terminate.
        self._breaker_last_sig: Optional[tuple] = None
        self._breaker_repeat: int = 0
        self._breaker_threshold: int = 2

        for rule in config.rules:
            try:
                compiled = re.compile(rule.pattern, re.IGNORECASE)
                self._rules.append((compiled, rule))
            except re.error:
                # Skip invalid patterns so one bad rule can't disable the engine.
                continue

    @property
    def rule_count(self) -> int:
        """Number of successfully compiled rules."""
        return len(self._rules)

    def check_input(
        self,
        input_messages: List[Dict[str, Any]],
        step_number: int,
    ) -> GuardrailDecision:
        """Screen the messages about to be sent to the LLM, per message.

        Each message is classified as ``new_input`` (latest user turn) or
        ``history`` and resolved via SeverityResolver. On ``mask`` all matching
        messages are redacted in a copy returned as ``masked_messages``; the
        overall action is the highest-rank across messages.

        Args:
            input_messages: Messages about to be sent to the LLM.
            step_number: Current ReAct step number, for telemetry.

        Returns:
            A GuardrailDecision; carries ``masked_messages`` when masking.
            Never raises -- engine failures degrade to a pass.
        """
        try:
            new_input_idx = self._find_new_input_index(input_messages)
            overall = "pass"
            chosen = None  # (rule, matched_text, source, user_severity)
            any_mask = False
            # Shallow-copy each message so we can rewrite content on mask.
            messages_copy = [
                (dict(m) if isinstance(m, dict) else m)
                for m in (input_messages or [])
            ]
            for i, msg in enumerate(messages_copy):
                source = "new_input" if i == new_input_idx else "history"
                screened = self._screen_message(msg, source)
                if screened is None:
                    continue
                eff, rule, matched_text, user_sev, masked_content = screened
                if self._action_rank(eff) > self._action_rank(overall):
                    overall = eff
                    chosen = (rule, matched_text, source, user_sev)
                if masked_content is not None:
                    any_mask = True
                    self._set_msg_text(msg, masked_content)

            if chosen is None:
                return self._pass_decision("new_input", "guardrail_input")

            rule, matched_text, source, user_sev = chosen
            eff = self._apply_breaker(rule.name, matched_text, source, overall)
            downgraded = SeverityResolver.is_downgraded(user_sev, eff)
            vr = self._build_vr(
                rule, matched_text, eff, "guardrail_input", source, downgraded
            )
            return GuardrailDecision(
                source=source,
                user_severity=user_sev,
                effective_action=eff,
                downgraded=downgraded,
                rule_name=rule.name,
                matched_texts=[matched_text],
                verification_result=vr,
                masked_messages=messages_copy if any_mask else None,
            )
        except Exception:
            # Fail-open: the engine's own bug must never block the agent.
            return self._pass_decision("new_input", "guardrail_input")

    def _screen_message(self, msg: Any, source: str) -> Optional[tuple]:
        """Scan one message and resolve its guardrail action.

        Args:
            msg: A chat message (dict or ChatMessage).
            source: Guardrail source for this message (new_input/history).

        Returns:
            A ``(effective_action, rule, matched_text, user_severity, masked_content)``
            tuple, or ``None`` if no rule matched. ``masked_content`` is the redacted
            text when the action is ``mask``, otherwise ``None``.
        """
        content = self._msg_text(msg)
        matches = self._scan(content)
        if not matches:
            return None
        first_rule = matches[0][1]
        user_sev = first_rule.severity or self._default_action
        eff = SeverityResolver.resolve(user_sev, source)
        matched_text = matches[0][2][0] if matches[0][2] else ""
        masked = self._mask_value(content, matches) if eff == "mask" else None
        return eff, first_rule, matched_text, user_sev, masked

    def check_output(
        self,
        observation: str,
        code_action: str,
        step_number: int,
        is_final_answer: bool,
    ) -> GuardrailDecision:
        """Screen a tool's observation before it enters agent memory.

        Source is ``tool_output`` -- the tool already ran, so ``block`` is not
        possible and SeverityResolver downgrades it to ``mask`` (matched spans
        are redacted in the observation, then written back). ``mask``/``pass``
        behave as configured.

        Args:
            observation: The tool's output text.
            code_action: The code_action that produced this observation.
            step_number: The current ReAct step number, for telemetry.
            is_final_answer: Whether this observation is a final-answer candidate.

        Returns:
            A GuardrailDecision; when masking, ``cleaned_content`` carries the
            redacted observation. Never raises -- engine failures degrade to a pass.
        """
        try:
            text = observation or ""
            matches = self._scan(text)
            if not matches:
                return self._pass_decision("tool_output", "guardrail_output")
            first_rule = matches[0][1]
            user_sev = first_rule.severity or self._default_action
            eff = SeverityResolver.resolve(user_sev, "tool_output")
            matched_text = matches[0][2][0] if matches[0][2] else ""
            eff = self._apply_breaker(first_rule.name, matched_text, "tool_output", eff)
            downgraded = SeverityResolver.is_downgraded(user_sev, eff)
            cleaned = None
            if eff == "mask":
                cleaned = text
                for compiled, _rule, _texts in matches:
                    try:
                        cleaned = compiled.sub(self._mask_token, cleaned)
                    except Exception:
                        pass
            vr = self._build_vr(
                first_rule, matched_text, eff, "guardrail_output",
                "tool_output", downgraded,
            )
            return GuardrailDecision(
                source="tool_output",
                user_severity=user_sev,
                effective_action=eff,
                downgraded=downgraded,
                rule_name=first_rule.name,
                matched_texts=matches[0][2],
                verification_result=vr,
                cleaned_content=cleaned,
            )
        except Exception:
            return self._pass_decision("tool_output", "guardrail_output")

    def check_tool_args(
        self,
        tool_name: str,
        args: tuple,
        kwargs: Dict[str, Any],
        step_number: int = 0,
    ) -> GuardrailDecision:
        """Screen the resolved arguments of a tool call before it executes.

        Source is ``tool_input`` -- ``block`` is genuine (the tool doesn't run),
        ``mask`` redacts string args and runs on the masked values. Sees actual
        runtime arg values (inside the wrapped ``forward``), so it also catches
        content that flowed in via a variable or a prior tool's return.

        Args:
            tool_name: Name of the tool whose call is being screened.
            args: Positional argument values as resolved at runtime.
            kwargs: Keyword argument values as resolved at runtime.
            step_number: Current ReAct step number, for telemetry.

        Returns:
            A GuardrailDecision; carries ``masked_args`` / ``masked_kwargs``
            when masking. Never raises -- engine failures degrade to a pass.
        """
        try:
            parts: List[str] = []
            for value in list(args) + list(kwargs.values()):
                if value is None:
                    continue
                try:
                    parts.append(str(value))
                except Exception:
                    # Skip unstringifiable values; one bad arg can't disable screening.
                    continue
            text = "\n".join(parts)
            matches = self._scan(text)
            if not matches:
                return self._pass_decision("tool_input", "guardrail_tool_input")
            first_rule = matches[0][1]
            user_sev = first_rule.severity or self._default_action
            eff = SeverityResolver.resolve(user_sev, "tool_input")
            matched_text = matches[0][2][0] if matches[0][2] else ""
            eff = self._apply_breaker(first_rule.name, matched_text, "tool_input", eff)
            downgraded = SeverityResolver.is_downgraded(user_sev, eff)
            masked_args = None
            masked_kwargs = None
            if eff == "mask":
                masked_args = tuple(self._mask_value(v, matches) for v in args)
                masked_kwargs = {
                    k: self._mask_value(v, matches) for k, v in kwargs.items()
                }
            vr = self._build_vr(
                first_rule, matched_text, eff, "guardrail_tool_input",
                "tool_input", downgraded,
            )
            return GuardrailDecision(
                source="tool_input",
                user_severity=user_sev,
                effective_action=eff,
                downgraded=downgraded,
                rule_name=first_rule.name,
                matched_texts=matches[0][2],
                verification_result=vr,
                masked_args=masked_args,
                masked_kwargs=masked_kwargs,
            )
        except Exception:
            return self._pass_decision("tool_input", "guardrail_tool_input")

    @staticmethod
    def _msg_role(msg: Any) -> str:
        """Role of a chat message as a lowercase string (dict or ChatMessage).

        Args:
            msg: A chat message (dict or smolagents ChatMessage).

        Returns:
            The role lowercased, or ``""`` if it has none.
        """
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role is None:
            return ""
        value = getattr(role, "value", None)
        return str(value if value is not None else role).lower()

    @staticmethod
    def _msg_text(msg: Any) -> str:
        """Best-effort text of a chat message (string, None, or OpenAI-style list parts).

        Args:
            msg: A chat message whose ``content`` may be a string, None, or a
                list of ``{"text": ...}``/``{"content": ...}`` parts.

        Returns:
            The concatenated text, or ``""`` if none can be extracted.
        """
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text is None:
                        text = item.get("content")
                    if text:
                        parts.append(str(text))
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts)
        return str(content)

    @staticmethod
    def _set_msg_text(msg: Any, text: str) -> None:
        """Write masked text back into a dict or ChatMessage message.

        Args:
            msg: The message to mutate (dict or ChatMessage).
            text: The redacted text to store as ``content``.
        """
        try:
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    msg["content"] = [{"type": "text", "text": text}]
                else:
                    msg["content"] = text
            else:
                content = getattr(msg, "content", None)
                if isinstance(content, list):
                    setattr(msg, "content", [{"type": "text", "text": text}])
                else:
                    setattr(msg, "content", text)
        except Exception:
            pass

    @staticmethod
    def _find_new_input_index(messages: List[Any]) -> int:
        """Index of the latest user message; every other message is history.

        Args:
            messages: Prompt messages (dict or ChatMessage).

        Returns:
            The index of the last user-role message, or ``-1`` if there is none.
        """
        idx = -1
        for i, msg in enumerate(messages or []):
            if GuardrailEngine._msg_role(msg) == "user":
                idx = i
        return idx

    def _scan(
        self, text: str
    ) -> List[tuple]:
        """Scan all rules; returns ``(compiled, rule, [matched_texts])`` for every match.

        First match decides the action; all matches are returned so mask can
        redact every occurrence.

        Args:
            text: Text to scan against every compiled rule.

        Returns:
            A list of ``(compiled_regex, rule, [matched_texts])`` for every rule
            that matched; empty if none.
        """
        results: List[tuple] = []
        if not text:
            return results
        for compiled, rule in self._rules:
            try:
                texts = [m.group(0) for m in compiled.finditer(text)]
            except Exception:
                continue
            if texts:
                results.append((compiled, rule, texts))
        return results

    def _mask_value(self, value: Any, matches: List[tuple]) -> Any:
        """Redact matched spans in a string arg value; non-strings pass through.

        Args:
            value: A single tool-call argument value.
            matches: Match tuples from ``_scan`` (compiled regex + rule + texts).

        Returns:
            The value with matched spans replaced by the mask token; non-string
            values are returned unchanged.
        """
        if not isinstance(value, str):
            return value
        out = value
        for compiled, _rule, _texts in matches:
            try:
                out = compiled.sub(self._mask_token, out)
            except Exception:
                pass
        return out

    @staticmethod
    def _action_rank(action: str) -> int:
        """Rank for the overall action: terminate > block > mask > pass.

        Args:
            action: One of pass/mask/block/terminate.

        Returns:
            Numeric rank (pass=0, mask=2, block=3, terminate=4); unknown -> 0.
        """
        return {"pass": 0, "mask": 2, "block": 3, "terminate": 4}.get(
            action, 0
        )

    def _apply_breaker(
        self, rule_name: str, matched_text: str, source: str, effective_action: str
    ) -> str:
        """Upgrade a repeated identical block to terminate (stops stubborn-retry loops).

        Args:
            rule_name: Name of the matched rule.
            matched_text: The text that matched the rule.
            source: Guardrail source (new_input/history/tool_input/tool_output).
            effective_action: Action resolved before the breaker is applied.

        Returns:
            ``terminate`` if the same (rule, matched_text, source) block repeats
            past the threshold, otherwise the input action unchanged.
        """
        if effective_action not in ("block", "terminate"):
            return effective_action
        sig = (rule_name, matched_text, source)
        if sig == self._breaker_last_sig:
            self._breaker_repeat += 1
        else:
            self._breaker_last_sig = sig
            self._breaker_repeat = 1
        if self._breaker_repeat >= self._breaker_threshold:
            return "terminate"
        return effective_action

    def _build_vr(
        self,
        rule: GuardrailRule,
        matched_text: str,
        effective_action: str,
        event: str,
        source: str,
        downgraded: bool,
    ) -> VerificationResult:
        """Build the VerificationResult (for emit/feedback) from a matched decision.

        Args:
            rule: The rule that matched.
            matched_text: The text that matched the rule.
            effective_action: Resolved action (pass/mask/block/terminate).
            event: Verification event name (e.g. ``guardrail_input``).
            source: Guardrail source (new_input/history/tool_input/tool_output).
            downgraded: Whether the action was downgraded from the user severity.

        Returns:
            The VerificationResult to emit/feed back for this match.
        """
        severity = {
            "terminate": "blocking",
            "block": "blocking",
            "mask": "warning",
            "pass": "info",
        }.get(effective_action, "info")
        phase = {
            "terminate": "blocked",
            "block": "blocked",
            "mask": "warning",
            "pass": "pass",
        }.get(effective_action, "pass")
        if effective_action == "terminate":
            note = f"Input terminated by guardrail: rule '{rule.name}' matched"
        elif effective_action == "block":
            note = f"Content blocked by rule '{rule.name}'"
        elif effective_action == "mask":
            note = f"Content masked by rule '{rule.name}'"
            if downgraded:
                note += " (downgraded from block: source is non-blockable)"
        else:
            note = ""
        return VerificationResult(
            passed=effective_action in ("pass", "mask"),
            severity=severity,
            event=event,
            phase=phase,
            failed_criteria=[rule.name] if rule.name else [],
            repair_instruction=(
                f"Guardrail rule '{rule.name}' matched: '{matched_text}'. "
                f"Source: {source}. Effective action: {effective_action}."
            ),
            user_visible_note=note,
            checks=[
                VerificationCheck(
                    name=rule.name,
                    passed=False,
                    reason=f"Pattern matched: {matched_text}",
                    fix_hint=rule.description
                    or "Revise the content to avoid the matched pattern.",
                )
            ] if rule.name else [],
        )

    def _pass_decision(self, source: str, event: str) -> GuardrailDecision:
        """Build a pass decision (no rule matched / fail-open).

        Args:
            source: Guardrail source (new_input/history/tool_input/tool_output).
            event: Verification event name (e.g. ``guardrail_input``).

        Returns:
            A GuardrailDecision whose effective action is ``pass``.
        """
        vr = VerificationResult(
            passed=True,
            severity="info",
            event=event,
            phase="pass",
        )
        return GuardrailDecision(
            source=source,
            user_severity="pass",
            effective_action="pass",
            downgraded=False,
            rule_name="",
            matched_texts=[],
            verification_result=vr,
        )


# Pre-built refusal for a terminal new_input block. {matched}=user's matched input, {rule}=rule name.
GUARDRAIL_REFUSAL_TPL = {
    "zh": (
        "您的输入包含受限内容「{matched}」，已根据安全策略「{rule}」中止处理。\n"
        "原因：该内容被配置为禁止输入。\n"
        "建议：请移除或替换该内容后重新提问。\n"
        "如需调整规则，请联系管理员在护栏配置中修改。"
    ),
    "en": (
        'Your input contains restricted content "{matched}" and was halted by '
        'safety policy "{rule}".\n'
        "Reason: this content is configured as a blocked input.\n"
        "Suggestion: remove or replace it and try again.\n"
        "To adjust the rule, contact an administrator in the guardrail configuration."
    ),
}


def _guardrail_locale(text: str) -> str:
    """Pick zh/en from the language of ``text`` (CJK -> zh, else en).

    Args:
        text: The text whose language to detect.

    Returns:
        ``"zh"`` if the text contains CJK characters, otherwise ``"en"``.
    """
    if any("一" <= ch <= "鿿" for ch in (text or "")):
        return "zh"
    return "en"


def latest_user_message_text(messages: List[Any]) -> str:
    """Best-effort text of the latest user-role message in ``messages``.

    Args:
        messages: Prompt messages as plain dicts or smolagents ChatMessage objects,
            with string or OpenAI-style list-part content.

    Returns:
        The latest user message text, or "" if there is none.
    """
    last_idx = -1
    for i, msg in enumerate(messages or []):
        role = getattr(msg, "role", None) if not isinstance(msg, dict) else msg.get("role")
        value = getattr(role, "value", None)
        role_str = str(value if value is not None else role).lower()
        if role_str == "user":
            last_idx = i
    if last_idx < 0:
        return ""
    msg = messages[last_idx]
    content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") if item.get("text") is not None else item.get("content")
                if text:
                    parts.append(str(text))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return str(content)


def render_guardrail_refusal(decision: "GuardrailDecision", messages: List[Any]) -> str:
    """Render the pre-built refusal for a terminal new_input block.

    Args:
        decision: The guardrail decision (supplies matched text + rule name).
        messages: The prompt messages, used to pick zh/en by the user's language.

    Returns:
        The localized refusal string. No LLM call is made; the caller ends the run.
    """
    matched = decision.matched_texts[0] if decision.matched_texts else ""
    user_text = latest_user_message_text(messages)
    if not matched:
        matched = user_text
    tpl = GUARDRAIL_REFUSAL_TPL[_guardrail_locale(user_text)]
    return tpl.format(matched=matched or "", rule=decision.rule_name or "")


# Pre-built refusal for a terminal tool_input block. {matched}=blocked arg, {rule}=rule name, {tool}=tool name.
GUARDRAIL_TOOL_INPUT_REFUSAL_TPL = {
    "zh": (
        "工具「{tool}」的调用入参包含受限内容「{matched}」，已根据安全策略「{rule}」中止处理。\n"
        "原因：该内容被配置为禁止输入。\n"
        "建议：请调整请求内容后重新提问。\n"
        "如需调整规则，请联系管理员在护栏配置中修改。"
    ),
    "en": (
        'The call to tool "{tool}" contained restricted content "{matched}" in its '
        'arguments and was halted by safety policy "{rule}".\n'
        "Reason: this content is configured as a blocked input.\n"
        "Suggestion: adjust your request and try again.\n"
        "To adjust the rule, contact an administrator in the guardrail configuration."
    ),
}


def render_tool_input_refusal(decision: "GuardrailDecision", tool_name: str) -> str:
    """Render the pre-built refusal for a terminal tool_input block.

    Args:
        decision: The guardrail decision (supplies matched text + rule name).
        tool_name: The tool whose call was blocked.

    Returns:
        The localized refusal string. Locale follows the matched content's language.
    """
    matched = decision.matched_texts[0] if decision.matched_texts else ""
    tpl = GUARDRAIL_TOOL_INPUT_REFUSAL_TPL[_guardrail_locale(matched)]
    return tpl.format(matched=matched or "", rule=decision.rule_name or "", tool=tool_name or "")


class VerificationController:
    """Layered verification for critical ReAct events and final answers."""

    _ERROR_RE = re.compile(
        r"(traceback|exception|error:|failed|timeout|unauthorized|permission denied)",
        re.IGNORECASE,
    )
    _EMPTY_RE = re.compile(r"^\s*(execution logs:\s*)?(last output from code snippet:\s*)?\s*$", re.IGNORECASE)
    _RAW_TAG_RE = re.compile(r"</?(code|RUN)>|<DISPLAY:[^>]+>|</DISPLAY>", re.IGNORECASE)
    _CITATION_RE = re.compile(r"\[\[[a-e]\d+\]\]")
    _LIGHTWEIGHT_CONVERSATION_RE = re.compile(
        r"^\s*(你好|您好|嗨|哈喽|hello|hi|hey|早上好|上午好|中午好|下午好|晚上好|"
        r"在吗|你是谁|你会干什么|介绍一下你自己|谢谢|好的|好|可以|没事|再见|"
        r"thanks|thank you|ok|bye)\s*[。！？!?.]*\s*$",
        re.IGNORECASE,
    )
    _EVIDENCE_DEMAND_RE = re.compile(
        r"(搜索|检索|查询|查找|分析|调研|根据|基于|引用|证据|来源|文档|文件|代码|项目|数据库|"
        r"最新|今天|昨天|现在|当前|执行|运行|部署|修复|报错|日志|search|retrieve|cite|source|"
        r"evidence|file|code|database|latest|today|run|execute|deploy|error|log)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        config: AgentVerificationConfig,
        observer: MessageObserver,
        agent_name: str,
        model: Any,
        logger: Any = None,
    ) -> None:
        self.config = config
        self.observer = observer
        self.agent_name = agent_name
        self.model = model
        self.logger = logger

        # Instantiate the guardrail engine if guardrail config is present and enabled.
        self.guardrail_engine: Optional[GuardrailEngine] = None
        guardrail_cfg = getattr(config, "guardrail_config", None)
        if guardrail_cfg and guardrail_cfg.enabled:
            self.guardrail_engine = GuardrailEngine(guardrail_cfg)

    def is_enabled(self) -> bool:
        return bool(self.config and self.config.enabled)

    def emit(self, result: VerificationResult, round_number: int = 0, message: Optional[str] = None) -> None:
        if not self.is_enabled():
            return
        try:
            display_message = message or self._build_display_message(result)
            self.observer.add_message(
                self.agent_name,
                ProcessType.VERIFICATION,
                json.dumps(result.to_payload(round_number, display_message), ensure_ascii=False),
            )
        except Exception:
            if self.logger:
                self.logger.log("Failed to emit verification event")

    def _build_display_message(self, result: VerificationResult) -> str:
        if result.passed and result.phase in {"pass", "final_pass"}:
            prefix = "最终自检通过" if result.phase == "final_pass" else "基础自检通过"
            summary = self._build_pass_summary(result)
            return f"{prefix}：{summary}" if summary else prefix

        if result.phase in {"warning", "blocked", "repair", "final_fail"}:
            note = result.user_visible_note or result.repair_instruction
            if note:
                prefix = {
                    "warning": "自检发现需关注项",
                    "blocked": "自检已阻断",
                    "repair": "自检未通过，正在修正",
                    "final_fail": "最终自检未通过",
                }.get(result.phase, "自检提示")
                return f"{prefix}：{note}"

        return result.user_visible_note or result.repair_instruction or ""

    def _build_pass_summary(self, result: VerificationResult) -> str:
        if result.event == "tool_precheck":
            return "动作非空、语法正常，未发现越权风险"
        if result.event == "retrieval":
            return "检索返回可用内容，未发现错误信号"
        if result.event == "handoff":
            return "子任务返回可用结论，未发现错误信号"
        if result.event in {"tool_result", "code_execution"}:
            return "执行结果非空，未发现错误信号"

        if result.event == "final_answer":
            if "Lightweight conversational task" in (result.user_visible_note or ""):
                return "轻量对话无需外部证据，答案非空且格式正常"

            labels = self._passed_check_labels(result.checks)
            if labels:
                return "、".join(labels[:3])
            if result.user_visible_note:
                return result.user_visible_note
            return "答案满足当前任务要求，未发现阻断问题"

        labels = self._passed_check_labels(result.checks)
        return "、".join(labels[:3])

    def _passed_check_labels(self, checks: List[VerificationCheck]) -> List[str]:
        label_map = {
            "non_empty_code": "动作非空",
            "python_syntax": "语法正常",
            "action_scope": "未发现越权风险",
            "tool_relevance_signal": "动作与任务相关",
            "observation_present": "结果非空",
            "tool_error_handled": "未发现未处理错误",
            "retrieval_has_evidence": "检索证据可用",
            "handoff_has_substance": "子任务结论可用",
            "final_answer_non_empty": "答案非空",
            "no_unresolved_raw_tags": "无内部标记",
            "no_unresolved_placeholders": "无占位符",
            "previous_errors_acknowledged": "未发现未处理错误",
            "intent_coverage": "覆盖用户目标",
            "evidence_grounding": "证据支撑充分",
            "citation_integrity": "引用格式正常",
            "format_safety": "格式安全",
            "tool_error_handling": "工具错误已处理",
        }
        ordered_names = [
            "intent_coverage",
            "evidence_grounding",
            "tool_error_handling",
            "citation_integrity",
            "format_safety",
            "final_answer_non_empty",
            "no_unresolved_raw_tags",
            "no_unresolved_placeholders",
            "previous_errors_acknowledged",
            "observation_present",
            "tool_error_handled",
            "retrieval_has_evidence",
            "handoff_has_substance",
            "non_empty_code",
            "python_syntax",
            "action_scope",
            "tool_relevance_signal",
        ]
        passed_names = {check.name for check in checks if check.passed}
        return [label_map[name] for name in ordered_names if name in passed_names and name in label_map]

    def verify_before_tool_call(
        self,
        code_action: str,
        step_number: int,
        available_tool_names: Optional[List[str]] = None,
    ) -> VerificationResult:
        if not self._should_verify_step("tool_precheck"):
            return self._pass("tool_precheck")

        checks: List[VerificationCheck] = []
        code_text = code_action or ""

        checks.append(VerificationCheck(
            name="non_empty_code",
            passed=bool(code_text.strip()),
            reason="" if code_text.strip() else "The generated action code is empty.",
            fix_hint="Generate a concrete tool call or a final answer.",
        ))

        syntax_ok = True
        try:
            ast.parse(code_text)
        except SyntaxError as exc:
            syntax_ok = False
            checks.append(VerificationCheck(
                name="python_syntax",
                passed=False,
                reason=f"Python syntax error: {exc}",
                fix_hint="Rewrite the action as valid Python inside <code>...</code>.",
            ))
        if syntax_ok:
            checks.append(VerificationCheck(name="python_syntax", passed=True))

        dangerous_terms = [
            "__import__",
            "eval(",
            "exec(",
            "subprocess",
            "os.system",
            "shutil.rmtree",
            "socket.",
        ]
        dangerous_hits = [term for term in dangerous_terms if term in code_text]
        checks.append(VerificationCheck(
            name="action_scope",
            passed=not dangerous_hits,
            reason=f"Potentially unsafe code terms: {', '.join(dangerous_hits)}" if dangerous_hits else "",
            fix_hint="Use the platform-provided tools instead of direct system or network operations.",
        ))

        if "final_answer(" not in code_text and available_tool_names:
            used_tools = [name for name in available_tool_names if re.search(rf"\b{re.escape(name)}\s*\(", code_text)]
            checks.append(VerificationCheck(
                name="tool_relevance_signal",
                passed=bool(used_tools) or "print(" in code_text,
                reason="" if used_tools or "print(" in code_text else "No known tool call or printed observation was detected.",
                fix_hint="Call a relevant tool with keyword arguments, or print the evidence needed for the next step.",
            ))

        return self._result_from_checks(
            event="tool_precheck",
            checks=checks,
            blocking_names={"non_empty_code", "python_syntax", "action_scope"},
            step_number=step_number,
        )

    def verify_after_tool_call(
        self,
        code_action: str,
        observation: str,
        step_number: int,
        is_final_answer: bool = False,
    ) -> VerificationResult:
        event = self._classify_step_event(code_action, is_final_answer)
        if not self._should_verify_step(event):
            return self._pass(event)

        observation_text = observation or ""
        checks = [
            VerificationCheck(
                name="observation_present",
                passed=not self._EMPTY_RE.match(observation_text),
                reason="" if observation_text.strip() else "The action produced no visible observation.",
                fix_hint="Retry with better parameters, inspect tool errors, or explain that evidence is unavailable.",
            ),
            VerificationCheck(
                name="tool_error_handled",
                passed=not self._ERROR_RE.search(observation_text),
                reason="The observation contains an error signal." if self._ERROR_RE.search(observation_text) else "",
                fix_hint="Do not ignore this tool error. Diagnose it, retry safely, or state the limitation.",
            ),
        ]

        if event == "retrieval":
            checks.append(VerificationCheck(
                name="retrieval_has_evidence",
                passed=not self._looks_empty_retrieval(observation_text),
                reason="Retrieval appears empty or has no usable evidence." if self._looks_empty_retrieval(observation_text) else "",
                fix_hint="Search again with refined terms or say that supporting evidence was not found.",
            ))

        if event == "handoff":
            checks.append(VerificationCheck(
                name="handoff_has_substance",
                passed=not self._looks_empty_handoff(observation_text),
                reason="The delegated agent returned no useful result." if self._looks_empty_handoff(observation_text) else "",
                fix_hint="Reassign a narrower task or proceed with clearly stated limitations.",
            ))

        return self._result_from_checks(
            event=event,
            checks=checks,
            blocking_names=set(),
            step_number=step_number,
        )

    def verify_before_final_answer(
        self,
        candidate: Any,
        observation: str,
        step_number: int,
    ) -> VerificationResult:
        if not self.is_enabled() or not self.config.final_verification_enabled:
            return self._pass("final_answer")

        answer = "" if candidate is None else str(candidate)
        observation_text = observation or ""
        recent_error_signal = self._has_recent_error_signal(observation_text)
        checks = [
            VerificationCheck(
                name="final_answer_non_empty",
                passed=bool(answer.strip()),
                reason="" if answer.strip() else "The final answer candidate is empty.",
                fix_hint="Produce a concise answer or an explicit inability summary.",
            ),
            VerificationCheck(
                name="no_unresolved_raw_tags",
                passed=not self._RAW_TAG_RE.search(answer),
                reason="The final answer still contains internal execution/display tags." if self._RAW_TAG_RE.search(answer) else "",
                fix_hint="Convert internal tags to user-facing Markdown before answering.",
            ),
            VerificationCheck(
                name="no_unresolved_placeholders",
                passed=not any(marker in answer for marker in ["{{", "}}", "<TODO>", "TODO:"]),
                reason="The final answer contains unresolved placeholders." if any(marker in answer for marker in ["{{", "}}", "<TODO>", "TODO:"]) else "",
                fix_hint="Replace placeholders with real content or remove them.",
            ),
            VerificationCheck(
                name="previous_errors_acknowledged",
                passed=not recent_error_signal or self._mentions_limitation(answer),
                reason="A recent error signal is not acknowledged in the final answer." if recent_error_signal and not self._mentions_limitation(answer) else "",
                fix_hint="Acknowledge the failed operation, retry, or state what could not be verified.",
            ),
        ]

        return self._result_from_checks(
            event="final_answer",
            checks=checks,
            blocking_names={"final_answer_non_empty", "no_unresolved_raw_tags", "no_unresolved_placeholders"},
            step_number=step_number,
        )

    def verify_final_answer(
        self,
        task: str,
        candidate: Any,
        memory_summary: str,
        round_number: int,
    ) -> VerificationResult:
        if not self.is_enabled() or not self.config.final_verification_enabled:
            return self._pass("final_answer", phase="final_pass")

        start = self._pass("final_answer", phase="start")
        self.emit(start, round_number, "正在自检最终答案：检查答案完整性、格式和错误处理")

        deterministic = self.verify_before_final_answer(
            candidate=candidate,
            observation=memory_summary,
            step_number=round_number,
        )
        if not deterministic.passed:
            deterministic.phase = "final_fail"
            self.emit(deterministic, round_number)
            return deterministic

        if not self.config.llm_verification_enabled:
            deterministic.phase = "final_pass"
            self.emit(deterministic, round_number)
            return deterministic

        policy = self._build_final_verification_policy(task, memory_summary)
        if policy["task_profile"] == "lightweight_conversation":
            deterministic.phase = "final_pass"
            deterministic.user_visible_note = "Lightweight conversational task; deterministic checks passed."
            self.emit(deterministic, round_number)
            return deterministic

        llm_result = self._run_llm_verifier(task, candidate, memory_summary, round_number, policy)
        self.emit(llm_result, round_number)
        return llm_result

    def build_feedback_observation(self, result: VerificationResult) -> str:
        failed = ", ".join(result.failed_criteria) if result.failed_criteria else "verification"
        instruction = result.repair_instruction or "Revise the next action based on the failed verification checks."
        return (
            "\nVerification feedback:\n"
            f"- Event: {result.event}\n"
            f"- Severity: {result.severity}\n"
            f"- Failed criteria: {failed}\n"
            f"- Repair instruction: {instruction}\n"
        )

    def build_controlled_failure_answer(self, candidate: Any, result: VerificationResult) -> str:
        note = result.user_visible_note or "最终答案未能通过自验证。"
        failed = "、".join(result.failed_criteria) if result.failed_criteria else "verification"
        instruction = result.repair_instruction or "请补充更多信息或放宽任务约束后重试。"
        if self.config.fail_policy == "warn" and candidate:
            return f"{candidate}\n\n> 自验证提示：{note}"
        return (
            "我无法在当前步骤内给出已通过自验证的确定答案。\n\n"
            f"- 未通过项：{failed}\n"
            f"- 原因：{note}\n"
            f"- 建议：{instruction}"
        )

    def _should_verify_step(self, event: str) -> bool:
        return (
            self.is_enabled()
            and self.config.step_verification_enabled
            and event in set(self.config.critical_events)
        )

    def _run_llm_verifier(
        self,
        task: str,
        candidate: Any,
        memory_summary: str,
        round_number: int,
        policy: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        policy = policy or self._build_final_verification_policy(task, memory_summary)
        monitoring_manager = get_monitoring_manager()
        attrs = {
            "agent.verification.event": "final_answer",
            "agent.verification.round": round_number,
            "agent.verification.strictness": self.config.strictness,
            "agent.verification.fail_policy": self.config.fail_policy,
            "agent.verification.task_profile": policy["task_profile"],
            "agent.verification.evidence_required": policy["evidence_required"],
            "agent.verification.tool_error_check_required": policy["tool_error_check_required"],
        }
        with monitoring_manager.trace_agent_step(
            "agent.verify.final_answer",
            step_type="verification",
            **attrs,
        ):
            messages = self._build_verifier_messages(task, candidate, memory_summary, policy)
            saved_observer = getattr(self.model, "observer", None)
            if saved_observer is not None:
                try:
                    self.model.observer = _SilentObserver()
                except Exception:
                    pass
            try:
                chat_message: ChatMessage = self.model(messages)
                content = chat_message.content or ""
                result = self._parse_llm_verifier_result(content, policy)
                monitoring_manager.add_span_event(
                    "agent.verification.result",
                    {
                        "agent.verification.status": result.phase,
                        "agent.verification.score": result.score,
                        "agent.verification.failed_criteria": json.dumps(result.failed_criteria, ensure_ascii=False),
                    },
                )
                return result
            except Exception as exc:
                if self.logger:
                    self.logger.log(f"LLM verifier unavailable: {exc}")
                result = VerificationResult(
                    passed=True,
                    severity="warning",
                    event="final_answer",
                    phase="final_pass",
                    score=0.75,
                    failed_criteria=["verifier_unavailable"],
                    user_visible_note="Verifier was unavailable; deterministic checks passed.",
                )
                monitoring_manager.add_span_event(
                    "agent.verification.unavailable",
                    {"error.type": type(exc).__name__, "error.message": str(exc)},
                )
                return result
            finally:
                if saved_observer is not None:
                    try:
                        self.model.observer = saved_observer
                    except Exception:
                        pass

    def _build_verifier_messages(
        self,
        task: str,
        candidate: Any,
        memory_summary: str,
        policy: Optional[Dict[str, Any]] = None,
    ) -> List[ChatMessage]:
        policy = policy or self._build_final_verification_policy(task, memory_summary)
        clean_memory_summary = self._strip_internal_verification_feedback(memory_summary or "")
        system_prompt = (
            "You are a strict answer verifier for a ReAct agent. "
            "Check only the evidence shown to you. Do not reveal chain-of-thought. "
            "Return JSON only with keys: passed, score, status, failed_criteria, checks, "
            "revision_instruction, user_visible_note. "
            "Criteria: intent_coverage, evidence_grounding, tool_error_handling, citation_integrity, format_safety. "
            "Apply criteria conditionally: for lightweight conversational tasks such as greetings or capability chat, "
            "do not require external observations, citations, tool calls, or retrieval evidence. "
            "Only fail evidence_grounding when evidence_required is true. "
            "Only fail tool_error_handling when tool_error_check_required is true and the answer ignores an actual "
            "tool/code execution error in the evidence summary."
        )
        user_prompt = json.dumps(
            {
                "task": truncate_content(str(task), max_length=4000),
                "candidate_answer": truncate_content(str(candidate), max_length=4000),
                "react_evidence_summary": truncate_content(clean_memory_summary, max_length=6000),
                "task_profile": policy["task_profile"],
                "evidence_required": policy["evidence_required"],
                "tool_error_check_required": policy["tool_error_check_required"],
                "pass_score": self.config.pass_score,
                "strictness": self.config.strictness,
            },
            ensure_ascii=False,
        )
        return [
            ChatMessage(role=MessageRole.SYSTEM, content=[{"type": "text", "text": system_prompt}]),
            ChatMessage(role=MessageRole.USER, content=[{"type": "text", "text": user_prompt}]),
        ]

    def _parse_llm_verifier_result(
        self,
        content: str,
        policy: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        policy = policy or {
            "task_profile": "unknown",
            "evidence_required": True,
            "tool_error_check_required": True,
        }
        data = self._extract_json(content)
        passed = bool(data.get("passed"))
        score = float(data.get("score", 0.0))
        status = str(data.get("status") or ("pass" if passed else "revise"))
        failed_criteria = data.get("failed_criteria") or []
        if not isinstance(failed_criteria, list):
            failed_criteria = [str(failed_criteria)]
        failed_criteria = [str(item) for item in failed_criteria]
        ignored_criteria = set()
        if not policy.get("evidence_required", True):
            ignored_criteria.add("evidence_grounding")
        if not policy.get("tool_error_check_required", True):
            ignored_criteria.add("tool_error_handling")
        effective_failed_criteria = [
            criterion for criterion in failed_criteria if criterion not in ignored_criteria
        ]

        checks = []
        for item in data.get("checks") or []:
            if isinstance(item, dict):
                name = str(item.get("name", "unknown"))
                check_passed = bool(item.get("passed"))
                if name in ignored_criteria:
                    check_passed = True
                checks.append(VerificationCheck(
                    name=name,
                    passed=check_passed,
                    reason=str(item.get("reason", "")),
                    fix_hint=str(item.get("fix_hint", "")),
                ))

        threshold_passed = score >= self.config.pass_score
        if failed_criteria and not effective_failed_criteria:
            passed = True
            score = max(score, self.config.pass_score)
            threshold_passed = True
            status = "pass"
        effective_passed = passed and threshold_passed
        severity = "info" if effective_passed else "blocking"
        return VerificationResult(
            passed=effective_passed,
            severity=severity,
            event="final_answer",
            phase="final_pass" if effective_passed else "final_fail",
            score=score,
            failed_criteria=effective_failed_criteria if effective_failed_criteria else ([] if effective_passed else ["llm_verifier"]),
            repair_instruction=str(data.get("revision_instruction") or data.get("repair_instruction") or ""),
            user_visible_note=str(data.get("user_visible_note") or ""),
            checks=checks,
        )

    def _extract_json(self, content: str) -> Dict[str, Any]:
        text = (content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start:end + 1])
            raise

    def _result_from_checks(
        self,
        event: str,
        checks: List[VerificationCheck],
        blocking_names: set[str],
        step_number: int,
    ) -> VerificationResult:
        failed = [check for check in checks if not check.passed]
        blocking_failed = [check for check in failed if check.name in blocking_names]
        should_block = bool(blocking_failed) or (self.config.strictness == "strict" and bool(failed))
        passed = not should_block
        severity = "info" if not failed else ("blocking" if should_block else "warning")
        phase = "pass" if not failed else ("blocked" if should_block else "warning")
        score = max(0.0, 1.0 - 0.15 * len(failed) - 0.35 * len(blocking_failed))
        failed_names = [check.name for check in failed]
        repair_instruction = " ".join(check.fix_hint for check in failed if check.fix_hint).strip()
        user_visible_note = "；".join(check.reason for check in failed if check.reason).strip()
        result = VerificationResult(
            passed=passed,
            severity=severity,
            event=event,
            score=score,
            phase=phase,
            failed_criteria=failed_names,
            repair_instruction=repair_instruction,
            user_visible_note=user_visible_note,
            checks=checks,
        )
        monitoring_manager = get_monitoring_manager()
        with monitoring_manager.trace_agent_step(
            "agent.verify.step",
            step_type="verification",
            **{
                "agent.verification.event": event,
                "agent.verification.step_number": step_number,
                "agent.verification.status": phase,
                "agent.verification.severity": severity,
                "agent.verification.score": score,
                "agent.verification.failed_criteria": json.dumps(failed_names, ensure_ascii=False),
            },
        ):
            monitoring_manager.add_span_event(
                "agent.verification.result",
                {
                    "agent.verification.passed": passed,
                    "agent.verification.failed_criteria": json.dumps(failed_names, ensure_ascii=False),
                },
            )
        self.emit(result, step_number)
        return result

    def _build_final_verification_policy(self, task: str, memory_summary: str) -> Dict[str, Any]:
        clean_memory_summary = self._strip_internal_verification_feedback(memory_summary or "")
        lightweight = self._is_lightweight_conversation_task(task)
        evidence_required = (not lightweight) and bool(self._EVIDENCE_DEMAND_RE.search(task or ""))
        return {
            "task_profile": "lightweight_conversation" if lightweight else "task_oriented",
            "evidence_required": evidence_required,
            "tool_error_check_required": self._has_recent_error_signal(clean_memory_summary),
        }

    def _is_lightweight_conversation_task(self, task: str) -> bool:
        text = (task or "").strip()
        if not text:
            return False
        if self._LIGHTWEIGHT_CONVERSATION_RE.match(text):
            return True
        return False

    def _strip_internal_verification_feedback(self, text: str) -> str:
        lines = (text or "").splitlines()
        cleaned: List[str] = []
        skipping = False
        for line in lines:
            if line.strip() == "Verification feedback:":
                skipping = True
                continue
            if skipping:
                if not line.strip() or line.lstrip().startswith("- "):
                    continue
                skipping = False
            cleaned.append(line)
        return "\n".join(cleaned)

    def _has_recent_error_signal(self, text: str) -> bool:
        clean_text = self._strip_internal_verification_feedback(text or "")
        return bool(self._ERROR_RE.search(clean_text))

    def _classify_step_event(self, code_action: str, is_final_answer: bool) -> str:
        if is_final_answer:
            return "final_answer"
        code = code_action or ""
        lowered = code.lower()
        if "knowledge_base_search" in lowered or "search(" in lowered or "_search" in lowered:
            return "retrieval"
        if "task=" in code and re.search(r"\w+\s*\(\s*task\s*=", code):
            return "handoff"
        return "code_execution"

    def _pass(self, event: str, phase: str = "pass") -> VerificationResult:
        return VerificationResult(passed=True, severity="info", event=event, phase=phase)

    def _looks_empty_retrieval(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(marker in lowered for marker in ["no result", "no results", "[]", "未找到", "无结果", "没有找到"])

    def _looks_empty_handoff(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(marker in lowered for marker in ["cannot help", "unable", "no answer", "无法", "不能", "空"])

    def _mentions_limitation(self, answer: str) -> bool:
        lowered = (answer or "").lower()
        return any(marker in lowered for marker in ["无法", "失败", "错误", "未能", "cannot", "unable", "failed", "error", "limitation"])
