import json
import ast
import time
import threading
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

from ..utils.observer import MessageObserver, ProcessType
from jinja2 import Template, StrictUndefined

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import PIL.Image

from .agent_context import ContextManager
from ..utils.token_estimation import msg_token_count

def parse_code_blobs(text: str) -> str:
    """Extract code blocs from the LLM's output for execution.

    This function is used to parse code that needs to be executed, so it only handles
    <code> format and legacy python formats.

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

    # Fallback to original patterns: py|python (for execution)
    # Use string operations to prevent backtracking
    py_matches = []
    search_pos = 0
    while True:
        # Find ```py or ```python
        start = text.find("```py", search_pos)
        if start == -1:
            start = text.find("```python", search_pos)
        if start == -1:
            break
        # Skip the opening backticks and optional language specifier
        if text[start:start + len("```python")] == "```python":
            content_start = start + len("```python")
        else:
            content_start = start + len("```py")
        # Skip optional newline after opening fence
        if content_start < len(text) and text[content_start] == "\n":
            content_start += 1
        # Find the closing ```
        end = text.find("```", content_start)
        if end == -1:
            break
        py_matches.append(text[content_start:end])
        search_pos = end + len("```")

    if py_matches:
        return "\n\n".join(match.strip() for match in py_matches)

    # Maybe the LLM outputted a code blob directly
    try:
        ast.parse(text)
        return text
    except SyntaxError:
        pass

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


def _build_final_answer_messages(task: str, agent_prompt_templates: Dict[str, Any], memory_messages: List) -> List[ChatMessage]:
    """Build messages for final answer generation.

    Args:
        task: The original task prompt
        agent_prompt_templates: Prompt templates from the agent
        memory_messages: Messages from agent memory

    Returns:
        List of ChatMessage for final answer generation
    """
    from smolagents.models import MessageRole

    messages = [
        ChatMessage(
            role=MessageRole.SYSTEM,
            content=[{"type": "text", "text": agent_prompt_templates["final_answer"]["pre_messages"]}]
        )
    ]
    messages += memory_messages[1:]
    messages.append(
        ChatMessage(
            role=MessageRole.USER,
            content=[{"type": "text", "text": Template(
                agent_prompt_templates["final_answer"]["post_messages"],
                undefined=StrictUndefined
            ).render(task=task)}]
        )
    )
    return messages


class CoreAgent(CodeAgent):
    def __init__(self, observer: MessageObserver, prompt_templates: Dict[str, Any] | None = None, *args, **kwargs):
        super().__init__(prompt_templates=prompt_templates, *args, **kwargs)
        self.observer = observer
        self.stop_event = threading.Event()
        self._history_step_count = 0  # For ContextManager, record boundary for compression
        self.context_manager: ContextManager = None
        self.step_metrics: List[dict] = []  # Quantitative metrics per step
        self._last_uncompressed_est = 0

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

        memory_messages = self.write_memory_to_messages()

        chars_per_token = (
            self.context_manager.config.chars_per_token
            if self.context_manager
            else 1.5
        )
        self._last_uncompressed_est = msg_token_count(
            memory_messages, chars_per_token
        )

        input_messages = memory_messages.copy()
        # import pdb; pdb.set_trace()
        # Trigger context compression if needed before building messages
        if self.context_manager and self.context_manager.config.enabled:
            input_messages = self.context_manager.compress_if_needed(
                self.model, self.memory, input_messages, self._history_step_count
            )
        # Add new step in logs
        memory_step.model_input_messages = input_messages
        stop_sequences = ["Observation:", "Calling tools:"]

        # Prepare additional arguments
        additional_args: dict[str, Any] = {}
        if self._use_structured_outputs_internally:
            additional_args["response_format"] = CODEAGENT_RESPONSE_FORMAT

        # Log model call parameters before execution
        self._log_model_call_parameters(input_messages, stop_sequences, additional_args)

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
        try:
            code_output = self.python_executor(code_action)
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
            raise AgentExecutionError(error_msg, self.logger)

        truncated_output = None
        if code_output is not None and code_output.output is not None:
            truncated_output = truncate_content(str(code_output.output))
            observation += "Last output from code snippet:\n" + truncated_output
        memory_step.observations = observation

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
        self.task = task
        if additional_args is not None:
            self.state.update(additional_args)
            self.task += f"""
You have been provided with these additional arguments, that you can access using the keys as variables in your python code:
{str(additional_args)}."""

        self.memory.system_prompt = SystemPromptStep(
            system_prompt=self.system_prompt)
        if reset:
            self.memory.reset()
            self.monitor.reset()

        self.logger.log_task(content=self.task.strip(),
                             subtitle=f"{type(self.model).__name__} - {(self.model.model_id if hasattr(self.model, 'model_id') else '')}",
                             level=LogLevel.INFO, title=self.name if hasattr(self, "name") else None, )

        # Record current agent task
        self.observer.add_message(
            self.name, ProcessType.AGENT_NEW_RUN, self.task.strip())

        self.memory.steps.append(TaskStep(task=self.task, task_images=images))

        if getattr(self, "python_executor", None):
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
            for message in self.write_memory_to_messages(summary_mode=True):
                content = message.content
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
        while not returned_final_answer and self.step_number <= max_steps and not self.stop_event.is_set():
            step_start_time = time.time()

            action_step = ActionStep(
                step_number=self.step_number, timing=Timing(start_time=step_start_time), observations_images=images
            )
            try:
                for output in self._step_stream(action_step):
                    yield output

                if isinstance(output, ActionOutput) and output.is_final_answer:
                    final_answer = output.output
                    self.logger.log(
                        Text(f"Final answer: {final_answer}", style=f"bold {YELLOW_HEX}"),
                        level=LogLevel.INFO,
                    )

                    if self.final_answer_checks:
                        self._validate_final_answer(final_answer)
                    returned_final_answer = True
                    action_step.is_final_answer = True

            except FinalAnswerError:
                # When the model does not output code, directly treat the large model content as the final answer
                final_answer = action_step.model_output
                if isinstance(final_answer, str):
                    final_answer = convert_code_format(final_answer)
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

        # 2. Compression overhead (from ContextManager)
        if self.context_manager and self.context_manager.config.enabled:
            comp_stats = self.context_manager.get_step_compression_stats()
            metric["compression"].update(comp_stats)
            metric["cache_hit"] = comp_stats.get("cache_hits", 0) > 0
            metric["cache_types"] = comp_stats.get("cache_types", [])
        else:
            metric["compression"] = {
                "calls": 0, "input_tokens": 0, "output_tokens": 0,
                "cache_hits": 0, "cache_types": [],
            }
            metric["cache_hit"] = False
            metric["cache_types"] = []

        # 3. Current memory estimated length
        chars_per_token = (
            self.context_manager.config.chars_per_token
            if self.context_manager
            else 1.5
        )
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
        from smolagents.models import MessageRole

        action_step_start_time = time.time()

        # Send STEP_COUNT to start a new step for the final answer thinking process
        # This ensures the thinking content is displayed in the task details panel
        self.observer.add_message(
            self.agent_name, ProcessType.STEP_COUNT, self.step_number)

        # Build messages for final answer generation
        memory_messages = self.write_memory_to_messages()
        messages = _build_final_answer_messages(task, self.prompt_templates, memory_messages)

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
            self.logger.log(f"Error in final answer generation: {e}", level=LogLevel.WARNING)

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

