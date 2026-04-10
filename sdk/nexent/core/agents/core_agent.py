import json
import re
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


def parse_code_blobs(text: str) -> str:
    """Extract code blocks from the LLM's output for execution.

    Supports multiple formats:
    1. Standard markdown: ```python ... ```
    2. XML tool_call format: <tool_call>...<tool>...</tool>...</tool_call>
    3. FunctionCall format: <FunctionCallBegin>...</FunctionCallEnd>
    4. Invoke format: <invoke name="tool">...</invoke> (Anthropic/Claude style)
    5. Direct Python code (fallback)

    Args:
        text (`str`): LLM's output text to parse.

    Returns:
        `str`: Extracted code block for execution.

    Raises:
        ValueError: If no valid code block is found in the text.
    """
    # Match standard python code blocks: ```python or ```py
    pattern = r"```(?:py|python)\s*\n(.*?)\n```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return "\n\n".join(match.strip() for match in matches)

    # Handle XML tool_call format (for models like MiniMax with native agent support)
    if "<tool_call>" in text and "</tool_call>" in text:
        tool_code = _parse_xml_tool_call(text)
        if tool_code:
            return tool_code

    # Handle FunctionCall format: <FunctionCallBegin>...<FunctionCallEnd>
    if "<FunctionCallBegin>" in text and "<FunctionCallEnd>" in text:
        tool_code = _parse_function_call(text)
        if tool_code:
            return tool_code

    # Handle Invoke format: <invoke name="tool">...</invoke> (Anthropic/Claude style)
    if "<invoke name=" in text and "</invoke>" in text:
        tool_code = _parse_invoke_format(text)
        if tool_code:
            return tool_code

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
            ```python
            # Your python code here (for execution)
            ```
            """
        ).strip()
    )


def _parse_xml_tool_call(text: str) -> str | None:
    """Parse XML tool_call format and convert to Python code.

    Supports multiple variants:
    ```xml
    <!-- Variant 1: with <param> tags -->
    <tool_call>
    <tool name="tool_name">
    <param name="param1">value1</param>
    </tool>
    </tool_call>

    <!-- Variant 2: direct attribute style -->
    <tool_call>
    <tool name="tool_name">
    param1="value1"
    </tool>
    </tool_call>
    ```
    To:
    ```python
    tool_name(param1="value1")
    ```

    Args:
        text: Input text containing tool_call XML format.

    Returns:
        Python code string if parsing succeeds, None otherwise.
    """
    code_lines = []

    # Find all <tool name="..."> blocks
    tool_pattern = r"<tool\s+name=\"([^\"]+)\">"
    param_pattern = r"<param\s+name=\"([^\"]+)\">([^<]*)</param>"
    direct_param_pattern = r"(\w+)=\"([^\"]*)\""

    for tool_match in re.finditer(tool_pattern, text):
        tool_name = tool_match.group(1)
        tool_start = tool_match.start()

        # Find the end of this tool block
        remaining = text[tool_start:]
        tool_end_match = re.search(r"</tool>", remaining)
        if not tool_end_match:
            continue

        tool_content = remaining[:tool_end_match.end()]
        params = []

        # Try to extract params with <param name="...">...</param> format first
        param_matches = list(re.finditer(param_pattern, tool_content))
        if param_matches:
            for param_match in param_matches:
                param_name = param_match.group(1)
                param_value = param_match.group(2).strip()
                escaped = param_value.replace('\\', '\\\\').replace('"', '\\"')
                params.append(f'{param_name}="{escaped}"')
        else:
            # Fallback: try direct attribute format: param_name="value"
            for direct_match in re.finditer(direct_param_pattern, tool_content):
                param_name = direct_match.group(1)
                param_value = direct_match.group(2)
                escaped = param_value.replace('\\', '\\\\').replace('"', '\\"')
                params.append(f'{param_name}="{escaped}"')

        # Build function call
        if params:
            code_lines.append(f"{tool_name}({', '.join(params)})")
        else:
            code_lines.append(f"{tool_name}()")

    if code_lines:
        return "\n".join(code_lines)

    return None


def _parse_function_call(text: str) -> str | None:
    """Parse FunctionCall format and convert to Python code.

    Converts:
    ```json
    <FunctionCallBegin>
    {
      tool => "tool_name",
      args => {
        param1="value1",
        param2="value2"
      }
    }
    <FunctionCallEnd>
    ```
    To:
    ```python
    tool_name(param1="value1", param2="value2")
    ```

    Args:
        text: Input text containing FunctionCall format.

    Returns:
        Python code string if parsing succeeds, None otherwise.
    """
    code_lines = []

    # Find all FunctionCall blocks
    pattern = r"<FunctionCallBegin>\s*\{([^}]+)\}\s*<FunctionCallEnd>"
    matches = re.findall(pattern, text, re.DOTALL)

    for match in matches:
        # Extract tool name
        tool_match = re.search(r'tool\s*=>\s*"([^"]+)"', match)
        if not tool_match:
            tool_match = re.search(r'tool\s*=\s*"([^"]+)"', match)

        if not tool_match:
            continue

        tool_name = tool_match.group(1)

        # Extract all parameters from args block
        args_match = re.search(r'args\s*=>?\s*\{([^}]*)\}', match, re.DOTALL)
        if not args_match:
            # No args, just tool call
            code_lines.append(f"{tool_name}()")
            continue

        args_content = args_match.group(1)
        params = []

        # Parse each parameter: param_name="value" or param_name="value"
        # Handle both => and = operators
        param_pattern = r'(\w+)\s*=>?\s*"([^"]*)"'
        for param_match in re.finditer(param_pattern, args_content):
            param_name = param_match.group(1)
            param_value = param_match.group(2)
            params.append(f'{param_name}="{param_value}"')

        if params:
            code_lines.append(f"{tool_name}({', '.join(params)})")
        else:
            code_lines.append(f"{tool_name}()")

    if code_lines:
        return "\n".join(code_lines)

    return None


def _parse_invoke_format(text: str) -> str | None:
    """Parse Invoke format and convert to Python code.

    Converts Anthropic/Claude style tool calls:
    ```xml
    <invoke name="read_skill_md">
    <parameter name="skill_name">scientific-brainstorming</parameter>
    </invoke>
    ```
    To:
    ```python
    read_skill_md(skill_name="scientific-brainstorming")
    ```

    Args:
        text: Input text containing Invoke format.

    Returns:
        Python code string if parsing succeeds, None otherwise.
    """
    code_lines = []

    # Find all <invoke name="..."> blocks
    invoke_pattern = r'<invoke\s+name="([^"]+)"[^>]*>(.*?)</invoke>'
    matches = re.findall(invoke_pattern, text, re.DOTALL)

    for tool_name, tool_content in matches:
        params = []

        # Extract all <parameter name="...">...</parameter> blocks
        param_pattern = r'<parameter\s+name="([^"]+)"[^>]*>([^<]*)</parameter>'
        for param_match in re.finditer(param_pattern, tool_content):
            param_name = param_match.group(1)
            param_value = param_match.group(2).strip()

            # Escape quotes in the value
            escaped = param_value.replace('\\', '\\\\').replace('"', '\\"')
            params.append(f'{param_name}="{escaped}"')

        # Build function call
        if params:
            code_lines.append(f"{tool_name}({', '.join(params)})")
        else:
            code_lines.append(f"{tool_name}()")

    if code_lines:
        return "\n".join(code_lines)

    return None


def convert_code_format(text):
    """
    Convert code blocks to markdown format for display.

    This function converts <DISPLAY:language> format to standard markdown format.
    """
    # Handle format: ```<DISPLAY:language> to ```language
    text = re.sub(r'```<DISPLAY:(\w+)>', r'```\1', text)

    # Handle legacy format: ```code:language to ```language
    text = re.sub(r'```code:(\w+)', r'```\1', text)

    # Clean up any remaining ```< patterns
    text = text.replace("```<", "```")

    return text


class FinalAnswerError(Exception):
    """Raised when agent output directly."""
    pass


class CoreAgent(CodeAgent):
    def __init__(self, observer: MessageObserver, prompt_templates: Dict[str, Any] | None = None, *args, **kwargs):
        super().__init__(prompt_templates=prompt_templates, *args, **kwargs)
        self.observer = observer
        self.stop_event = threading.Event()

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
            self.logger.log(f"Failed to log model call parameters: {e}", level=LogLevel.WARNING)

    def _step_stream(self, memory_step: ActionStep) -> Generator[Any]:
        """
        Perform one step in the ReAct framework: the agent thinks, acts, and observes the result.
        Returns None if the step is not final.
        """
        self.observer.add_message(
            self.agent_name, ProcessType.STEP_COUNT, self.step_number)

        memory_messages = self.write_memory_to_messages()

        input_messages = memory_messages.copy()

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
        except:
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
                self.memory.steps.append(action_step)
                yield action_step
                self.step_number += 1

        if self.stop_event.is_set():
            final_answer = "<user_break>"

        if not returned_final_answer and self.step_number == max_steps + 1:
            final_answer = self._handle_max_steps_reached(task)
            yield action_step
        yield FinalAnswerStep(handle_agent_output_types(final_answer))
