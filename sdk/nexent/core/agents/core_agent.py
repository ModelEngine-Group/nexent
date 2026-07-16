import json
import ast
import time
import threading
from datetime import datetime
from textwrap import dedent
from typing import Any, Optional, List, Dict
from collections.abc import Generator

from rich.console import Group
from rich.text import Text

from smolagents.agents import CodeAgent, handle_agent_output_types, AgentError, ActionOutput, RunResult
from smolagents.local_python_executor import fix_final_answer_code
from smolagents.memory import ActionStep, PlanningStep, FinalAnswerStep, ToolCall, TaskStep, SystemPromptStep
from smolagents.models import ChatMessage, CODEAGENT_RESPONSE_FORMAT
from smolagents.monitoring import LogLevel, Timing, YELLOW_HEX, TokenUsage
from smolagents.utils import AgentExecutionError, AgentGenerationError, truncate_content, AgentMaxStepsError, \
    extract_code_from_text

from ...monitor import get_monitoring_manager

from ..utils.observer import MessageObserver, ProcessType
from jinja2 import Template, StrictUndefined

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import PIL.Image

from .agent_model import AgentVerificationConfig
from ..context_runtime.contracts import ContextRuntime, UnconfiguredContextRuntime
from .verification import (
    VerificationController,
    VerificationResult,
    render_guardrail_refusal,
    render_tool_input_refusal,
)
from ..utils.token_estimation import msg_token_count

def parse_code_blobs(text: str) -> str:
    """Extract code blocks from the LLM's output for execution.

    This function handles only two formats:
    - <code>...</code>: primary execution format
    - ```<RUN>...</RUN>```: legacy format for backward compatibility

    Note: ```python / ```py blocks are intentionally NOT extracted here to prevent
    KB content containing code examples from being accidentally executed.

    Args:
        text (`str`): LLM's output text to parse.

    Returns:
        `str`: Extracted code block for execution.

    Raises:
        ValueError: If no valid code block is found in the text.
    """
    # First try to match the new <code>...</code> format for execution
    # Use string find/slice operations instead of regex to prevent backtracking issues
    code_matches = []
    search_pos = 0
    while True:
        start = text.find("<code>", search_pos)
        if start == -1:
            break
        # Move past the opening tag
        content_start = start + len("<code>")
        end = text.find("</code>", content_start)
        if end == -1:
            # No closing tag found, stop searching
            break
        # Extract the content between tags
        code_matches.append(text[content_start:end])
        search_pos = end + len("</code>")

    if code_matches:
        return "\n\n".join(match.strip() for match in code_matches)

    # Fallback to legacy <RUN> format for backward compatibility
    # Use string operations instead of regex to prevent backtracking
    run_matches = []
    search_pos = 0
    run_tag = "```<RUN>"
    while True:
        start = text.find(run_tag, search_pos)
        if start == -1:
            break
        # Move past the opening tag (including newline)
        content_start = start + len(run_tag)
        # Find the closing ```
        end = text.find("```", content_start)
        if end == -1:
            break
        run_matches.append(text[content_start:end])
        search_pos = end + len("```")

    if run_matches:
        return "\n\n".join(match.strip() for match in run_matches)

    raise ValueError(
        dedent(
            f"""
            Your code snippet is invalid, because no valid executable code block pattern was found in it.
            Here is your code snippet:
            {text}
            Make sure to include code with the correct pattern for execution:
            Thoughts: Your thoughts
            Code:
            <code>
            # Your python code here (for execution)
            </code>
            """
        ).strip()
    )


def convert_code_format(text):
    """
    Convert code blocks to markdown format for display.

    This function is used to convert code blocks in final answers to markdown format,
    so it handles <DISPLAY:language>...</DISPLAY> format and legacy formats.
    """
    # Use string operations instead of regex to prevent backtracking issues
    backtick = chr(96)
    triple_backtick = backtick * 3

    # Step 1: Handle legacy format ```<DISPLAY:language> -> ```language
    # Handle all variants: `, ``, ``` followed by <DISPLAY:language>
    for n_backticks in [1, 2, 3]:
        b = backtick * n_backticks
        prefix = b + "<DISPLAY:"
        while True:
            idx = text.find(prefix)
            if idx == -1:
                break
            lang_start = idx + len(prefix)
            lang_end = text.find(">", lang_start)
            if lang_end == -1:
                break
            lang = text[lang_start:lang_end]
            text = text[:idx] + b + lang + text[lang_end + 1:]

    # Step 2: Handle legacy format ```code:language -> ```language
    for n_backticks in [1, 2, 3]:
        b = backtick * n_backticks
        prefix = b + "code:"
        while True:
            idx = text.find(prefix)
            if idx == -1:
                break
            lang_start = idx + len(prefix)
            lang_end = lang_start
            while lang_end < len(text) and (text[lang_end].isalnum() or text[lang_end] == "_"):
                lang_end += 1
            if lang_end == lang_start:
                break
            lang = text[lang_start:lang_end]
            text = text[:idx] + b + lang + text[lang_end:]

    # Step 3: Handle new format <DISPLAY:language>...</DISPLAY> -> ```language...```
    # Replace opening tags first
    while True:
        idx = text.find("<DISPLAY:")
        if idx == -1:
            break
        lang_start = idx + len("<DISPLAY:")
        lang_end = text.find(">", lang_start)
        if lang_end == -1:
            break
        lang = text[lang_start:lang_end]
        text = text[:idx] + triple_backtick + lang + text[lang_end + 1:]

    # Step 4: Replace closing tags
    text = text.replace("</DISPLAY>", triple_backtick)

    # Step 5: Handle closing tags - restore closing backticks from legacy END markers
    text = text.replace(triple_backtick + "<END_DISPLAY_CODE>", triple_backtick)
    text = text.replace(triple_backtick + "<END_CODE>", triple_backtick)

    return text


class FinalAnswerError(Exception):
    """Raised when agent output directly."""
    pass


class ToolInputBlockedError(AgentExecutionError):
    """Raised by the guardrail tool-input wrap when a call is blocked.

    Carries a ``refusal`` string for ``_step_stream`` to end the run without a retry loop.

    Args:
        refusal: User-facing refusal text used as the run's final answer.
        logger: Optional logger forwarded to the base exception.
    """

    def __init__(self, refusal: str, logger=None):
        super().__init__(refusal, logger)
        self.refusal = refusal


def _screened_tool_forward(engine, tool_name, controller, logger, original_forward, *args, **kwargs):
    """Screen tool call args then dispatch to the original ``forward`` (checkpoint ③).

    Args:
        engine: GuardrailEngine that screens the resolved call args.
        tool_name: Name of the wrapped tool.
        controller: VerificationController used to emit + stash the refusal.
        logger: Logger forwarded to ``ToolInputBlockedError``.
        original_forward: The tool's real ``forward`` callable.
        *args: Positional args of the tool call.
        **kwargs: Keyword args of the tool call.

    Returns:
        Whatever ``original_forward`` returns (masked args are substituted on
        ``mask``); raises ``ToolInputBlockedError`` on ``block``/``terminate``.
    """
    decision = engine.check_tool_args(tool_name=tool_name, args=args, kwargs=kwargs)
    action = decision.effective_action
    if action != "pass":
        controller.emit(decision.verification_result, message=decision.message)
    if action in ("block", "terminate"):
        # Stash the refusal; _step_stream raises FinalAnswerError from it (no retry loop).
        refusal = render_tool_input_refusal(decision, tool_name)
        controller.pending_tool_block_refusal = refusal
        raise ToolInputBlockedError(refusal, logger)
    if action == "mask":
        if decision.masked_args is not None:
            args = decision.masked_args
        if decision.masked_kwargs is not None:
            kwargs = decision.masked_kwargs
    return original_forward(*args, **kwargs)


class CoreAgent(CodeAgent):
    def __init__(
        self,
        observer: MessageObserver,
        prompt_templates: Dict[str, Any] | None = None,
        verification_config: AgentVerificationConfig | None = None,
        *args,
        **kwargs
    ):
        context_runtime = kwargs.pop("context_runtime", None)
        super().__init__(prompt_templates=prompt_templates, *args, **kwargs)
        self.observer = observer
        self.verification_config = verification_config or AgentVerificationConfig(enabled=False)
        self.verification_controller = VerificationController(
            config=self.verification_config,
            observer=observer,
            agent_name=self.agent_name,
            model=self.model,
            logger=self.logger,
        )
        self.stop_event = threading.Event()
        self._history_step_count = 0  # For ContextManager, record boundary for compression
        # The factory injects exactly one independent runtime.  CoreAgent has
        # no legacy/managed fallback branch and cannot assemble context itself.
        self.context_runtime: ContextRuntime = context_runtime or UnconfiguredContextRuntime()
        self.context_manager: Any = getattr(
            self.context_runtime, "context_manager", None
        )
        self.step_metrics: List[dict] = []  # Quantitative metrics per step
        self._last_uncompressed_est = 0
        # Override smolagent default to prevent extracting ```python blocks from KB content.
        # code_block_tags[0] and [1] are used by the system prompt template for opening/closing
        # tags (e.g., ``` and ```). extract_code_from_text iterates all tags as language
        # identifiers; omitting "python" and "py" ensures ```python blocks are not extracted.
        self.code_block_tags = ["", ""]

    def _verification_tool_names(self) -> List[str]:
        names = set()
        for container in (getattr(self, "tools", {}) or {}, getattr(self, "managed_agents", {}) or {}):
            try:
                names.update(str(name) for name in container.keys())
            except AttributeError:
                continue
        names.add("final_answer")
        return sorted(names)

    def _context_tools(self) -> List[Any]:
        """Return a stable tool list for ContextRuntime/ContextManager evidence.

        Tool execution still uses smolagents' native tool registry.  This list is
        the context-module view used for W3 ordering, budgeting, and evidence.
        """
        tools: List[Any] = []
        for container in (getattr(self, "tools", {}) or {}, getattr(self, "managed_agents", {}) or {}):
            try:
                iterable = container.values()
            except AttributeError:
                iterable = container
            tools.extend(list(iterable or ()))
        return tools

    def _guardrail_wrap_tools(self) -> None:
        """Wrap each tool's forward() to screen resolved args before execution (checkpoint ③).

        Blocked content never reaches the tool (vs checkpoint ②, which screens
        output after the fact). Idempotent: already-wrapped tools are skipped.
        Covers self.tools and self.managed_agents (incl. MCP).
        """
        engine = getattr(getattr(self, "verification_controller", None), "guardrail_engine", None)
        if not engine:
            return
        for container in (getattr(self, "tools", {}) or {}, getattr(self, "managed_agents", {}) or {}):
            try:
                iterable = container.values()
            except AttributeError:
                iterable = container
            for tool in list(iterable or ()):
                self._guardrail_wrap_one(tool, engine)

    def _guardrail_wrap_one(self, tool, engine) -> None:
        """Wrap a single tool's forward() with guardrail arg screening.

        A blocked call raises ``AgentExecutionError`` so the tool never runs; a
        passing call adds no observer traffic. Idempotent via ``_guardrail_wrapped``.

        Args:
            tool: Tool whose ``forward()`` is wrapped.
            engine: GuardrailEngine that screens the resolved call args.
        """
        if tool is None or getattr(tool, "_guardrail_wrapped", False):
            return
        original_forward = getattr(tool, "forward", None)
        if not callable(original_forward):
            return
        tool_name = getattr(tool, "name", "") or ""
        controller = self.verification_controller
        logger = self.logger
        tool.forward = lambda *args, **kwargs: _screened_tool_forward(
            engine, tool_name, controller, logger, original_forward, *args, **kwargs
        )
        try:
            tool._guardrail_wrapped = True
        except Exception:
            # Some tool proxies block attribute writes; the wrap still took effect (worst case: harmless double-wrap).
            pass

    def _append_verification_feedback(self, action_step: ActionStep, result: VerificationResult) -> None:
        feedback = self.verification_controller.build_feedback_observation(result)
        if action_step.observations:
            action_step.observations += feedback
        else:
            action_step.observations = feedback

    def _build_verification_memory_summary(
        self,
        current_step: ActionStep | None = None,
        max_chars: int = 8000,
    ) -> str:
        summaries = []
        steps = list(self.memory.steps[-8:])
        if current_step is not None:
            steps.append(current_step)
        for step in steps:
            if isinstance(step, TaskStep):
                summaries.append(f"Task: {truncate_content(str(step.task), max_length=1200)}")
            elif isinstance(step, ActionStep):
                code = truncate_content(str(getattr(step, "code_action", "") or ""), max_length=1200)
                observations = truncate_content(str(getattr(step, "observations", "") or ""), max_length=1800)
                output = truncate_content(str(getattr(step, "action_output", "") or ""), max_length=1200)
                summaries.append(
                    f"Step {getattr(step, 'step_number', '?')}:\n"
                    f"Code: {code}\n"
                    f"Observation: {observations}\n"
                    f"Output: {output}"
                )
        return truncate_content("\n\n".join(summaries), max_length=max_chars)

    def _finalize_failed_verification_candidate(
        self,
        action_step: ActionStep,
        verification_result: VerificationResult,
        verification_round: int,
        max_rounds: int,
        candidate_answer: Any,
    ) -> tuple[bool, Any]:
        if verification_round < max_rounds:
            verification_result.phase = "repair"
            self.verification_controller.emit(
                verification_result,
                verification_round,
            )
            self._append_verification_feedback(action_step, verification_result)
            action_step.is_final_answer = False
            return False, None

        verification_result.phase = "final_fail"
        self.verification_controller.emit(
            verification_result,
            verification_round,
        )
        controlled_answer = self.verification_controller.build_controlled_failure_answer(
            candidate_answer,
            verification_result,
        )
        action_step.is_final_answer = True
        action_step.action_output = controlled_answer
        return True, controlled_answer

    def _log_model_call_parameters(self, input_messages: List[ChatMessage], stop_sequences: List[str], additional_args: Dict[str, Any]) -> None:
        """
        Log model call parameters with content truncation for readability.


        Args:
            input_messages: List of chat messages being sent to the model
            stop_sequences: Stop sequences for the model
            additional_args: Additional arguments passed to the model
        """
        try:
            # Convert messages to serializable format and truncate
            messages_data = []
            for msg in input_messages:
                msg_dict = msg.model_dump() if hasattr(msg, 'model_dump') else (
                    msg.__dict__ if hasattr(msg, '__dict__') else str(msg)
                )
                messages_data.append(msg_dict)

            # Format as JSON with truncation for readability
            messages_json = json.dumps(messages_data, indent=2, ensure_ascii=False, default=str)
            truncated_messages = truncate_content(messages_json, max_length=1000)
            truncated_messages = messages_json

            # Format stop sequences
            stop_seq_str = ", ".join(f'"{seq}"' for seq in stop_sequences) if stop_sequences else "None"

            # Format additional args (excluding sensitive data)
            safe_args = {}
            for key, value in additional_args.items():
                if key.lower() in ['api_key', 'token', 'password', 'secret']:
                    safe_args[key] = "***REDACTED***"
                else:
                    safe_args[key] = value

            args_str = json.dumps(safe_args, indent=2, ensure_ascii=False) if safe_args else "None"

            # Create log content
            log_content = f"""Input Messages ({len(input_messages)} total):
{truncated_messages}

Stop Sequences: [{stop_seq_str}]
Additional Args:
{args_str}"""

            self.logger.log_markdown(
                content=log_content,
                title="MODEL INPUT PARAMETERS",
                level=LogLevel.INFO
            )

        except Exception as e:
            # Don't let logging errors break the model call
            self.logger.log(f"Failed to log model call parameters: {e}", level=LogLevel.INFO)

    def _step_stream(self, memory_step: ActionStep) -> Generator[Any]:
        """
        Perform one step in the ReAct framework: the agent thinks, acts, and observes the result.
        Returns None if the step is not final.
        """
        self.observer.add_message(
            self.agent_name, ProcessType.STEP_COUNT, self.step_number)

        final_context = self.context_runtime.prepare_step(
            model=self.model,
            memory=self.memory,
            current_run_start_idx=self._history_step_count,
            tools=self._context_tools(),
        )
        input_messages = final_context.messages
        chars_per_token = self.context_runtime.chars_per_token
        self._last_uncompressed_est = msg_token_count(input_messages, chars_per_token)
        # Add new step in logs
        memory_step.model_input_messages = input_messages
        stop_sequences = ["Observation:", "Calling tools:"]

        # Prepare additional arguments
        additional_args: dict[str, Any] = {}
        if self._use_structured_outputs_internally:
            additional_args["response_format"] = CODEAGENT_RESPONSE_FORMAT

        # Log model call parameters before execution
        self._log_model_call_parameters(input_messages, stop_sequences, additional_args)

        # Guardrail checkpoint ①: screen LLM input per-message; terminate -> end run, mask -> redact, pass -> continue.
        guardrail_engine = getattr(getattr(self, "verification_controller", None), "guardrail_engine", None)
        if guardrail_engine:
            decision = guardrail_engine.check_input(
                input_messages=input_messages,
                step_number=memory_step.step_number,
            )
            self.verification_controller.emit(
                decision.verification_result, message=decision.message
            )
            if decision.effective_action == "terminate":
                self._append_verification_feedback(memory_step, decision.verification_result)
                # Pre-built refusal as the final answer; FinalAnswerError ends the run (no retry loop).
                memory_step.model_output = render_guardrail_refusal(
                    decision, input_messages
                )
                raise FinalAnswerError()
            if decision.effective_action == "mask" and decision.masked_messages is not None:
                input_messages = decision.masked_messages
                self._append_verification_feedback(memory_step, decision.verification_result)

        try:
            chat_message: ChatMessage = self.model(input_messages,
                                                   stop_sequences=stop_sequences, **additional_args)
            memory_step.model_output_message = chat_message
            model_output = chat_message.content
            memory_step.token_usage = chat_message.token_usage
            memory_step.model_output = model_output

            self.logger.log_markdown(
                content=model_output, title="MODEL OUTPUT", level=LogLevel.INFO)
        except Exception as e:
            raise AgentGenerationError(
                f"Error in generating model output:\n{e}", self.logger) from e

        self.logger.log_markdown(
            content=model_output, title="Output message of the LLM:", level=LogLevel.DEBUG)

        # Parse
        try:
            if self._use_structured_outputs_internally:
                code_action = json.loads(model_output)["code"]
                code_action = extract_code_from_text(code_action, self.code_block_tags) or code_action
            else:
                code_action = parse_code_blobs(model_output)
            code_action = fix_final_answer_code(code_action)
            memory_step.code_action = code_action
            # Record parsing results
            self.observer.add_message(
                self.agent_name, ProcessType.PARSE, code_action)
            verification_controller = getattr(self, "verification_controller", None)
            if verification_controller:
                precheck = verification_controller.verify_before_tool_call(
                    code_action=code_action,
                    step_number=memory_step.step_number,
                    available_tool_names=self._verification_tool_names(),
                )
                if not precheck.passed and precheck.severity == "blocking":
                    self._append_verification_feedback(memory_step, precheck)
                    raise AgentExecutionError(
                        precheck.repair_instruction or precheck.user_visible_note or "Action failed verification.",
                        self.logger,
                    )

        except AgentExecutionError:
            raise
        except Exception:
            self.logger.log_markdown(
                content=model_output, title="AGENT FINAL ANSWER", level=LogLevel.INFO)
            raise FinalAnswerError()

        tool_call = ToolCall(
            name="python_interpreter",
            arguments=code_action,
            id=f"call_{len(self.memory.steps)}",
        )
        memory_step.tool_calls = [tool_call]

        # Execute
        self.logger.log_code(title="Executing parsed code:",
                             content=code_action, level=LogLevel.INFO)
        exec_start = time.time()
        try:
            monitoring_manager = get_monitoring_manager()
            with monitoring_manager.trace_tool_call(
                "python_interpreter",
                self.name,
                {"code": code_action, "step_number": memory_step.step_number},
            ):
                code_output = self.python_executor(code_action)
                monitoring_manager.set_tool_output({
                    "output": getattr(code_output, "output", None),
                    "is_final_answer": getattr(code_output, "is_final_answer", False),
                    "logs": getattr(code_output, "logs", ""),
                })
            if getattr(code_output, "is_final_answer", False):
                with monitoring_manager.trace_tool_call(
                    "FinalAnswerTool",
                    self.name,
                    {"step_number": memory_step.step_number},
                ):
                    monitoring_manager.set_tool_output(code_output.output)
            execution_outputs_console = []
            if len(code_output.logs) > 0:
                # Record execution results
                self.observer.add_message(
                    self.agent_name, ProcessType.EXECUTION_LOGS, f"{code_output.logs}")

                execution_outputs_console += [
                    Text("Execution logs:", style="bold"),
                    Text(code_output.logs),
                ]
            observation = "Execution logs:\n" + code_output.logs
        except Exception as e:
            # Guardrail ③ block: end the run with the stashed refusal (no retry loop).
            # The executor re-wraps exceptions, so isinstance(e, ToolInputBlockedError) may miss.
            pending_refusal = getattr(getattr(self, "verification_controller", None), "pending_tool_block_refusal", None)
            if pending_refusal or isinstance(e, ToolInputBlockedError):
                refusal = pending_refusal or getattr(e, "refusal", "")
                self.verification_controller.pending_tool_block_refusal = None
                memory_step.model_output = refusal
                raise FinalAnswerError()
            exec_duration_ms = (time.time() - exec_start) * 1000
            if hasattr(self.python_executor, "state") and "_print_outputs" in self.python_executor.state:
                execution_logs = str(
                    self.python_executor.state["_print_outputs"])
                if len(execution_logs) > 0:
                    # Record execution results
                    self.observer.add_message(
                        self.agent_name, ProcessType.EXECUTION_LOGS, f"{execution_logs}\n")

                    execution_outputs_console = [
                        Text("Execution logs:", style="bold"), Text(execution_logs), ]
                    memory_step.observations = "Execution logs:\n" + execution_logs
                    self.logger.log(
                        Group(*execution_outputs_console), level=LogLevel.INFO)
            error_msg = str(e)
            self.logger.log(
                f"[Code Execution] step={memory_step.step_number} failed after {exec_duration_ms:.1f}ms: {error_msg}",
                level=LogLevel.ERROR,
            )
            raise AgentExecutionError(error_msg, self.logger)

        exec_duration_ms = (time.time() - exec_start) * 1000
        self.logger.log(
            f"[Code Execution] step={memory_step.step_number} completed in {exec_duration_ms:.1f}ms",
            level=LogLevel.INFO,
        )

        truncated_output = None
        if code_output is not None and code_output.output is not None:
            truncated_output = truncate_content(str(code_output.output))
            observation += "Last output from code snippet:\n" + truncated_output
        memory_step.observations = observation

        verification_controller = getattr(self, "verification_controller", None)
        if verification_controller:
            postcheck = verification_controller.verify_after_tool_call(
                code_action=code_action,
                observation=memory_step.observations,
                step_number=memory_step.step_number,
                is_final_answer=bool(code_output.is_final_answer),
            )
            if not postcheck.passed and postcheck.severity == "blocking":
                self._append_verification_feedback(memory_step, postcheck)
                raise AgentExecutionError(
                    postcheck.repair_instruction or postcheck.user_visible_note or "Action result failed verification.",
                    self.logger,
                )
            if postcheck.severity == "warning":
                self._append_verification_feedback(memory_step, postcheck)

        # Guardrail checkpoint ②: screen tool output; block downgrades to mask (tool already ran), redact before memory. Never raises, never loops.
        guardrail_engine = getattr(verification_controller, "guardrail_engine", None) if verification_controller else None
        if guardrail_engine:
            decision = guardrail_engine.check_output(
                observation=memory_step.observations,
                code_action=code_action,
                step_number=memory_step.step_number,
                is_final_answer=bool(code_output.is_final_answer),
            )
            verification_controller.emit(
                decision.verification_result, message=decision.message
            )
            if decision.effective_action == "mask" and decision.cleaned_content is not None:
                memory_step.observations = decision.cleaned_content
                self._append_verification_feedback(memory_step, decision.verification_result)

        # Pre-truncate observations when ContextManager is enabled. Keeps the
        # head + tail of long outputs around a truncation marker so downstream
        # compression sees bounded-length step records and the model can still
        # search/read for the elided portion.
        self.context_runtime.truncate_observation(memory_step)

        if not code_output.is_final_answer and truncated_output is not None:
            execution_outputs_console += [
                Text(
                    f"Out: {truncated_output}",
                ),
            ]
        self.logger.log(Group(*execution_outputs_console), level=LogLevel.INFO)
        memory_step.action_output = code_output.output
        yield ActionOutput(output=code_output.output, is_final_answer=code_output.is_final_answer)

    def run(self, task: str, stream: bool = False, reset: bool = True, images: Optional[List[str]] = None,
            additional_args: Optional[Dict] = None, max_steps: Optional[int] = None, return_full_result: bool | None = None):
        """
        Run the agent for the given task.

        Args:
            task (`str`): Task to perform.
            stream (`bool`): Whether to run in a streaming way.
            reset (`bool`): Whether to reset the conversation or keep it going from previous run.
            images (`list[str]`, *optional*): Paths to image(s).
            additional_args (`dict`, *optional*): Any other variables that you want to pass to the agent run, for instance images or dataframes. Give them clear names!
            max_steps (`int`, *optional*): Maximum number of steps the agent can take to solve the task. if not provided, will use the agent's default value.
            return_full_result (`bool`, *optional*): Whether to return the full [`RunResult`] object or just the final answer output.
                If `None` (default), the agent's `self.return_full_result` setting is used.

        Example:
        ```py
        from nexent.smolagent import CodeAgent
        agent = CodeAgent(tools=[])
        agent.run("What is the result of 2 power 3.7384?")
        ```
        """
        max_steps = max_steps or self.max_steps
        # Prepend current time to the user task instead of baking it into the
        # system prompt. This keeps the system prefix stable so prompt/KV caches
        # can hit across requests; only the trailing user message varies.
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.task = f"[Current time: {time_str}]\n\n{task}"
        if additional_args is not None:
            self.state.update(additional_args)
            self.task += f"""
You have been provided with these additional arguments, that you can access using the keys as variables in your python code:
{str(additional_args)}."""

        if reset:
            self.memory.reset()
            self.monitor.reset()
        self.context_runtime.prepare_run(
            memory=self.memory,
            fallback_system_prompt=self.system_prompt,
        )

        self.logger.log_task(content=self.task.strip(),
                             subtitle=f"{type(self.model).__name__} - {(self.model.model_id if hasattr(self.model, 'model_id') else '')}",
                             level=LogLevel.INFO, title=self.name if hasattr(self, "name") else None, )

        # Record current agent task
        self.observer.add_message(
            self.name, ProcessType.AGENT_NEW_RUN, self.task.strip())

        self.memory.steps.append(TaskStep(task=self.task, task_images=images))

        if getattr(self, "python_executor", None):
            self._guardrail_wrap_tools()
            self.python_executor.send_variables(variables=self.state)
            self.python_executor.send_tools(
                {**self.tools, **self.managed_agents})

        if stream:
            # The steps are returned as they are executed through a generator to iterate on.
            return self._run_stream(task=self.task, max_steps=max_steps, images=images)
        run_start_time = time.time()
        steps = list(self._run_stream(task=self.task, max_steps=max_steps, images=images))

        # Outputs are returned only at the end. We only look at the last step.
        assert isinstance(steps[-1], FinalAnswerStep)
        output = steps[-1].output

        return_full_result = return_full_result if return_full_result is not None else self.return_full_result
        if return_full_result:
            total_input_tokens = 0
            total_output_tokens = 0
            correct_token_usage = True
            for step in self.memory.steps:
                if isinstance(step, (ActionStep, PlanningStep)):
                    if step.token_usage is None:
                        correct_token_usage = False
                        break
                    else:
                        total_input_tokens += step.token_usage.input_tokens
                        total_output_tokens += step.token_usage.output_tokens
            if correct_token_usage:
                token_usage = TokenUsage(input_tokens=total_input_tokens, output_tokens=total_output_tokens)
            else:
                token_usage = None

            if self.memory.steps and isinstance(getattr(self.memory.steps[-1], "error", None), AgentMaxStepsError):
                state = "max_steps_error"
            else:
                state = "success"

            step_dicts = self.memory.get_full_steps()

            return RunResult(
                output=output,
                token_usage=token_usage,
                steps=step_dicts,
                timing=Timing(start_time=run_start_time, end_time=time.time()),
                state=state,
            )

        return output

    def __call__(self, task: str, **kwargs):
        """Adds additional prompting for the managed agent, runs it, and wraps the output.
        This method is called only by a managed agent.
        """
        full_task = Template(self.prompt_templates["managed_agent"]["task"], undefined=StrictUndefined).render({
            "name": self.name, "task": task, **self.state
        })
        result = self.run(full_task, **kwargs)
        if isinstance(result, RunResult):
            report = result.output
        else:
            report = result

        # When a sub-agent finishes running, return a marker
        try:
            self.observer.add_message(
                self.name, ProcessType.AGENT_FINISH, str(report))
        except Exception:
            self.observer.add_message(self.name, ProcessType.AGENT_FINISH, "")

        answer = Template(self.prompt_templates["managed_agent"]["report"], undefined=StrictUndefined).render({
            "name": self.name, "final_answer": report
        })
        if self.provide_run_summary:
            answer += "\n\nFor more detail, find below a summary of this agent's work:\n<summary_of_work>\n"
            for message in self.context_runtime.render_summary_messages(memory=self.memory):
                content = message.get("content") if isinstance(message, dict) else message.content
                answer += "\n" + truncate_content(str(content)) + "\n---"
            answer += "\n</summary_of_work>"
        return answer

    def _run_stream(
            self, task: str, max_steps: int, images: list["PIL.Image.Image"] | None = None
    ) -> Generator[ActionStep | PlanningStep | FinalAnswerStep]:
        final_answer = None
        action_step = None
        self.step_number = 1
        returned_final_answer = False
        final_verification_round = 0
        verification_config = getattr(
            self,
            "verification_config",
            AgentVerificationConfig(enabled=False),
        )
        max_final_verification_rounds = (
            verification_config.max_final_rounds
            if verification_config and verification_config.enabled
            else 1
        )
        while not returned_final_answer and self.step_number <= max_steps and not self.stop_event.is_set():
            step_start_time = time.time()

            action_step = ActionStep(
                step_number=self.step_number, timing=Timing(start_time=step_start_time), observations_images=images
            )
            try:
                for output in self._step_stream(action_step):
                    yield output

                if isinstance(output, ActionOutput) and output.is_final_answer:
                    candidate_answer = output.output
                    self.logger.log(
                        Text(f"Final answer: {candidate_answer}", style=f"bold {YELLOW_HEX}"),
                        level=LogLevel.INFO,
                    )

                    if verification_config.enabled and verification_config.final_verification_enabled:
                        final_verification_round += 1
                        verification_result = self.verification_controller.verify_final_answer(
                            task=task,
                            candidate=candidate_answer,
                            memory_summary=self._build_verification_memory_summary(action_step),
                            round_number=final_verification_round,
                        )
                        if verification_result.passed:
                            final_answer = candidate_answer
                            if self.final_answer_checks:
                                self._validate_final_answer(final_answer)
                            returned_final_answer = True
                            action_step.is_final_answer = True
                        else:
                            returned_final_answer, final_answer = self._finalize_failed_verification_candidate(
                                action_step=action_step,
                                verification_result=verification_result,
                                verification_round=final_verification_round,
                                max_rounds=max_final_verification_rounds,
                                candidate_answer=candidate_answer,
                            )
                    else:
                        final_answer = candidate_answer
                        if self.final_answer_checks:
                            self._validate_final_answer(final_answer)
                        returned_final_answer = True
                        action_step.is_final_answer = True

            except FinalAnswerError:
                # When the model does not output code, directly treat the large model content as the final answer
                candidate_answer = action_step.model_output
                if isinstance(candidate_answer, str):
                    candidate_answer = convert_code_format(candidate_answer)

                if verification_config.enabled and verification_config.final_verification_enabled:
                    final_verification_round += 1
                    verification_result = self.verification_controller.verify_final_answer(
                        task=task,
                        candidate=candidate_answer,
                        memory_summary=self._build_verification_memory_summary(action_step),
                        round_number=final_verification_round,
                    )
                    if verification_result.passed:
                        final_answer = candidate_answer
                        if self.final_answer_checks:
                            self._validate_final_answer(final_answer)
                        returned_final_answer = True
                        action_step.is_final_answer = True
                    else:
                        returned_final_answer, final_answer = self._finalize_failed_verification_candidate(
                            action_step=action_step,
                            verification_result=verification_result,
                            verification_round=final_verification_round,
                            max_rounds=max_final_verification_rounds,
                            candidate_answer=candidate_answer,
                        )
                else:
                    final_answer = candidate_answer
                    returned_final_answer = True
                    action_step.is_final_answer = True

            except AgentError as e:
                action_step.error = e

            finally:
                self._finalize_step(action_step)
                # add quantitative collection
                self._collect_step_metrics(action_step)
                self.memory.steps.append(action_step)
                yield action_step
                self.step_number += 1

        if self.stop_event.is_set():
            final_answer = "<user_break>"

        if not returned_final_answer and self.step_number == max_steps + 1:
            max_steps_data = json.dumps({
                "completedSteps": self.step_number - 1,
                "maxSteps": max_steps,
                "message": ""
            })
            self.observer.add_message(
                self.agent_name, ProcessType.MAX_STEPS_REACHED, max_steps_data)
            # _handle_max_steps_reached already yields the final step internally
            # and sets action_step.error, so don't yield again to avoid duplicate error
            final_answer = self._handle_max_steps_reached(task)
            if verification_config.enabled and verification_config.final_verification_enabled:
                final_verification_round += 1
                verification_result = self.verification_controller.verify_final_answer(
                    task=task,
                    candidate=final_answer,
                    memory_summary=self._build_verification_memory_summary(),
                    round_number=final_verification_round,
                )
                if not verification_result.passed:
                    final_answer = self.verification_controller.build_controlled_failure_answer(
                        final_answer,
                        verification_result,
                    )
        yield FinalAnswerStep(handle_agent_output_types(final_answer))


    def _collect_step_metrics(self, action_step: ActionStep):
        """Extract single-step data into structured metrics"""
        metric = {
            "step_number": action_step.step_number,
            "timestamp": time.time(),
            "main_llm": {
                "input_tokens": 0,
                "output_tokens": 0,
            },
            "compression": {
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_hits": 0,
                "cache_types": [],
            },
            "memory_state": {
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
            },
            "uncompressed_mem_est_input": 0,
            "cache_hit": False,
            "cache_types": [],
        }

        # 1. Main model tokens
        if action_step.token_usage:
            metric["main_llm"]["input_tokens"] = action_step.token_usage.input_tokens
            metric["main_llm"]["output_tokens"] = action_step.token_usage.output_tokens

        # 2. Compression overhead is supplied by the active runtime; CoreAgent
        # never branches on managed versus legacy context behavior.
        comp_stats = self.context_runtime.compression_stats()
        metric["compression"].update(comp_stats)
        metric["cache_hit"] = comp_stats.get("cache_hits", 0) > 0
        metric["cache_types"] = comp_stats.get("cache_types", [])

        # 3. Current memory estimated length
        chars_per_token = self.context_runtime.chars_per_token
        metric["memory_state"]["estimated_input_tokens"] = msg_token_count(
            action_step.model_input_messages, chars_per_token
        )
        metric["memory_state"]["estimated_output_tokens"] = msg_token_count(
            action_step.model_output_message, chars_per_token
        )

        # 4. Uncompressed memory estimation
        metric["uncompressed_mem_est_input"] = getattr(
            self, "_last_uncompressed_est", 0
        )
        self._last_uncompressed_est = 0

        # 5. Compression ratio
        uncompressed = metric["uncompressed_mem_est_input"]
        compressed = metric["memory_state"]["estimated_input_tokens"]
        if uncompressed > 0:
            metric["compression_ratio"] = round(
                (1 - compressed / uncompressed) * 100, 1
            )
        else:
            metric["compression_ratio"] = 0.0

        self.step_metrics.append(metric)
        token_threshold = self.context_runtime.token_threshold
        get_monitoring_manager().record_agent_step_metrics(
            metric,
            token_threshold=token_threshold,
        )

    def _handle_max_steps_reached(self, task: str) -> Any:
        """Handle the case when max steps is reached by generating final answer with streaming.

        This method overrides the parent class implementation to use streaming for
        the final answer generation, allowing the observer to receive thinking tokens
        in real-time.

        Args:
            task: The original task prompt

        Returns:
            The final answer content string
        """
        action_step_start_time = time.time()

        # Send STEP_COUNT to start a new step for the final answer thinking process
        # This ensures the thinking content is displayed in the task details panel
        self.observer.add_message(
            self.agent_name, ProcessType.STEP_COUNT, self.step_number)

        # Build messages for final answer generation
        final_context = self.context_runtime.prepare_final_answer(
            model=self.model,
            memory=self.memory,
            current_run_start_idx=self._history_step_count,
            tools=self._context_tools(),
            task=task,
            final_answer_templates=self.prompt_templates,
        )
        messages = final_context.messages

        # Create the final memory step with error
        final_memory_step = ActionStep(
            step_number=self.step_number,
            error=AgentMaxStepsError("Reached max steps.", self.logger),
            timing=Timing(start_time=action_step_start_time),
        )

        # Track accumulated content and token usage for streaming
        accumulated_content = []
        total_input_tokens = 0
        total_output_tokens = 0
        role = None

        try:
            # Use streaming call (model.__call__) to generate final answer
            # This will trigger observer.add_model_new_token() and
            # observer.add_model_reasoning_content() in OpenAIModel
            chat_message: ChatMessage = self.model(messages)

            # Update role and content from the completed message
            role = chat_message.role
            model_output = chat_message.content or ""

            # Accumulate token usage if available
            if chat_message.token_usage:
                total_input_tokens = chat_message.token_usage.input_tokens
                total_output_tokens = chat_message.token_usage.output_tokens

        except Exception as e:
            # Fallback to error message if streaming fails
            model_output = f"Error in generating final LLM output: {e}"
            self.logger.log(f"Error in final answer generation: {e}", level=LogLevel.ERROR)

        # Finalize the memory step
        final_memory_step.timing.end_time = time.time()
        final_memory_step.token_usage = TokenUsage(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens
        )
        final_memory_step.action_output = model_output

        self._finalize_step(final_memory_step)
        self.memory.steps.append(final_memory_step)

        return model_output
