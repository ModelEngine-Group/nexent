from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from smolagents.models import ChatMessage, MessageRole
from smolagents.utils import truncate_content

from ...monitor import get_monitoring_manager
from ..utils.observer import MessageObserver, ProcessType
from .agent_model import AgentVerificationConfig


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


class VerificationController:
    """Layered verification for critical ReAct events and final answers."""

    _ERROR_RE = re.compile(
        r"(traceback|exception|error:|failed|timeout|unauthorized|permission denied)",
        re.IGNORECASE,
    )
    _SKILL_DOC_READ_RE = re.compile(r"\bread_skill_md\s*\(", re.IGNORECASE)
    _SKILL_READ_FAILURE_RE = re.compile(
        r"(^|\n)\s*(?:"
        r"\[?(?:error|warning|skillnotfounderror|filenotfounderror|timeouterror|unexpectederror)\]?|"
        r"skill not found:|skill directory not found:|skill\.md not found|file not found:|"
        r"error reading skill:|failed to read"
        r")",
        re.IGNORECASE,
    )
    _SUMMARY_STEP_RE = re.compile(r"Step\s+\S+:\n(?P<body>.*?)(?=\n\nStep\s+\S+:\n|\Z)", re.DOTALL)
    _SUMMARY_CODE_RE = re.compile(r"Code:\s*(?P<code>.*?)(?=\nObservation:|\Z)", re.DOTALL)
    _SUMMARY_OBSERVATION_RE = re.compile(r"Observation:\s*(?P<observation>.*?)(?=\nOutput:|\Z)", re.DOTALL)
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
            if result.severity == "warning" and result.failed_criteria:
                note = result.user_visible_note or result.repair_instruction
                if note:
                    suffix = "" if "不阻断" in note or "放行" in note else "；不阻断输出"
                    return f"{prefix}（有提示）：{note}{suffix}"
                labels = self._failed_check_labels(result.failed_criteria)
                if labels:
                    return f"{prefix}（有提示）：{'、'.join(labels[:3])}不阻断输出"
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
                if result.passed and result.severity == "warning" and "不阻断" not in note:
                    note = f"{note}；不阻断继续执行"
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

    def _failed_check_labels(self, failed_criteria: List[str]) -> List[str]:
        label_map = {
            "no_unresolved_raw_tags": "存在内部格式标记",
            "no_unresolved_placeholders": "存在未替换占位符",
            "previous_errors_acknowledged": "存在未说明的工具错误",
            "citation_integrity": "引用格式需关注",
            "format_safety": "格式需关注",
            "llm_verifier_confidence": "自检模型置信度偏低",
            "llm_verifier": "自检模型结果不稳定",
        }
        return [label_map.get(name, name) for name in failed_criteria]

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
            blocking_names={"non_empty_code", "python_syntax"},
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
        tool_error_signal = self._has_tool_error_signal(code_action, observation_text)
        checks = [
            VerificationCheck(
                name="observation_present",
                passed=not self._EMPTY_RE.match(observation_text),
                reason="" if observation_text.strip() else "The action produced no visible observation.",
                fix_hint="Retry with better parameters, inspect tool errors, or explain that evidence is unavailable.",
            ),
            VerificationCheck(
                name="tool_error_handled",
                passed=not tool_error_signal,
                reason="The observation contains an error signal." if tool_error_signal else "",
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
            blocking_names={"final_answer_non_empty"},
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

        policy = self._build_final_verification_policy(task, memory_summary)
        if policy["task_profile"] == "lightweight_conversation":
            deterministic.phase = "final_pass"
            deterministic.user_visible_note = "Lightweight conversational task; deterministic checks passed."
            self.emit(deterministic, round_number)
            return deterministic

        if not self._should_run_llm_verifier(policy):
            deterministic.phase = "final_pass"
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
        blocking_failed_criteria = self._blocking_llm_failed_criteria(effective_failed_criteria, policy)
        has_blocking_failure = bool(blocking_failed_criteria)
        effective_passed = not has_blocking_failure
        warning_criteria = effective_failed_criteria.copy()
        if not warning_criteria and not has_blocking_failure and (not passed or not threshold_passed):
            warning_criteria = ["llm_verifier_confidence"]
        severity = "blocking" if has_blocking_failure else ("warning" if warning_criteria else "info")
        visible_note = str(data.get("user_visible_note") or "")
        if warning_criteria and not visible_note:
            visible_note = "自检发现非阻断提示，已放行最终答案。"
        return VerificationResult(
            passed=effective_passed,
            severity=severity,
            event="final_answer",
            phase="final_pass" if effective_passed else "final_fail",
            score=score,
            failed_criteria=blocking_failed_criteria if has_blocking_failure else warning_criteria,
            repair_instruction=str(data.get("revision_instruction") or data.get("repair_instruction") or ""),
            user_visible_note=visible_note,
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
        should_block = bool(blocking_failed)
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

    def _should_run_llm_verifier(self, policy: Dict[str, Any]) -> bool:
        if not self.config.llm_verification_enabled:
            return False
        if policy.get("task_profile") == "lightweight_conversation":
            return False
        return self.config.strictness == "strict"

    def _blocking_llm_failed_criteria(self, failed_criteria: List[str], policy: Dict[str, Any]) -> List[str]:
        if self.config.fail_policy == "warn" or self.config.strictness != "strict":
            return []

        blocking_criteria = {"intent_coverage"}
        if policy.get("evidence_required", True):
            blocking_criteria.add("evidence_grounding")
        if policy.get("tool_error_check_required", True):
            blocking_criteria.add("tool_error_handling")
        return [criterion for criterion in failed_criteria if criterion in blocking_criteria]

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
        step_signals = list(self._iter_summary_step_signals(clean_text))
        if step_signals:
            return any(
                self._has_tool_error_signal(code_action, observation)
                for code_action, observation in step_signals
            )
        clean_text = self._strip_successful_skill_doc_observations(clean_text)
        return bool(self._ERROR_RE.search(clean_text))

    def _iter_summary_step_signals(self, text: str):
        for match in self._SUMMARY_STEP_RE.finditer(text or ""):
            body = match.group("body") or ""
            code_match = self._SUMMARY_CODE_RE.search(body)
            observation_match = self._SUMMARY_OBSERVATION_RE.search(body)
            code_action = code_match.group("code").strip() if code_match else ""
            observation = observation_match.group("observation").strip() if observation_match else ""
            if code_action or observation:
                yield code_action, observation

    def _has_tool_error_signal(self, code_action: str, observation: str) -> bool:
        observation_text = observation or ""
        if self._is_skill_doc_read_action(code_action):
            return self._looks_like_skill_read_failure(observation_text)
        return bool(self._ERROR_RE.search(observation_text))

    def _is_skill_doc_read_action(self, code_action: str) -> bool:
        return bool(self._SKILL_DOC_READ_RE.search(code_action or ""))

    def _looks_like_skill_read_failure(self, observation: str) -> bool:
        return bool(self._SKILL_READ_FAILURE_RE.search(observation or ""))

    def _strip_successful_skill_doc_observations(self, text: str) -> str:
        if "read_skill_md" not in (text or ""):
            return text

        blocks = re.split(r"(?=Step \d+:\n)", text)
        sanitized_blocks: List[str] = []
        for block in blocks:
            if not self._is_skill_doc_read_action(block):
                sanitized_blocks.append(block)
                continue

            marker = "Observation:"
            marker_index = block.find(marker)
            if marker_index == -1:
                sanitized_blocks.append(block)
                continue

            observation_start = marker_index + len(marker)
            output_index = block.find("\nOutput:", observation_start)
            observation_end = output_index if output_index != -1 else len(block)
            observation = block[observation_start:observation_end]
            if self._looks_like_skill_read_failure(observation):
                sanitized_blocks.append(block)
                continue

            replacement = " [skill documentation omitted for error-signal detection]"
            sanitized_blocks.append(
                block[:observation_start] + replacement + block[observation_end:]
            )
        return "".join(sanitized_blocks)

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
