import re
import ast
import time
import threading
from textwrap import dedent
from typing import Any, Optional, List, Dict
from collections.abc import Generator

from rich.console import Group
from rich.text import Text

from smolagents.agents import CodeAgent, handle_agent_output_types, AgentError
from smolagents.local_python_executor import fix_final_answer_code
from smolagents.memory import ActionStep, PlanningStep, FinalAnswerStep, ToolCall, TaskStep, SystemPromptStep
from smolagents.models import ChatMessage
from smolagents.monitoring import LogLevel
from smolagents.utils import AgentExecutionError, AgentGenerationError, truncate_content

from ..utils.observer import MessageObserver, ProcessType
from jinja2 import Template, StrictUndefined

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import PIL.Image


def parse_code_blobs(text: str) -> str:
    """Extract code blocs from the LLM's output for execution.

    This function is used to parse code that needs to be executed, so it only handles
    <RUN> format and legacy python formats.

    Args:
        text (`str`): LLM's output text to parse.

    Returns:
        `str`: Extracted code block for execution.

    Raises:
        ValueError: If no valid code block is found in the text.
    """
    # First try to match the new <RUN> format for execution
    # <END_CODE> is optional - match both with and without it
    run_pattern = r"```<RUN>\s*\n(.*?)\n```(?:<END_CODE>)?"
    run_matches = re.findall(run_pattern, text, re.DOTALL)

    if run_matches:
        return "\n\n".join(match.strip() for match in run_matches)

    # Fallback to original patterns: py|python (for execution)
    pattern = r"```(?:py|python)\s*\n(.*?)\n```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return "\n\n".join(match.strip() for match in matches)

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
            ```<RUN>
            # Your python code here (for execution)
            ```<END_CODE>
            """
        ).strip()
    )


def convert_code_format(text):
    """
    Convert code blocks to markdown format for display.

    This function is used to convert code blocks in final answers to markdown format,
    so it handles <DISPLAY:language> format and legacy formats.
    """
    # Handle new format: ```<DISPLAY:language> to ```language
    text = re.sub(r'```<DISPLAY:(\w+)>', r'```\1', text)

    # Handle legacy format: ```code:language to ```language
    text = re.sub(r'```code:(\w+)', r'```\1', text)

    # Restore <END_CODE> if it was affected by the above replacement
    text = text.replace("```<END_CODE>", "```")

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
        try:
            additional_args = {
                "grammar": self.grammar} if self.grammar is not None else {}
            chat_message: ChatMessage = self.model(input_messages,
                                                   stop_sequences=["<END_CODE>", "Observation:", "Calling tools:", "<END_CODE"], **additional_args, )
            memory_step.model_output_message = chat_message
            model_output = chat_message.content
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
            code_action = fix_final_answer_code(parse_code_blobs(model_output))
            # Record parsing results
            self.observer.add_message(
                self.agent_name, ProcessType.PARSE, code_action)

        except Exception:
            self.logger.log_markdown(
                content=model_output, title="AGENT FINAL ANSWER", level=LogLevel.INFO)
            raise FinalAnswerError()

        memory_step.tool_calls = [
            ToolCall(name="python_interpreter", arguments=code_action, id=f"call_{len(self.memory.steps)}", )]

        # Execute
        self.logger.log_code(title="Executing parsed code:",
                             content=code_action, level=LogLevel.INFO)
        is_final_answer = False
        try:
            output, execution_logs, is_final_answer = self.python_executor(
                code_action)

            execution_outputs_console = []
            if len(execution_logs) > 0:
                # Record execution results
                self.observer.add_message(
                    self.agent_name, ProcessType.EXECUTION_LOGS, f"{execution_logs}")

                execution_outputs_console += [
                    Text("Execution logs:", style="bold"), Text(execution_logs), ]
            observation = "Execution logs:\n" + execution_logs
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
            if "Import of " in error_msg and " is not allowed" in error_msg:
                self.logger.log(
                    "[bold red]Warning to user: Code execution failed due to an unauthorized import - Consider passing said import under `additional_authorized_imports` when initializing your CodeAgent.",
                    level=LogLevel.INFO, )
            raise AgentExecutionError(error_msg, self.logger)

        truncated_output = truncate_content(str(output))
        if output is not None:
            observation += "Last output from code snippet:\n" + truncated_output
        memory_step.observations = observation

        execution_outputs_console += [
            Text(f"{('Out - Final answer' if is_final_answer else 'Out')}: {truncated_output}",
                 style=("bold #d4b702" if is_final_answer else ""), ), ]
        self.logger.log(Group(*execution_outputs_console), level=LogLevel.INFO)
        memory_step.action_output = output
        yield output if is_final_answer else None

    def run(self, task: str, stream: bool = False, reset: bool = True, images: Optional[List[str]] = None,
            additional_args: Optional[Dict] = None, max_steps: Optional[int] = None, ):
        """
        Run the agent for the given task.

        Args:
            task (`str`): Task to perform.
            stream (`bool`): Whether to run in a streaming way.
            reset (`bool`): Whether to reset the conversation or keep it going from previous run.
            images (`list[str]`, *optional*): Paths to image(s).
            additional_args (`dict`, *optional*): Any other variables that you want to pass to the agent run, for instance images or dataframes. Give them clear names!
            max_steps (`int`, *optional*): Maximum number of steps the agent can take to solve the task. if not provided, will use the agent's default value.

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

        self.system_prompt = self.initialize_system_prompt()
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
        # Outputs are returned only at the end. We only look at the last step.
        return list(self._run_stream(task=self.task, max_steps=max_steps, images=images))[-1].final_answer

    def __call__(self, task: str, **kwargs):
        """Adds additional prompting for the managed agent, runs it, and wraps the output.
        This method is called only by a managed agent.
        """
        full_task = Template(self.prompt_templates["managed_agent"]["task"], undefined=StrictUndefined).render({
            "name": self.name, "task": task, **self.state
        })
        report = self.run(full_task, **kwargs)

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
                content = message["content"]
                answer += "\n" + truncate_content(str(content)) + "\n---"
            answer += "\n</summary_of_work>"
        return answer

    def _run_stream(
            self, task: str, max_steps: int, images: list["PIL.Image.Image"] | None = None
    ) -> Generator[ActionStep | PlanningStep | FinalAnswerStep]:
        final_answer = None
        self.step_number = 1
        while final_answer is None and self.step_number <= max_steps and not self.stop_event.is_set():
            step_start_time = time.time()

            action_step = ActionStep(
                step_number=self.step_number, start_time=step_start_time, observations_images=images
            )
            try:
                for el in self._execute_step(action_step):
                    yield el
                final_answer = el
            except FinalAnswerError:
                # When the model does not output code, directly treat the large model content as the final answer
                final_answer = action_step.model_output
                if isinstance(final_answer, str):
                    final_answer = convert_code_format(final_answer)

            except AgentError as e:
                action_step.error = e

            finally:
                self._finalize_step(action_step, step_start_time)
                self.memory.steps.append(action_step)
                yield action_step
                self.step_number += 1

        if self.stop_event.is_set():
            final_answer = "<user_break>"

        if final_answer is None and self.step_number == max_steps + 1:
            final_answer = self._handle_max_steps_reached(
                task, images, step_start_time)
            yield action_step
        yield FinalAnswerStep(handle_agent_output_types(final_answer))
