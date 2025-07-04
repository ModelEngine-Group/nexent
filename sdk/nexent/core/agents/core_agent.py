import time
import threading
from collections import deque
from typing import Union, Any, Optional, List, Dict, Generator

from rich.console import Group
from rich.text import Text

from smolagents.agents import CodeAgent, populate_template, handle_agent_output_types, AgentError, AgentType
from smolagents.local_python_executor import fix_final_answer_code
from smolagents.memory import ActionStep, ToolCall, TaskStep, SystemPromptStep
from smolagents.models import ChatMessage
from smolagents.monitoring import LogLevel
from smolagents.utils import AgentExecutionError, AgentGenerationError, AgentParsingError, parse_code_blobs, \
    truncate_content

from ..utils.observer import MessageObserver, ProcessType


class CoreAgent(CodeAgent):
    def __init__(self, observer: MessageObserver, prompt_templates, *args, **kwargs):
        super().__init__(prompt_templates=prompt_templates, *args, **kwargs)
        self.observer = observer
        self.stop_event = threading.Event()

    def step(self, memory_step: ActionStep) -> Union[None, Any]:
        """
        Perform one step in the ReAct framework: the agent thinks, acts, and observes the result.
        Returns None if the step is not final.
        """
        self.observer.add_message(self.agent_name, ProcessType.STEP_COUNT, self.step_number)

        memory_messages = self.write_memory_to_messages()

        self.input_messages = memory_messages.copy()

        # Add new step in logs
        memory_step.model_input_messages = memory_messages.copy()
        try:
            additional_args = {"grammar": self.grammar} if self.grammar is not None else {}
            chat_message: ChatMessage = self.model(self.input_messages,
                stop_sequences=["<end_code>", "Observation:", "Calling tools:", "<end_code"], **additional_args, )
            memory_step.model_output_message = chat_message
            model_output = chat_message.content
            memory_step.model_output = model_output
        except Exception as e:
            raise AgentGenerationError(f"Error in generating model output:\n{e}", self.logger) from e

        self.logger.log_markdown(content=model_output, title="Output message of the LLM:", level=LogLevel.DEBUG, )

        # Parse
        try:
            code_action = fix_final_answer_code(parse_code_blobs(model_output))
            # 记录解析结果
            self.observer.add_message(self.agent_name, ProcessType.PARSE, code_action)

        except Exception as e:
            error_msg = f"Error in code parsing:\n{e}\nMake sure to provide correct code blobs."
            raise AgentParsingError(error_msg, self.logger)

        memory_step.tool_calls = [
            ToolCall(name="python_interpreter", arguments=code_action, id=f"call_{len(self.memory.steps)}", )]

        # Execute
        self.logger.log_code(title="Executing parsed code:", content=code_action, level=LogLevel.INFO)
        is_final_answer = False
        try:
            output, execution_logs, is_final_answer = self.python_executor(code_action)

            execution_outputs_console = []
            if len(execution_logs) > 0:
                # 记录运行结果
                self.observer.add_message(self.agent_name, ProcessType.EXECUTION_LOGS, f"{execution_logs}")

                execution_outputs_console += [Text("Execution logs:", style="bold"), Text(execution_logs), ]
            observation = "Execution logs:\n" + execution_logs
        except Exception as e:
            if hasattr(self.python_executor, "state") and "_print_outputs" in self.python_executor.state:
                execution_logs = str(self.python_executor.state["_print_outputs"])
                if len(execution_logs) > 0:
                    # 记录运行结果
                    self.observer.add_message(self.agent_name, ProcessType.EXECUTION_LOGS, f"{execution_logs}\n")

                    execution_outputs_console = [Text("Execution logs:", style="bold"), Text(execution_logs), ]
                    memory_step.observations = "Execution logs:\n" + execution_logs
                    self.logger.log(Group(*execution_outputs_console), level=LogLevel.INFO)
            error_msg = str(e)
            if "Import of " in error_msg and " is not allowed" in error_msg:
                self.logger.log(
                    "[bold red]Warning to user: Code execution failed due to an unauthorized import - Consider passing said import under `additional_authorized_imports` when initializing your CodeAgent.",
                    level=LogLevel.INFO, )
            raise AgentExecutionError(error_msg, self.logger)

        truncated_output = truncate_content(str(output))
        observation += "Last output from code snippet:\n" + truncated_output
        memory_step.observations = observation

        execution_outputs_console += [
            Text(f"{('Out - Final answer' if is_final_answer else 'Out')}: {truncated_output}",
                style=("bold #d4b702" if is_final_answer else ""), ), ]
        self.logger.log(Group(*execution_outputs_console), level=LogLevel.INFO)
        memory_step.action_output = output
        return output if is_final_answer else None

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
        self.memory.system_prompt = SystemPromptStep(system_prompt=self.system_prompt)
        if reset:
            self.memory.reset()
            self.monitor.reset()

        self.logger.log_task(content=self.task.strip(),
            subtitle=f"{type(self.model).__name__} - {(self.model.model_id if hasattr(self.model, 'model_id') else '')}",
            level=LogLevel.INFO, title=self.name if hasattr(self, "name") else None, )

        # 记录当前agent任务
        self.observer.add_message(self.name, ProcessType.AGENT_NEW_RUN, self.task.strip())

        self.memory.steps.append(TaskStep(task=self.task, task_images=images))

        if getattr(self, "python_executor", None):
            self.python_executor.send_variables(variables=self.state)
            self.python_executor.send_tools({**self.tools, **self.managed_agents})

        if stream:
            # The steps are returned as they are executed through a generator to iterate on.
            return self._run(task=self.task, max_steps=max_steps, images=images)
        # Outputs are returned only at the end. We only look at the last step.
        return deque(self._run(task=self.task, max_steps=max_steps, images=images), maxlen=1)[0]

    def __call__(self, task: str, **kwargs):
        """Adds additional prompting for the managed agent, runs it, and wraps the output.
        This method is called only by a managed agent.
        """
        full_task = populate_template(self.prompt_templates["managed_agent"]["task"],
            variables=dict(name=self.name, task=task), )
        report = self.run(full_task, **kwargs)

        # 当子Agent运行结束，返回标记
        try:
            self.observer.add_message(self.name, ProcessType.AGENT_FINISH, str(report))
        except:
            self.observer.add_message(self.name, ProcessType.AGENT_FINISH, "")

        answer = populate_template(self.prompt_templates["managed_agent"]["report"],
            variables=dict(name=self.name, final_answer=report))
        if self.provide_run_summary:
            answer += "\n\nFor more detail, find below a summary of this agent's work:\n<summary_of_work>\n"
            for message in self.write_memory_to_messages(summary_mode=True):
                content = message["content"]
                answer += "\n" + truncate_content(str(content)) + "\n---"
            answer += "\n</summary_of_work>"
        return answer

    def _run(self, task: str, max_steps: int, images: List[str] | None = None) -> Generator[
        ActionStep | AgentType, None, None]:
        final_answer = None
        self.step_number = 1
        while final_answer is None and self.step_number <= max_steps and not self.stop_event.is_set():
            step_start_time = time.time()
            memory_step = self._create_memory_step(step_start_time, images)
            try:
                final_answer = self._execute_step(task, memory_step)

            except AgentError as e:
                except_parse_error_pattern = """Make sure to include code with the correct pattern, for instance"""
                if except_parse_error_pattern in e.message:
                    # 当检测到模型没有输出code时，直接将大模型内容当成final_answer
                    final_answer = memory_step.model_output
                else:
                    memory_step.error = e

            finally:
                self._finalize_step(memory_step, step_start_time)
                yield memory_step
                self.step_number += 1

        if self.stop_event.is_set():
            final_answer = "Agent stopped by user"

        if final_answer is None and self.step_number == max_steps + 1:
            final_answer = self._handle_max_steps_reached(task, images, step_start_time)
            yield memory_step
        yield handle_agent_output_types(final_answer)
