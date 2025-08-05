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
            ProcessType.TOOL: default_transformer
        }

    def add_model_new_token(self, new_token):
        """
        get the streaming output of the model, use the double-ended queue to analyze and classify tokens in real time
        """

        # add the new token to the buffer
        self.token_buffer.append(new_token)

        # concatenate the buffer into text for checking
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
            max_buffer_size = 10  # set the maximum buffer size, can be adjusted according to needs
            while len(self.token_buffer) > max_buffer_size:
                oldest_token = self.token_buffer.popleft()
                self.message_query.append(
                    Message(self.current_mode, oldest_token).to_json())

    def flush_remaining_tokens(self):
        """
        send the remaining tokens in the double-ended queue
        """
        if not self.token_buffer:
            return

        # concatenate the buffer into text
        buffer_text = ''.join(self.token_buffer)
        self.message_query.append(
            Message(self.current_mode, buffer_text).to_json())

        # clear the buffer
        self.token_buffer.clear()

    def add_message(self, agent_name, process_type, content, **kwargs):
        """add message to the queue"""
        transformer = self.transformers.get(
            process_type, self.transformers[ProcessType.OTHER])
        formatted_content = transformer.transform(
            content=content, lang=self.lang, agent_name=agent_name, **kwargs)
        self.message_query.append(
            Message(process_type, formatted_content).to_json())

    def get_cached_message(self):
        cached_message = self.message_query
        self.message_query = []
        return cached_message


# fixed MessageObserver output format
class Message:
    def __init__(self, message_type: ProcessType, content):
        self.message_type = message_type
        self.content = content

    # generate json format and convert to string
    def to_json(self):
        return json.dumps({"type": self.message_type.value, "content": self.content}, ensure_ascii=False)
