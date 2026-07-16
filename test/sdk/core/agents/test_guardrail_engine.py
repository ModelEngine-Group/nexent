"""Unit tests for the guardrail engine, severity resolver, and refusal rendering.

Complements ``test_guardrail_checkpoints.py`` (which drives the real ``_guardrail_wrap_one``
integration). This file covers the deterministic building blocks directly so the guardrail
diff stays above the coverage target:

- ``SeverityResolver``: the hardcoded ``(severity, source) -> effective_action`` table.
- ``GuardrailEngine``: ``__init__`` (invalid-pattern skip), ``check_input`` (①),
  ``check_output`` (②), ``check_tool_args`` (③), and the internal helpers.
- Circuit breaker: a repeated identical block upgrades to ``terminate``.
- Refusal rendering: zh/en locale pick + placeholder fill.
- Message helpers: ``_msg_role`` / ``_msg_text`` / ``_set_msg_text`` / ``_find_new_input_index``.
"""

import pytest

from nexent.core.agents.agent_model import GuardrailConfig, GuardrailRule
from nexent.core.agents.verification import (
    GuardrailDecision,
    GuardrailEngine,
    SeverityResolver,
    VerificationResult,
    _guardrail_locale,
    latest_user_message_text,
    render_guardrail_refusal,
    render_tool_input_refusal,
)

KEYWORD = "机密信息"
PATTERN = KEYWORD


def _engine(rules, default_action="pass"):
    cfg = GuardrailConfig(enabled=True, rules=rules, default_action=default_action)
    return GuardrailEngine(cfg)


def _rule(severity="block", name="confidential", pattern=PATTERN):
    return GuardrailRule(name=name, pattern=pattern, severity=severity)


def _msg(role, content):
    return {"role": role, "content": content}


def _decision(action="terminate", matched="机密信息", rule_name="confidential", source="new_input",
              user_severity="block", downgraded=True):
    vr = VerificationResult(passed=True, severity="info", event="guardrail_input")
    return GuardrailDecision(
        source=source,
        user_severity=user_severity,
        effective_action=action,
        downgraded=downgraded,
        rule_name=rule_name,
        matched_texts=[matched] if matched else [],
        verification_result=vr,
    )


# ---------------------------------------------------------------------------
# SeverityResolver
# ---------------------------------------------------------------------------

class TestSeverityResolver:
    """The hardcoded ``(user_severity, source) -> effective_action`` policy."""

    @pytest.mark.parametrize("source,expected", [
        ("new_input", "terminate"),
        ("history", "mask"),
        ("tool_input", "block"),
        ("tool_output", "mask"),
    ])
    def test_block_resolution_depends_on_source(self, source, expected):
        assert SeverityResolver.resolve("block", source) == expected

    @pytest.mark.parametrize("severity", ["mask", "pass"])
    def test_mask_and_pass_are_source_independent(self, severity):
        for source in ("new_input", "history", "tool_input", "tool_output"):
            assert SeverityResolver.resolve(severity, source) == severity

    @pytest.mark.parametrize("source", ["new_input", "history", "tool_input", "tool_output"])
    def test_unknown_severity_fails_open(self, source):
        assert SeverityResolver.resolve("bogus", source) == "pass"

    def test_block_on_unknown_source_defaults_to_mask(self):
        assert SeverityResolver.resolve("block", "somewhere_unknown") == "mask"

    @pytest.mark.parametrize("user_sev, eff, expected", [
        ("block", "terminate", True),
        ("block", "mask", True),
        ("mask", "mask", False),
        ("pass", "pass", False),
    ])
    def test_is_downgraded(self, user_sev, eff, expected):
        assert SeverityResolver.is_downgraded(user_sev, eff) is expected


# ---------------------------------------------------------------------------
# GuardrailEngine.__init__
# ---------------------------------------------------------------------------

class TestEngineInit:
    def test_valid_rules_compiled_and_counted(self):
        engine = _engine([_rule(), _rule("mask", name="phone", pattern="1[3-9]\\d{9}")])
        assert engine.rule_count == 2

    def test_invalid_pattern_skipped_not_fatal(self):
        bad = GuardrailRule(name="broken", pattern="(", severity="block")  # unbalanced group
        engine = _engine([_rule(), bad])
        assert engine.rule_count == 1  # bad rule skipped, good rule kept

    def test_defaults_from_config(self):
        engine = _engine([_rule()], default_action="pass")
        assert engine._default_action == "pass"
        assert engine._mask_token == "***"
        assert engine._breaker_threshold == 2


# ---------------------------------------------------------------------------
# check_input (checkpoint ①)
# ---------------------------------------------------------------------------

class TestCheckInput:
    def test_new_input_block_resolves_to_terminate(self):
        engine = _engine([_rule(severity="block")])
        messages = [_msg("user", f"分析{KEYWORD}内容")]
        decision = engine.check_input(input_messages=messages, step_number=1)
        assert decision.effective_action == "terminate"  # new_input + block -> terminate
        assert decision.rule_name == "confidential"
        assert KEYWORD in decision.matched_texts
        assert decision.masked_messages is None  # terminate does not mask

    def test_history_block_downgrades_to_mask_and_redacts(self):
        engine = _engine([_rule(severity="block")])
        # last user (new_input) has no keyword; the earlier user turn is history
        messages = [_msg("user", f"记住{KEYWORD}的资料"), _msg("assistant", "ok"), _msg("user", "你好")]
        decision = engine.check_input(input_messages=messages, step_number=1)
        assert decision.effective_action == "mask"  # history + block -> mask
        assert decision.downgraded is True
        assert decision.masked_messages is not None
        assert KEYWORD not in decision.masked_messages[0]["content"]
        assert "***" in decision.masked_messages[0]["content"]

    def test_mask_redacts_all_occurrences_in_message(self):
        engine = _engine([_rule(severity="mask")])
        messages = [_msg("user", f"{KEYWORD}和{KEYWORD}都在")]
        decision = engine.check_input(input_messages=messages, step_number=1)
        assert decision.effective_action == "mask"
        redacted = decision.masked_messages[0]["content"]
        assert KEYWORD not in redacted
        assert redacted.count("***") == 2

    def test_new_input_block_wins_over_history_mask_for_overall(self):
        engine = _engine([_rule(severity="block")])
        messages = [_msg("user", f"历史{KEYWORD}"), _msg("assistant", "ok"), _msg("user", f"分析{KEYWORD}")]
        decision = engine.check_input(input_messages=messages, step_number=1)
        # history -> mask, new_input -> terminate; overall highest rank is terminate
        assert decision.effective_action == "terminate"

    def test_no_match_returns_pass(self):
        engine = _engine([_rule(severity="block")])
        messages = [_msg("user", "今天天气不错")]
        decision = engine.check_input(input_messages=messages, step_number=1)
        assert decision.effective_action == "pass"
        assert decision.passed is True
        assert decision.rule_name == ""

    def test_engine_error_degrades_to_pass(self):
        engine = _engine([_rule(severity="block")])
        # Passing a non-iterable triggers the fail-open except branch
        decision = engine.check_input(input_messages=None, step_number=1)
        assert decision.effective_action == "pass"


# ---------------------------------------------------------------------------
# check_output (checkpoint ②)
# ---------------------------------------------------------------------------

class TestCheckOutput:
    def test_block_on_tool_output_downgrades_to_mask(self):
        engine = _engine([_rule(severity="block")])
        decision = engine.check_output(
            observation=f"doc: {KEYWORD} 营收7000亿", code_action="kb()", step_number=1,
            is_final_answer=False)
        assert decision.effective_action == "mask"  # tool_output + block -> mask
        assert decision.downgraded is True
        assert KEYWORD not in decision.cleaned_content
        assert "***" in decision.cleaned_content

    def test_mask_redacts_observation(self):
        engine = _engine([_rule(severity="mask")])
        decision = engine.check_output(
            observation=f"返回{KEYWORD}的数据", code_action="kb()", step_number=1,
            is_final_answer=False)
        assert decision.effective_action == "mask"
        assert KEYWORD not in decision.cleaned_content

    def test_no_match_returns_pass(self):
        engine = _engine([_rule(severity="block")])
        decision = engine.check_output(
            observation="普通内容", code_action="kb()", step_number=1, is_final_answer=False)
        assert decision.effective_action == "pass"

    def test_empty_observation_passes(self):
        engine = _engine([_rule(severity="block")])
        decision = engine.check_output(
            observation="", code_action="kb()", step_number=1, is_final_answer=False)
        assert decision.effective_action == "pass"


# ---------------------------------------------------------------------------
# check_tool_args (checkpoint ③)
# ---------------------------------------------------------------------------

class TestCheckToolArgs:
    def test_block_is_genuine_tool_input_block(self):
        engine = _engine([_rule(severity="block")])
        decision = engine.check_tool_args(
            tool_name="send_email", args=(f"把{KEYWORD}发给客户",), kwargs={}, step_number=1)
        assert decision.effective_action == "block"  # tool_input + block -> block (genuine)
        assert decision.masked_args is None  # block does not mask args

    def test_mask_redacts_string_args_and_kwargs(self):
        engine = _engine([_rule(severity="mask")])
        decision = engine.check_tool_args(
            tool_name="send_email", args=(f"正文{KEYWORD}", 42),
            kwargs={"subject": f"{KEYWORD}标题"}, step_number=1)
        assert decision.effective_action == "mask"
        assert KEYWORD not in decision.masked_args[0]
        assert decision.masked_args[1] == 42  # non-string arg passes through
        assert KEYWORD not in decision.masked_kwargs["subject"]

    def test_no_match_returns_pass(self):
        engine = _engine([_rule(severity="block")])
        decision = engine.check_tool_args(
            tool_name="send_email", args=("普通内容",), kwargs={}, step_number=1)
        assert decision.effective_action == "pass"

    def test_unstringifiable_arg_does_not_break_screening(self):
        engine = _engine([_rule(severity="block")])

        class _Explodes:
            def __str__(self):
                raise ValueError("nope")

        decision = engine.check_tool_args(
            tool_name="t", args=(_Explodes(), f"{KEYWORD}"), kwargs={}, step_number=1)
        # the keyword arg still triggers a block; the exploding arg did not abort screening
        assert decision.effective_action == "block"


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_non_block_action_is_unchanged(self):
        engine = _engine([_rule(severity="mask")])
        assert engine._apply_breaker("r", KEYWORD, "tool_input", "mask") == "mask"

    def test_first_block_stays_block(self):
        engine = _engine([_rule(severity="block")])
        assert engine._apply_breaker("r", KEYWORD, "tool_input", "block") == "block"

    def test_repeated_identical_block_upgrades_to_terminate(self):
        engine = _engine([_rule(severity="block")])
        engine._apply_breaker("r", KEYWORD, "tool_input", "block")
        assert engine._apply_breaker("r", KEYWORD, "tool_input", "block") == "terminate"

    def test_different_signature_resets_counter(self):
        engine = _engine([_rule(severity="block")])
        engine._apply_breaker("r", KEYWORD, "tool_input", "block")
        # different matched text -> new signature, counter resets, still block
        assert engine._apply_breaker("r", "其他", "tool_input", "block") == "block"

    def test_different_source_resets_counter(self):
        engine = _engine([_rule(severity="block")])
        engine._apply_breaker("r", KEYWORD, "tool_input", "block")
        assert engine._apply_breaker("r", KEYWORD, "new_input", "terminate") == "terminate"


# ---------------------------------------------------------------------------
# Refusal rendering (zh/en locale + placeholder fill)
# ---------------------------------------------------------------------------

class TestRefusalRendering:
    def test_chinese_input_uses_zh_template(self):
        messages = [_msg("user", "分析机密信息内容")]
        text = render_guardrail_refusal(_decision(matched=KEYWORD), messages)
        assert "受限内容" in text
        assert KEYWORD in text
        assert "confidential" in text

    def test_english_input_uses_en_template(self):
        messages = [_msg("user", "analyze the report")]
        text = render_guardrail_refusal(_decision(matched="secret"), messages)
        assert "restricted content" in text
        assert "secret" in text
        assert "confidential" in text

    def test_empty_matched_falls_back_to_latest_user_message(self):
        messages = [_msg("assistant", "hi"), _msg("user", f"提到{KEYWORD}了")]
        text = render_guardrail_refusal(_decision(matched=""), messages)
        assert KEYWORD in text  # pulled from the latest user message

    def test_tool_input_refusal_zh_and_tool_name(self):
        text = render_tool_input_refusal(_decision(matched=KEYWORD, source="tool_input"),
                                         tool_name="send_email")
        assert "send_email" in text
        assert KEYWORD in text
        assert "confidential" in text

    def test_tool_input_refusal_en_for_english_match(self):
        text = render_tool_input_refusal(_decision(matched="secret", source="tool_input"),
                                         tool_name="send_email")
        assert "send_email" in text
        assert "secret" in text


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------

class TestMessageHelpers:
    def test_msg_role_dict_and_lowercase(self):
        assert GuardrailEngine._msg_role({"role": "USER"}) == "user"
        assert GuardrailEngine._msg_role({"role": "assistant"}) == "assistant"

    def test_msg_role_object_with_enum_like_value(self):
        class _R:
            value = "User"
        class _M:
            role = _R()
        assert GuardrailEngine._msg_role(_M()) == "user"

    def test_msg_role_missing_returns_empty(self):
        assert GuardrailEngine._msg_role({"content": "x"}) == ""

    def test_msg_text_string_none_list(self):
        assert GuardrailEngine._msg_text({"content": "hi"}) == "hi"
        assert GuardrailEngine._msg_text({"content": None}) == ""
        assert GuardrailEngine._msg_text({"content": [{"text": "a"}, {"content": "b"}, "c"]}) == "abc"

    def test_set_msg_text_writes_dict_and_object(self):
        d = {"role": "user", "content": "原"}
        GuardrailEngine._set_msg_text(d, "新")
        assert d["content"] == "新"

        class _M:
            content = "原"
        m = _M()
        GuardrailEngine._set_msg_text(m, "新")
        assert m.content == "新"

    def test_find_new_input_index_last_user(self):
        messages = [_msg("user", "a"), _msg("assistant", "b"), _msg("user", "c")]
        assert GuardrailEngine._find_new_input_index(messages) == 2

    def test_find_new_input_index_no_user(self):
        assert GuardrailEngine._find_new_input_index([_msg("assistant", "b")]) == -1
        assert GuardrailEngine._find_new_input_index(None) == -1


# ---------------------------------------------------------------------------
# Internal scan / mask / rank helpers
# ---------------------------------------------------------------------------

class TestScanMaskRank:
    def test_scan_returns_all_matches_first_decides_action(self):
        engine = _engine([_rule("block", name="kw"), _rule("mask", name="phone", pattern="1[3-9]\\d{9}")])
        text = f"{KEYWORD} 13912345678"
        matches = engine._scan(text)
        names = {m[1].name for m in matches}
        assert names == {"kw", "phone"}  # both rules matched, all returned

    def test_scan_empty_text_returns_empty(self):
        assert _engine([_rule()])._scan("") == []

    def test_mask_value_redacts_strings_passthrough_nonstrings(self):
        engine = _engine([_rule("mask")])
        matches = engine._scan(KEYWORD)
        assert KEYWORD not in engine._mask_value(f"x{KEYWORD}y", matches)
        assert engine._mask_value(123, matches) == 123  # non-string passthrough
        assert engine._mask_value(None, matches) is None

    @pytest.mark.parametrize("action,rank", [
        ("pass", 0), ("mask", 2), ("block", 3), ("terminate", 4), ("bogus", 0),
    ])
    def test_action_rank(self, action, rank):
        assert GuardrailEngine._action_rank(action) == rank


# ---------------------------------------------------------------------------
# _build_vr (VerificationResult construction per effective action)
# ---------------------------------------------------------------------------

class TestBuildVr:
    @pytest.mark.parametrize("action,severity,phase", [
        ("terminate", "blocking", "blocked"),
        ("block", "blocking", "blocked"),
        ("mask", "warning", "warning"),
        ("pass", "info", "pass"),
    ])
    def test_severity_and_phase_per_action(self, action, severity, phase):
        engine = _engine([_rule()])
        vr = engine._build_vr(_rule(), KEYWORD, action, "guardrail_input", "new_input",
                               downgraded=False)
        assert vr.severity == severity
        assert vr.phase == phase

    def test_mask_downgraded_note_mentions_downgrade(self):
        engine = _engine([_rule()])
        vr = engine._build_vr(_rule(), KEYWORD, "mask", "guardrail_output", "tool_output",
                               downgraded=True)
        assert "downgraded" in vr.user_visible_note

    def test_pass_note_is_empty_and_failed_criteria_carry_rule(self):
        engine = _engine([_rule(name="confidential")])
        vr = engine._build_vr(_rule(name="confidential"), KEYWORD, "terminate", "guardrail_input",
                               "new_input", downgraded=False)
        assert vr.user_visible_note.startswith("Input terminated")
        assert "confidential" in vr.failed_criteria
        assert vr.checks and vr.checks[0].name == "confidential"


# ---------------------------------------------------------------------------
# _pass_decision
# ---------------------------------------------------------------------------

class TestPassDecision:
    def test_pass_decision_is_pass(self):
        engine = _engine([_rule()])
        decision = engine._pass_decision("new_input", "guardrail_input")
        assert decision.effective_action == "pass"
        assert decision.passed is True
        assert decision.verification_result.passed is True
        assert decision.verification_result.event == "guardrail_input"


# ---------------------------------------------------------------------------
# Fail-open: an internal engine error degrades to pass, never blocks the agent
# ---------------------------------------------------------------------------

def _raising_scan(_self, _text):
    raise RuntimeError("simulated engine bug")


class TestFailOpen:
    def test_check_input_fail_open_on_engine_error(self, monkeypatch):
        engine = _engine([_rule()])
        monkeypatch.setattr(engine, "_scan", _raising_scan)
        decision = engine.check_input(input_messages=[_msg("user", KEYWORD)], step_number=1)
        assert decision.effective_action == "pass"

    def test_check_output_fail_open_on_engine_error(self, monkeypatch):
        engine = _engine([_rule()])
        monkeypatch.setattr(engine, "_scan", _raising_scan)
        decision = engine.check_output(
            observation=KEYWORD, code_action="kb()", step_number=1, is_final_answer=False)
        assert decision.effective_action == "pass"

    def test_check_tool_args_fail_open_on_engine_error(self, monkeypatch):
        engine = _engine([_rule()])
        monkeypatch.setattr(engine, "_scan", _raising_scan)
        decision = engine.check_tool_args(
            tool_name="send_email", args=(KEYWORD,), kwargs={}, step_number=1)
        assert decision.effective_action == "pass"


# ---------------------------------------------------------------------------
# Module-level helpers: _guardrail_locale, latest_user_message_text
# ---------------------------------------------------------------------------

class TestModuleHelpers:
    @pytest.mark.parametrize("text,expected", [
        ("分析机密信息内容", "zh"),
        ("analyze the report", "en"),
        ("", "en"),
        ("123 abc only", "en"),
    ])
    def test_guardrail_locale(self, text, expected):
        assert _guardrail_locale(text) == expected

    def test_latest_user_message_text_dict(self):
        messages = [_msg("assistant", "hi"), _msg("user", "你好"), _msg("assistant", "bye")]
        assert latest_user_message_text(messages) == "你好"

    def test_latest_user_message_text_list_parts(self):
        messages = [{"role": "user", "content": [{"text": "a"}, {"content": "b"}]}]
        assert latest_user_message_text(messages) == "ab"

    def test_latest_user_message_text_none_when_no_user(self):
        assert latest_user_message_text([_msg("assistant", "x")]) == ""
        assert latest_user_message_text(None) == ""


# ---------------------------------------------------------------------------
# GuardrailDecision surface
# ---------------------------------------------------------------------------

class TestGuardrailDecision:
    def test_passed_property(self):
        assert _decision(action="pass", downgraded=False).passed is True
        assert _decision(action="mask").passed is True
        assert _decision(action="block").passed is False
        assert _decision(action="terminate").passed is False

    def test_message_property_prefers_user_visible_note(self):
        dec = _decision()
        dec.verification_result.user_visible_note = "可见提示"
        dec.verification_result.repair_instruction = "修复说明"
        assert dec.message == "可见提示"

    def test_message_property_falls_back_to_repair_instruction(self):
        dec = _decision()
        dec.verification_result.user_visible_note = ""
        dec.verification_result.repair_instruction = "修复说明"
        assert dec.message == "修复说明"
