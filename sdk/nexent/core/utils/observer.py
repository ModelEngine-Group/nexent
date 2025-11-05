import json
import re
from collections import deque
from enum import Enum
from typing import Any


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

    SEARCH_CONTENT = "search_content"  # search content in tool
    PICTURE_WEB = "picture_web"  # record the image after联网搜索

    CARD = "card"  # content that needs to be rendered by the front end using cards
    TOOL = "tool"  # tool name
    MEMORY_SEARCH = "memory_search"  # memory search status


# message transformer base class
# 将各阶段的消息进行格式化，风格统一
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
    # execution log template
    TEMPLATES = {"zh": "\n📝 执行结果\n", "en": "\n📝 Execution Logs\n"}

    def transform(self, **kwargs: Any) -> str:
        """convert the message of execution log"""
        content = kwargs.get("content", "")
        lang = kwargs.get("lang", "en")

        template = self.TEMPLATES.get(lang, self.TEMPLATES["en"])
        return template + f"```bash\n{content}\n```\n"


class FinalAnswerTransformer(MessageTransformer):
    def transform(self, **kwargs: Any) -> str:
        """convert the message of final answer"""
        content = kwargs.get("content", "")

        return f"{content}"


class TokenCountTransformer(MessageTransformer):
    TEMPLATES = {"zh": "步骤耗时：{0}", "en": "Duration:{0}"}

    def transform(self, **kwargs: Any) -> str:
        """convert the message of token count"""
        content = kwargs.get("content", "")
        lang = kwargs.get("lang", "en")

        template = self.TEMPLATES.get(lang, self.TEMPLATES["en"])
        return f"""<span style="color: #bbbbc2; font-size: 12px;">{template.format(content)}</span> """


class ErrorTransformer(MessageTransformer):
    # error template
    TEMPLATES = {"zh": "\n💥 运行出错： \n{0}\n", "en": "\n💥 Error: \n{0}\n"}

    def transform(self, **kwargs: Any) -> str:
        """convert the message of error"""
        content = kwargs.get("content", "")
        lang = kwargs.get("lang", "en")

        template = self.TEMPLATES.get(lang, self.TEMPLATES["en"])
        return template.format(content)


class MessageObserver:
    # set the maximum buffer size, can be adjusted according to needs
    MAX_TOKEN_BUFFER_SIZE = 10
    
    def __init__(self, lang="zh"):
        # unified output to the front end string, changed to queue
        self.message_query = []

        # control output language
        self.lang = lang

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

    def _init_message_transformers(self):
        """initialize the mapping of message type to transformer"""
        default_transformer = DefaultTransformer()

        self.transformers = {
            ProcessType.AGENT_NEW_RUN: default_transformer,
            ProcessType.STEP_COUNT: StepCountTransformer(),
            ProcessType.PARSE: ParseTransformer(),
            ProcessType.EXECUTION_LOGS: ExecutionLogsTransformer(),
            ProcessType.FINAL_ANSWER: FinalAnswerTransformer(),
            ProcessType.ERROR: ErrorTransformer(),
            ProcessType.OTHER: default_transformer,
            ProcessType.SEARCH_CONTENT: default_transformer,
            ProcessType.TOKEN_COUNT: TokenCountTransformer(),
            ProcessType.PICTURE_WEB: default_transformer,
            ProcessType.AGENT_FINISH: default_transformer,
            ProcessType.CARD: default_transformer,
            ProcessType.TOOL: default_transformer,
            ProcessType.MEMORY_SEARCH: default_transformer
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
                # todo 这块为什么没有从思考的开始索引
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
            think_content = self.think_buffer.popleft()
            # In think mode, output accumulated content as deep thinking
            if self.in_think_mode:
                self.message_query.append(
                    Message(ProcessType.MODEL_OUTPUT_DEEP_THINKING, think_content).to_json())
            else:
                self._process_normal_content(think_content)


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
            # 找到代码块的起始索引
            # 实际输出 = 思考 + 代码块
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
                # 切换当前处理阶段的模式
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
            while len(self.token_buffer) > max_buffer_size:
                oldest_token = self.token_buffer.popleft()
                self.message_query.append(
                    Message(self.current_mode, oldest_token).to_json())

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

    def add_message(self, agent_name, process_type, content, **kwargs):
        """add message to the queue"""
        transformer = self.transformers.get(
            process_type, self.transformers[ProcessType.OTHER])
        formatted_content = transformer.transform(
            content=content, lang=self.lang, agent_name=agent_name, **kwargs)
        self.message_query.append(
            Message(process_type, formatted_content).to_json())

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
    def __init__(self, message_type: ProcessType, content):
        self.message_type = message_type
        self.content = content

    # generate json format and convert to string
    def to_json(self):
        return json.dumps({"type": self.message_type.value, "content": self.content}, ensure_ascii=False)
