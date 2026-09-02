import json
import re
import threading
import uuid
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Any


_NL2A_WRAPPER_PATTERN = re.compile(r"<nl2a>\s*(.*?)\s*</nl2a>", re.DOTALL)
_NL2A_STATE_PATTERN = re.compile(
    r"<nl2a_state>\s*(.*?)\s*</nl2a_state>",
    re.DOTALL,
)
_NL2AGENT_DRAFT_SYNC_FIELDS = frozenset(
    {
        "description",
        "duty_prompt",
        "constraint_prompt",
        "few_shots_prompt",
        "greeting_message",
        "example_questions",
    }
)


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
    CONTEXT_BUDGET = "context_budget"  # content-free P3 final request budget snapshot
    LLM_USAGE = "llm_usage"  # P7 normalized usage for one physical provider call
    TURN_USAGE = "turn_usage"  # P7 deterministic user-turn usage summary

    SEARCH_CONTENT = "search_content"  # search content in tool
    PICTURE_WEB = "picture_web"  # record the image after联网搜索

    CARD = "card"  # content that needs to be rendered by the front end using cards
    TOOL = "tool"  # tool name
    NL2A = "nl2a"  # structured NL2Agent runtime output
    NL2A_STATE = "nl2a_state"  # trusted NL2Agent workflow state update
    SKILL_ARTIFACT = "skill_artifact"  # structured file output from a skill script
    FILE_ARTIFACT = "file_artifact"  # files already uploaded from the run workspace
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
        # Unified output queue consumed by the agent streaming bridge.
        self.message_query = []
        self._message_query_lock = threading.Lock()

        # Control output language
        self.lang = lang
        self.enable_nl2a_wrapper = enable_nl2a_wrapper
        self._nl2a_state_events: set[str] = set()
        self._nl2a_state_lock = threading.Lock()

        # Thread-local state for stream parsing. Must be created before
        # ``_init_message_transformers()`` because that call triggers setters
        # on ``current_mode`` and ``token_buffer``.
        self._stream_state = threading.local()

        # initialize message transformer
        self._init_message_transformers()

        # Code block marker mode
        self.code_pattern = re.compile(r"(代码|Code)([：:])\s*```")

        # Think tag state management for real-time processing.
        self.think_start_pattern = re.compile(r"<think>")
        self.think_end_pattern = re.compile(r"</think>")

        # Sub-agent nesting depth. 0 = main agent, +1 per entered sub-agent.
        # Context-local storage prevents concurrently executing tools from
        # affecting each other's frontend nesting hierarchy.
        self._current_depth: ContextVar[int] = ContextVar("current_depth", default=0)
        self._tool_call_id: ContextVar[str | None] = ContextVar(
            "tool_call_id", default=None
        )
        # Stack of currently-open sub-agent invocations. Each tuple records
        # ``(invocation_id, agent_id, agent_name)`` so every emitted ``Message``
        # can auto-attribute itself to the active sub-agent — including the
        # parallel case where two siblings are open at the same depth and a
        # stack-top heuristic would otherwise mis-route their events.
        # ``default=()`` is an immutable empty tuple; ``set`` always replaces
        # it with a fresh tuple so we never share mutable state across threads.
        self._subagent_stack: ContextVar[tuple] = ContextVar(
            "subagent_stack", default=()
        )
        self._current_invocation_id: ContextVar[str | None] = ContextVar(
            "current_invocation_id", default=None
        )

    @property
    def token_buffer(self) -> deque:
        if not hasattr(self._stream_state, "token_buffer"):
            self._stream_state.token_buffer = deque()
        return self._stream_state.token_buffer

    @token_buffer.setter
    def token_buffer(self, value: deque) -> None:
        self._stream_state.token_buffer = value

    @property
    def think_buffer(self) -> deque:
        if not hasattr(self._stream_state, "think_buffer"):
            self._stream_state.think_buffer = deque()
        return self._stream_state.think_buffer

    @think_buffer.setter
    def think_buffer(self, value: deque) -> None:
        self._stream_state.think_buffer = value

    @property
    def current_mode(self) -> ProcessType:
        return getattr(
            self._stream_state,
            "current_mode",
            ProcessType.MODEL_OUTPUT_THINKING,
        )

    @current_mode.setter
    def current_mode(self, value: ProcessType) -> None:
        self._stream_state.current_mode = value

    @property
    def in_think_mode(self) -> bool:
        return getattr(self._stream_state, "in_think_mode", False)

    @in_think_mode.setter
    def in_think_mode(self, value: bool) -> None:
        self._stream_state.in_think_mode = value

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
            ProcessType.CONTEXT_BUDGET: default_transformer,
            ProcessType.LLM_USAGE: default_transformer,
            ProcessType.TURN_USAGE: default_transformer,
            ProcessType.PICTURE_WEB: default_transformer,
            ProcessType.AGENT_FINISH: default_transformer,
            ProcessType.CARD: default_transformer,
            ProcessType.TOOL: default_transformer,
            ProcessType.NL2A: default_transformer,
            ProcessType.NL2A_STATE: default_transformer,
            ProcessType.SKILL_ARTIFACT: default_transformer,
            ProcessType.FILE_ARTIFACT: default_transformer,
            ProcessType.MEMORY_SEARCH: default_transformer,
            ProcessType.VERIFICATION: default_transformer,
            ProcessType.MAX_STEPS_REACHED: default_transformer,
            ProcessType.PLAN: default_transformer,
            ProcessType.PLAN_STEP_UPDATE: default_transformer,
            ProcessType.AUTOMATION_PROPOSAL: default_transformer,
        }

    def _active_subagent(self) -> tuple | None:
        """Return ``(invocation_id, agent_id, agent_name)`` for the current
        sub-agent scope, or ``None`` when running at the parent level."""
        stack = self._subagent_stack.get()
        return stack[-1] if stack else None

    def _append_message(self, message: str) -> None:
        with self._message_query_lock:
            self.message_query.append(message)

    def _emit(
        self,
        process_type: ProcessType,
        content: Any,
        *,
        tool_name: str | None = None,
        tool_arguments: Any = None,
        tool_call_id: str | None = None,
        agent_id: str | None = None,
        agent_name: str | None = None,
        depth: int | None = None,
        invocation_id: str | None = None,
        explicit_agent_id: bool = False,
        explicit_invocation_id: bool = False,
    ) -> None:
        """Append a ``Message`` with the current sub-agent context auto-stamped.

        ``explicit_*`` flags let callers override the auto-stamped values
        without losing the active scope; ``add_message`` uses them so an
        explicit ``agent_id`` from the tool still wins.
        """
        active = self._active_subagent()
        if active is not None:
            active_invocation, active_agent_id, _active_agent_name = active
        else:
            active_invocation = None
            active_agent_id = None
        resolved_invocation = (
            invocation_id if explicit_invocation_id else (invocation_id or active_invocation)
        )
        resolved_agent_id = (
            agent_id if explicit_agent_id else (agent_id or active_agent_id)
        )
        resolved_depth = depth if depth is not None else self._current_depth.get()
        self._append_message(
            Message(
                process_type,
                content,
                tool_name=tool_name,
                tool_arguments=tool_arguments,
                agent_id=resolved_agent_id,
                agent_name=agent_name,
                depth=resolved_depth,
                tool_call_id=tool_call_id,
                invocation_id=resolved_invocation,
            ).to_json()
        )

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
                    self._emit(
                        ProcessType.MODEL_OUTPUT_DEEP_THINKING, think_content)

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
                    self._emit(
                        ProcessType.MODEL_OUTPUT_DEEP_THINKING, accumulated_content)
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
                    self._emit(
                        ProcessType.MODEL_OUTPUT_THINKING, prefix_text)

                # send the content after the matching part as code
                code_text = buffer_text[match_start:]
                if code_text:
                    self._emit(
                        ProcessType.MODEL_OUTPUT_CODE, code_text)

                # switch mode
                self.current_mode = ProcessType.MODEL_OUTPUT_CODE
            else:
                # already in code mode, send the entire buffer content as code
                self._emit(
                    ProcessType.MODEL_OUTPUT_CODE, buffer_text)

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
                self._emit(self.current_mode, accumulated_content)

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
                    self._emit(
                        ProcessType.MODEL_OUTPUT_DEEP_THINKING,
                        think_buffer_text,
                    )
            else:
                # Not in think mode, process as normal content
                if think_buffer_text:
                    self._process_normal_content(think_buffer_text)
            self.think_buffer.clear()

        # Process remaining normal buffer content
        if self.token_buffer:
            buffer_text = ''.join(self.token_buffer)
            self._emit(self.current_mode, buffer_text)
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

    @staticmethod
    def _extract_nl2a_state(content):
        """Extract one strict state event and always remove its private marker."""
        if not isinstance(content, str):
            return None, content

        match = _NL2A_STATE_PATTERN.search(content)
        if match is None:
            return None, content

        visible_content = (content[:match.start()] + content[match.end():]).strip()
        try:
            payload = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            return None, visible_content

        if not isinstance(payload, dict):
            return None, visible_content
        agent_id = payload.get("agent_id")
        if (
            not isinstance(agent_id, int)
            or isinstance(agent_id, bool)
            or agent_id <= 0
        ):
            return None, visible_content
        event = payload.get("event")
        if event in {"agent_draft_created", "agent_generation_completed"}:
            valid = set(payload) == {"event", "agent_id"}
        elif event == "agent_draft_fields_saved":
            updated_fields = payload.get("updated_fields")
            valid = (
                set(payload) == {"event", "agent_id", "updated_fields"}
                and isinstance(updated_fields, list)
                and bool(updated_fields)
                and all(
                    isinstance(field_name, str)
                    and field_name in _NL2AGENT_DRAFT_SYNC_FIELDS
                    for field_name in updated_fields
                )
                and len(updated_fields) == len(set(updated_fields))
            )
        elif event == "prompt_generation_failed":
            failed_fields = payload.get("failed_fields")
            valid = (
                set(payload) == {"event", "agent_id", "failed_fields"}
                and isinstance(failed_fields, list)
                and bool(failed_fields)
                and all(
                    isinstance(field_name, str)
                    and field_name
                    in {
                        "duty_prompt",
                        "constraint_prompt",
                        "few_shots_prompt",
                        "greeting_message",
                        "example_questions",
                    }
                    for field_name in failed_fields
                )
                and len(failed_fields) == len(set(failed_fields))
            )
        else:
            valid = False
        if not valid:
            return None, visible_content
        return json.dumps(payload, ensure_ascii=False), visible_content

    def add_message(self, agent_name, process_type, content, **kwargs):
        """add message to the queue"""
        transformer = self.transformers.get(
            process_type, self.transformers[ProcessType.OTHER])
        formatted_content = transformer.transform(
            content=content, lang=self.lang, agent_name=agent_name, **kwargs)
        nl2a_content = None
        nl2a_state_content = None

        if (
            self.enable_nl2a_wrapper
            and process_type == ProcessType.EXECUTION_LOGS
        ):
            nl2a_state_content, formatted_content = self._extract_nl2a_state(
                formatted_content
            )
            nl2a_content, formatted_content = self._extract_nl2a_wrapper(
                formatted_content
            )

        tool_name = kwargs.get("tool_name")
        tool_arguments = kwargs.get("tool_arguments")
        tool_call_id = kwargs.get("tool_call_id") or self._tool_call_id.get()
        explicit_agent_id = "agent_id" in kwargs
        active = self._active_subagent()
        active_invocation_id = active[0] if active is not None else None

        if nl2a_state_content is not None:
            state_key = nl2a_state_content
            state_event = json.loads(nl2a_state_content).get("event")
            should_emit_state = state_event == "agent_draft_fields_saved"
            if not should_emit_state:
                with self._nl2a_state_lock:
                    should_emit_state = state_key not in self._nl2a_state_events
                    if should_emit_state:
                        self._nl2a_state_events.add(state_key)
            if should_emit_state:
                self._append_message(
                    Message(
                        ProcessType.NL2A_STATE,
                        nl2a_state_content,
                        agent_id=active[1] if active is not None else None,
                        agent_name=agent_name,
                        depth=self._current_depth.get(),
                        invocation_id=active_invocation_id,
                    ).to_json()
                )

        # NL2A side-channel units are emitted alongside execution logs. Preserve
        # the active invocation identity so parallel sub-agent output remains
        # attributable to the same nested card.
        if nl2a_content is not None:
            self._append_message(
                Message(
                    ProcessType.NL2A,
                    nl2a_content,
                    agent_id=active[1] if active is not None else None,
                    agent_name=agent_name,
                    depth=self._current_depth.get(),
                    invocation_id=active_invocation_id,
                ).to_json()
            )

        # explicit_agent_id=True preserves backward compatibility: when callers
        # pass agent_id explicitly it always wins over the active sub-agent scope.
        self._emit(
            process_type,
            formatted_content,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            tool_call_id=tool_call_id,
            agent_id=kwargs.get("agent_id"),
            agent_name=kwargs.get("agent_name"),
            explicit_agent_id=explicit_agent_id,
        )

    @contextmanager
    def tool_call_context(self, tool_call_id: str):
        """Associate observer output with one executing tool invocation."""
        token = self._tool_call_id.set(tool_call_id)
        try:
            yield
        finally:
            self._tool_call_id.reset(token)

    def add_subagent_start(self, agent_id, agent_name, task=None,
                           invocation_id=None):
        """Emit a subagent_start boundary and push the nesting depth.

        A unique ``invocation_id`` is generated (or used when supplied) so that
        downstream consumers can group every chunk produced while this sub-agent
        is running, even when multiple sub-agents execute in parallel.

        The chunk's ``content`` is a JSON blob so the downstream persistence
        layer (which only stores ``content`` for each unit) keeps enough
        information to reconstruct the sub-agent card on history replay.

        Args:
            agent_id: Stable identifier of the sub-agent.
            agent_name: Display name surfaced on the frontend sub-agent card.
            task: Optional task text forwarded from the parent's call (e.g.
                ``task="search the weather"``).
            invocation_id: Optional caller-supplied identifier. When ``None``
                a UUID4 string is generated.
        """
        depth = self._current_depth.get() + 1
        self._current_depth.set(depth)
        if not invocation_id:
            invocation_id = uuid.uuid4().hex
        stack = self._subagent_stack.get()
        self._subagent_stack.set(stack + ((invocation_id, agent_id, agent_name),))
        self._current_invocation_id.set(invocation_id)
        payload = json.dumps(
            {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "task": task if task is not None else "",
                "invocation_id": invocation_id,
            },
            ensure_ascii=False,
        )
        self._append_message(
            Message(
                ProcessType.SUBAGENT_START,
                payload,
                agent_id=agent_id,
                agent_name=agent_name,
                depth=depth,
                invocation_id=invocation_id,
            ).to_json()
        )

    def add_subagent_end(self, agent_id, agent_name, invocation_id=None):
        """Emit a subagent_end boundary and pop the nesting depth.

        When ``invocation_id`` is supplied it is used to pop the matching entry
        from the sub-agent stack. Falls back to popping by ``agent_id`` for
        backward compatibility when the caller doesn't track the id.

        Depth is clamped at 0 to stay resilient against unbalanced starts/ends
        from upstream tooling.
        """
        depth = self._current_depth.get()
        stack = self._subagent_stack.get()
        new_stack = stack
        resolved_invocation = invocation_id
        if stack:
            top_invocation, _top_agent_id, _top_agent_name = stack[-1]
            if invocation_id and invocation_id != top_invocation:
                # Find the matching nested entry by invocation_id first
                for entry in reversed(stack):
                    if entry[0] == invocation_id:
                        resolved_invocation = entry[0]
                        break
            elif not invocation_id:
                # No explicit id supplied: pop the most recent match by agent_id
                for entry in reversed(stack):
                    if entry[1] == agent_id:
                        resolved_invocation = entry[0]
                        break
            new_stack = tuple(
                entry for entry in stack if entry[0] != resolved_invocation
            ) if resolved_invocation else stack[:-1]
        self._subagent_stack.set(new_stack)
        # Update invocation id to the new top (or None)
        self._current_invocation_id.set(new_stack[-1][0] if new_stack else None)
        payload = json.dumps(
            {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "invocation_id": resolved_invocation,
            },
            ensure_ascii=False,
        )
        self._append_message(
            Message(
                ProcessType.SUBAGENT_END,
                payload,
                agent_id=agent_id,
                agent_name=agent_name,
                depth=max(depth, 1),
                invocation_id=resolved_invocation,
            ).to_json()
        )
        self._current_depth.set(max(0, depth - 1))

    def add_model_reasoning_content(self, reasoning_content):
        """
        Handle reasoning content from the model with type MODEL_OUTPUT_DEEP_THINKING
        """
        if reasoning_content:
            self._emit(
                ProcessType.MODEL_OUTPUT_DEEP_THINKING, reasoning_content)

    def get_cached_message(self):
        with self._message_query_lock:
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
                 depth: int = 0, tool_call_id: str | None = None,
                 invocation_id: str | None = None):
        self.message_type = message_type
        self.content = content
        self.tool_name = tool_name
        self.tool_arguments = tool_arguments
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.depth = depth
        self.tool_call_id = tool_call_id
        self.invocation_id = invocation_id

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
        if self.invocation_id is not None:
            result["invocation_id"] = self.invocation_id
        return json.dumps(result, ensure_ascii=False)
