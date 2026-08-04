import json
import re
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Any


_NL2A_WRAPPER_PATTERN = re.compile(r"<nl2a>\s*(.*?)\s*</nl2a>", re.DOTALL)


class ProcessType(Enum):
    MODEL_OUTPUT_THINKING = "model_output_thinking"  # model streaming output, thinking content
    MODEL_OUTPUT_DEEP_THINKING = "model_output_deep_thinking"  # model streaming output, deep thinking content
    MODEL_OUTPUT_CODE = "model_output_code"  # model streaming output, code content

    STEP_COUNT = "step_count"  # current step of agent
    PARSE = "parse"  # code parsing result
    EXECUTION_LOGS = "execution_logs"  # code execution result
    AGENT_NEW_RUN = "agent_new_run"  # Agent basic information
    AGENT_FINISH = "agent_finish"  # sub-agent end of run mark, mainly used for front-end display
    FINAL_ANSWER = "final_answer"  # final summary
    ERROR = "error"  # error field
    OTHER = "other"  # temporary other fields
    TOKEN_COUNT = "token_count"  # record the number of tokens used in each step
    HISTORY_SUMMARY = "history_summary"  # newly-created context compression checkpoint

    SEARCH_CONTENT = "search_content"  # search content in tool
    PICTURE_WEB = "picture_web"  # record the image after联网搜索

    CARD = "card"  # content that needs to be rendered by the front end using cards
    TOOL = "tool"  # tool name
    NL2A = "nl2a"  # structured NL2Agent runtime output
    SKILL_ARTIFACT = "skill_artifact"  # structured file output from a skill script
    MEMORY_SEARCH = "memory_search"  # memory search status
    MAX_STEPS_REACHED = "max_steps_reached"  # agent reached maximum steps limit
    VERIFICATION = "verification"  # layered ReAct self-verification status
    PLAN = "plan"  # structured plan JSON for planning feature
    PLAN_STEP_UPDATE = "plan_step_update"  # single plan step status update
    AUTOMATION_PROPOSAL = "automation_proposal"  # scheduled-task proposal card payload

    SUBAGENT_START = "subagent_start"  # sub-agent invocation boundary, opens a nested group on the frontend
    SUBAGENT_END = "subagent_end"  # sub-agent invocation boundary, closes the nested group


# message transformer base class
class MessageTransformer:
    def transform(self, **kwargs: Any) -> str:
        """convert the content to a specific format"""
        raise NotImplementedError("subclasses must implement the transform method")


# specific implementation class of message transformer
class DefaultTransformer(MessageTransformer):
    def transform(self, **kwargs: Any) -> str:
        """return any message, no processing"""
        content = kwargs.get("content", "")
        return content


class StepCountTransformer(MessageTransformer):
    # step template
    TEMPLATES = {"zh": "\n**步骤 {0}** \n", "en": "\n**Step {0}** \n"}

    def transform(self, **kwargs: Any) -> str:
        """convert the message of step count"""
        content = kwargs.get("content", "")
        lang = kwargs.get("lang", "en")

        template = self.TEMPLATES.get(lang, self.TEMPLATES["en"])
        return template.format(content)


class ParseTransformer(MessageTransformer):
    # parse template
    TEMPLATES = {"zh": "\n🛠️ 使用Python解释器执行代码\n",
                 "en": "\n🛠️ Used tool python_interpreter\n"}

    def transform(self, **kwargs: Any) -> str:
        """convert the message of parse result"""
        content = kwargs.get("content", "")
        lang = kwargs.get("lang", "en")

        template = self.TEMPLATES.get(lang, self.TEMPLATES["en"])
        return template + f"```python\n{content}\n```\n"


class ExecutionLogsTransformer(MessageTransformer):
    def transform(self, **kwargs: Any) -> str:
        """convert the message of execution log"""
        return kwargs.get("content", "")


class FinalAnswerTransformer(MessageTransformer):
    def transform(self, **kwargs: Any) -> str:
        """convert the message of final answer"""
        content = kwargs.get("content", "")

        return f"{content}"


class TokenCountTransformer(MessageTransformer):
    def transform(self, **kwargs: Any) -> str:
        """Pass through token stats JSON content unchanged for frontend consumption."""
        return kwargs.get("content", "")


class MessageObserver:
    # set the maximum buffer size, can be adjusted according to needs
    MAX_TOKEN_BUFFER_SIZE = 10

    def __init__(self, lang="zh", enable_nl2a_wrapper=False):
        # unified output to the front end string, changed to queue
        self.message_query = []

        # control output language
        self.lang = lang
        self.enable_nl2a_wrapper = enable_nl2a_wrapper

        # initialize message transformer
        self._init_message_transformers()

        # double-ended queue for storing and analyzing the latest tokens
        self.token_buffer = deque()

        # current output mode: default is thinking mode
        self.current_mode = ProcessType.MODEL_OUTPUT_THINKING

        # code block marker mode
        self.code_pattern = re.compile(r"(代码|Code)([：:])\s*```")

        # think tag state management for real-time processing
        self.think_buffer = deque()
        self.in_think_mode = False
        self.think_start_pattern = re.compile(r"<think>")
        self.think_end_pattern = re.compile(r"</think>")

        # Sub-agent nesting depth. 0 = main agent, +1 per entered sub-agent.
        # Context-local storage prevents concurrently executing tools from
        # affecting each other's frontend nesting hierarchy.
        self._current_depth: ContextVar[int] = ContextVar("current_depth", default=0)
        self._tool_call_id: ContextVar[str | None] = ContextVar(
            "tool_call_id", default=None
        )

    def _init_message_transformers(self):
        """initialize the mapping of message type to transformer"""
        default_transformer = DefaultTransformer()

        self.transformers = {
            ProcessType.AGENT_NEW_RUN: default_transformer,
            ProcessType.STEP_COUNT: StepCountTransformer(),
            ProcessType.PARSE: ParseTransformer(),
            ProcessType.EXECUTION_LOGS: ExecutionLogsTransformer(),
            ProcessType.FINAL_ANSWER: FinalAnswerTransformer(),
            ProcessType.ERROR: default_transformer,
            ProcessType.OTHER: default_transformer,
            ProcessType.SEARCH_CONTENT: default_transformer,
            ProcessType.TOKEN_COUNT: TokenCountTransformer(),
            ProcessType.HISTORY_SUMMARY: default_transformer,
            ProcessType.PICTURE_WEB: default_transformer,
            ProcessType.AGENT_FINISH: default_transformer,
            ProcessType.CARD: default_transformer,
            ProcessType.TOOL: default_transformer,
            ProcessType.NL2A: default_transformer,
            ProcessType.SKILL_ARTIFACT: default_transformer,
            ProcessType.MEMORY_SEARCH: default_transformer,
            ProcessType.VERIFICATION: default_transformer,
            ProcessType.MAX_STEPS_REACHED: default_transformer,
            ProcessType.PLAN: default_transformer,
            ProcessType.PLAN_STEP_UPDATE: default_transformer,
            ProcessType.AUTOMATION_PROPOSAL: default_transformer,
        }

    def add_model_new_token(self, new_token):
        """
        Process streaming tokens with real-time think tag detection and content classification
        """
        # Add token to think buffer
        self.think_buffer.append(new_token)

        # Check for think tag patterns in the buffer
        buffer_text = ''.join(self.think_buffer)

        # Check for think start tag
        if not self.in_think_mode:
            start_match = self.think_start_pattern.search(buffer_text)
            if start_match:
                # Found <think> tag, switch to think mode
                self.in_think_mode = True
                # Clear buffer and keep only content after <think>
                self.think_buffer.clear()
                think_content = buffer_text[start_match.end():]
                if think_content:
                    self.think_buffer.append(think_content)

        # Check for think end tag
        if self.in_think_mode:
            end_match = self.think_end_pattern.search(buffer_text)
            if end_match:
                # Found </think> tag, exit think mode
                self.in_think_mode = False
                # Process think content before </think>
                think_content = buffer_text[:end_match.start()]
                if think_content:
                    self.message_query.append(
                        Message(ProcessType.MODEL_OUTPUT_DEEP_THINKING, think_content).to_json())

                # Process content after </think> as normal content
                after_think = buffer_text[end_match.end():]
                if after_think:
                    self._process_normal_content(after_think)
                self.think_buffer.clear()

        while len(self.think_buffer) > self.MAX_TOKEN_BUFFER_SIZE:
            # Flush ALL tokens that exceed buffer size at once to avoid fragmentation
            # Each flush is a single message_query.append with multiple tokens concatenated
            accumulated_content = ''.join(list(self.think_buffer)[:-self.MAX_TOKEN_BUFFER_SIZE])
            # Remove the flushed tokens from buffer
            for _ in range(len(self.think_buffer) - self.MAX_TOKEN_BUFFER_SIZE):
                self.think_buffer.popleft()
            # Send accumulated content
            if accumulated_content:
                if self.in_think_mode:
                    self.message_query.append(
                        Message(ProcessType.MODEL_OUTPUT_DEEP_THINKING, accumulated_content).to_json())
                else:
                    self._process_normal_content(accumulated_content)


    def _process_normal_content(self, content):
        """
        Process normal content (non-deep-think content) for code block detection
        """
        self.token_buffer.append(content)

        # concatenate the buffer into text for checking code blocks
        buffer_text = ''.join(self.token_buffer)

        # find the code block marker
        match = self.code_pattern.search(buffer_text)

        if match:
            # found the code block marker
            match_start = match.start()

            # only switch mode when in thinking mode
            if self.current_mode == ProcessType.MODEL_OUTPUT_THINKING:
                # send the content before the matching position as thinking
                prefix_text = buffer_text[:match_start]
                if prefix_text:
                    self.message_query.append(
                        Message(ProcessType.MODEL_OUTPUT_THINKING, prefix_text).to_json())

                # send the content after the matching part as code
                code_text = buffer_text[match_start:]
                if code_text:
                    self.message_query.append(
                        Message(ProcessType.MODEL_OUTPUT_CODE, code_text).to_json())

                # switch mode
                self.current_mode = ProcessType.MODEL_OUTPUT_CODE
            else:
                # already in code mode, send the entire buffer content as code
                self.message_query.append(
                    Message(ProcessType.MODEL_OUTPUT_CODE, buffer_text).to_json())

            # clear the buffer
            self.token_buffer.clear()
        else:
            # not found the code block marker, pop the first token from the queue (if the buffer length exceeds a certain size)
            max_buffer_size = self.MAX_TOKEN_BUFFER_SIZE
            if len(self.token_buffer) > max_buffer_size:
                # Flush ALL tokens that exceed buffer size at once to avoid fragmentation
                accumulated_content = ''.join(list(self.token_buffer)[:-max_buffer_size])
                # Remove the flushed tokens from buffer
                for _ in range(len(self.token_buffer) - max_buffer_size):
                    self.token_buffer.popleft()
                # Send accumulated content
                self.message_query.append(
                    Message(self.current_mode, accumulated_content).to_json())

    def flush_remaining_tokens(self):
        """
        send the remaining tokens in the double-ended queue
        """
        # Process remaining think buffer content
        if self.think_buffer:
            think_buffer_text = ''.join(self.think_buffer)
            if self.in_think_mode:
                # Still in think mode, remove any think tags and process as deep thinking
                think_buffer_text = re.sub(r"<think>|</think>", "", think_buffer_text)
                if think_buffer_text:
                    self.message_query.append(
                        Message(ProcessType.MODEL_OUTPUT_DEEP_THINKING, think_buffer_text).to_json())
            else:
                # Not in think mode, process as normal content
                if think_buffer_text:
                    self._process_normal_content(think_buffer_text)
            self.think_buffer.clear()

        # Process remaining normal buffer content
        if self.token_buffer:
            buffer_text = ''.join(self.token_buffer)
            self.message_query.append(
                Message(self.current_mode, buffer_text).to_json())
            self.token_buffer.clear()

    @staticmethod
    def _extract_nl2a_wrapper(content):
        """Extract one valid NL2Agent JSON wrapper from tool execution logs."""
        if not isinstance(content, str):
            return None, content

        match = _NL2A_WRAPPER_PATTERN.search(content)
        if match is None:
            return None, content

        visible_content = (
            content[:match.start()] + content[match.end():]
        ).strip()
        try:
            payload = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            return None, visible_content

        if not isinstance(payload, dict):
            return None, visible_content
        return json.dumps(payload, ensure_ascii=False), visible_content

    def add_message(self, agent_name, process_type, content, **kwargs):
        """add message to the queue"""
        transformer = self.transformers.get(
            process_type, self.transformers[ProcessType.OTHER])
        formatted_content = transformer.transform(
            content=content, lang=self.lang, agent_name=agent_name, **kwargs)

        if (
            self.enable_nl2a_wrapper
            and process_type == ProcessType.EXECUTION_LOGS
        ):
            nl2a_content, formatted_content = self._extract_nl2a_wrapper(
                formatted_content
            )
            if nl2a_content is not None:
                self.message_query.append(
                    Message(ProcessType.NL2A, nl2a_content).to_json()
                )

        tool_name = kwargs.get("tool_name")
        tool_arguments = kwargs.get("tool_arguments")
        tool_call_id = kwargs.get("tool_call_id") or self._tool_call_id.get()
        agent_id = kwargs.get("agent_id")

        self.message_query.append(
            Message(process_type, formatted_content, tool_name=tool_name,
                    tool_arguments=tool_arguments,
                    tool_call_id=tool_call_id,
                    agent_id=agent_id,
                    depth=self._current_depth.get()).to_json())

    @contextmanager
    def tool_call_context(self, tool_call_id: str):
        """Associate observer output with one executing tool invocation."""
        token = self._tool_call_id.set(tool_call_id)
        try:
            yield
        finally:
            self._tool_call_id.reset(token)

    def add_subagent_start(self, agent_id, agent_name, task=None):
        """Emit a subagent_start boundary and push the nesting depth.

        The chunk's ``content`` is a JSON blob so the downstream persistence
        layer (which only stores ``content`` for each unit) keeps enough
        information to reconstruct the sub-agent card on history replay.

        Args:
            agent_id: Stable identifier of the sub-agent.
            agent_name: Display name surfaced on the frontend sub-agent card.
            task: Optional task text forwarded from the parent's call (e.g.
                ``task="search the weather"``).
        """
        depth = self._current_depth.get() + 1
        self._current_depth.set(depth)
        payload = json.dumps(
            {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "task": task if task is not None else "",
            },
            ensure_ascii=False,
        )
        self.message_query.append(
            Message(
                ProcessType.SUBAGENT_START,
                payload,
                agent_id=agent_id,
                agent_name=agent_name,
                depth=depth,
            ).to_json()
        )

    def add_subagent_end(self, agent_id, agent_name):
        """Emit a subagent_end boundary and pop the nesting depth.

        Depth is clamped at 0 to stay resilient against unbalanced starts/ends
        from upstream tooling.
        """
        depth = self._current_depth.get()
        payload = json.dumps(
            {"agent_id": agent_id, "agent_name": agent_name},
            ensure_ascii=False,
        )
        self.message_query.append(
            Message(
                ProcessType.SUBAGENT_END,
                payload,
                agent_id=agent_id,
                agent_name=agent_name,
                depth=max(depth, 1),
            ).to_json()
        )
        self._current_depth.set(max(0, depth - 1))

    def add_model_reasoning_content(self, reasoning_content):
        """
        Handle reasoning content from the model with type MODEL_OUTPUT_DEEP_THINKING
        """
        if reasoning_content:
            self.message_query.append(
                Message(ProcessType.MODEL_OUTPUT_DEEP_THINKING, reasoning_content).to_json())

    def get_cached_message(self):
        cached_message = self.message_query
        self.message_query = []
        return cached_message

    def get_final_answer(self):
        for item in self.message_query:
            if isinstance(item, str):
                try:
                    data = json.loads(item)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == ProcessType.FINAL_ANSWER.value:
                    return data.get("content")

        return None

# fixed MessageObserver output format
class Message:
    def __init__(self, message_type: ProcessType, content, tool_name: str = None,
                 tool_arguments: dict = None, agent_id=None, agent_name: str = None,
                 depth: int = 0, tool_call_id: str | None = None):
        self.message_type = message_type
        self.content = content
        self.tool_name = tool_name
        self.tool_arguments = tool_arguments
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.depth = depth
        self.tool_call_id = tool_call_id

    # generate json format and convert to string
    def to_json(self):
        result = {"type": self.message_type.value}
        # Always include content (running prompt text)
        if isinstance(self.content, dict):
            result["content"] = self.content
        else:
            result["content"] = self.content
        # Add tool metadata if available
        if self.tool_name is not None:
            result["tool_name"] = self.tool_name
        if self.tool_arguments is not None:
            result["tool_arguments"] = self.tool_arguments
        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id
        # Sub-agent metadata. Only emitted when populated so legacy consumers
        # see byte-for-byte identical payloads for non-subagent chunks.
        if self.agent_id is not None:
            result["agent_id"] = self.agent_id
        if self.agent_name is not None:
            result["agent_name"] = self.agent_name
        if self.depth:
            result["depth"] = self.depth
        return json.dumps(result, ensure_ascii=False)
