import json
import re  # 新增导入
from collections import deque  # 导入双端队列
from enum import Enum
from typing import Any


class ProcessType(Enum):
    MODEL_OUTPUT_THINKING = "model_output_thinking"  # 模型流式输出，思考内容
    MODEL_OUTPUT_CODE = "model_output_code"  # 模型流式输出，代码内容

    STEP_COUNT = "step_count"  # 当前处于agent的哪一步
    PARSE = "parse"  # 代码解析结果
    EXECUTION_LOGS = "execution_logs"  # 代码执行结果
    AGENT_NEW_RUN = "agent_new_run"  # Agent基本信息打印
    AGENT_FINISH = "agent_finish"  # 子agent结束运行标记，主要用于前端展示
    FINAL_ANSWER = "final_answer"  # 最终总结字样
    ERROR = "error"  # 异常字段
    OTHER = "other"  # 临时的其他字段
    TOKEN_COUNT = "token_count"  # 记录每一个step使用的token数

    SEARCH_CONTENT = "search_content"  # 工具中的搜索内容
    PICTURE_WEB = "picture_web"  # 记录联网搜索后的图片

    CARD = "card"  # 需要前端用卡片渲染的内容
    TOOL = "tool"  # 工具名称


# 消息转换器基类
class MessageTransformer:
    def transform(self, **kwargs: Any) -> str:
        """将内容转换为特定格式"""
        raise NotImplementedError("子类必须实现transform方法")


# 具体转换器实现类
class DefaultTransformer(MessageTransformer):
    def transform(self, **kwargs: Any) -> str:
        """返回任意消息，不做处理"""
        content = kwargs.get("content", "")
        return content


class StepCountTransformer(MessageTransformer):
    # 步骤模板
    TEMPLATES = {"zh": "\n**步骤 {0}** \n", "en": "\n**Step {0}** \n"}

    def transform(self, **kwargs: Any) -> str:
        """转换步骤计数的消息"""
        content = kwargs.get("content", "")
        lang = kwargs.get("lang", "en")

        template = self.TEMPLATES.get(lang, self.TEMPLATES["en"])
        return template.format(content)


class ParseTransformer(MessageTransformer):
    # 解析模板
    TEMPLATES = {"zh": "\n🛠️ 使用Python解释器执行代码\n",
                 "en": "\n🛠️ Used tool python_interpreter\n"}

    def transform(self, **kwargs: Any) -> str:
        """转换解析结果的消息"""
        content = kwargs.get("content", "")
        lang = kwargs.get("lang", "en")

        template = self.TEMPLATES.get(lang, self.TEMPLATES["en"])
        return template + f"```python\n{content}\n```\n"


class ExecutionLogsTransformer(MessageTransformer):
    # 执行日志模板
    TEMPLATES = {"zh": "\n📝 执行结果\n", "en": "\n📝 Execution Logs\n"}

    def transform(self, **kwargs: Any) -> str:
        """转换执行日志的消息"""
        content = kwargs.get("content", "")
        lang = kwargs.get("lang", "en")

        template = self.TEMPLATES.get(lang, self.TEMPLATES["en"])
        return template + f"```bash\n{content}\n```\n"


class FinalAnswerTransformer(MessageTransformer):
    def transform(self, **kwargs: Any) -> str:
        """转换最终答案的消息"""
        content = kwargs.get("content", "")

        return f"\n{content}"


class TokenCountTransformer(MessageTransformer):
    TEMPLATES = {"zh": "步骤耗时：{0}", "en": "Duration:{0}"}

    def transform(self, **kwargs: Any) -> str:
        """转换最终答案的消息"""
        content = kwargs.get("content", "")
        lang = kwargs.get("lang", "en")

        template = self.TEMPLATES.get(lang, self.TEMPLATES["en"])
        return f"""<span style="color: #bbbbc2; font-size: 12px;">{template.format(content)}</span> """


class ErrorTransformer(MessageTransformer):
    # 错误模板
    TEMPLATES = {"zh": "\n💥 运行出错\n{0}\n", "en": "\n💥 Error\n{0}\n"}

    def transform(self, **kwargs: Any) -> str:
        """转换错误消息"""
        content = kwargs.get("content", "")
        lang = kwargs.get("lang", "en")

        template = self.TEMPLATES.get(lang, self.TEMPLATES["en"])
        return template.format(content)


class MessageObserver:
    def __init__(self, lang="zh"):
        # 统一输出给前端的字符串，改为队列
        self.message_query = []

        # 控制输出语言
        self.lang = lang

        # 初始化消息转换器
        self._init_message_transformers()

        # 双端队列用于存储和分析最近的tokens
        self.token_buffer = deque()

        # 当前输出模式：默认为思考模式
        self.current_mode = ProcessType.MODEL_OUTPUT_THINKING

        # 代码块标记模式
        self.code_pattern = re.compile(r"```")

    def _init_message_transformers(self):
        """初始化消息类型到转换器的映射"""
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
        获取模型的流式输出，使用双端队列实时分析和分类token
        """

        # 将新token添加到缓冲区
        self.token_buffer.append(new_token)

        # 将缓冲区拼接成文本进行检查
        buffer_text = ''.join(self.token_buffer)

        # 查找代码块标记
        match = self.code_pattern.search(buffer_text)

        if match:
            # 找到了代码块标记
            match_start = match.start()

            # 只有在思考模式下才进行模式切换
            if self.current_mode == ProcessType.MODEL_OUTPUT_THINKING:
                # 将匹配位置之前的内容作为思考发送
                prefix_text = buffer_text[:match_start]
                if prefix_text:
                    self.message_query.append(
                        Message(ProcessType.MODEL_OUTPUT_THINKING, prefix_text).to_json())

                # 将匹配部分及之后的内容作为代码发送
                code_text = buffer_text[match_start:]
                if code_text:
                    self.message_query.append(
                        Message(ProcessType.MODEL_OUTPUT_CODE, code_text).to_json())

                # 切换模式
                self.current_mode = ProcessType.MODEL_OUTPUT_CODE
            else:
                # 已经在代码模式下，直接发送整个缓冲区内容作为代码
                self.message_query.append(
                    Message(ProcessType.MODEL_OUTPUT_CODE, buffer_text).to_json())

            # 清空缓冲区
            self.token_buffer.clear()
        else:
            # 未找到代码块标记，从队首取出并发送一个token（如果缓冲区长度超过一定大小）
            max_buffer_size = 10  # 设置最大缓冲区大小，可以根据需要调整
            while len(self.token_buffer) > max_buffer_size:
                oldest_token = self.token_buffer.popleft()
                self.message_query.append(
                    Message(self.current_mode, oldest_token).to_json())

    def flush_remaining_tokens(self):
        """
        将双端队列中剩余的token发送出去
        """
        if not self.token_buffer:
            return

        # 将缓冲区拼接成文本
        buffer_text = ''.join(self.token_buffer)
        self.message_query.append(
            Message(self.current_mode, buffer_text).to_json())

        # 清空缓冲区
        self.token_buffer.clear()

    def add_message(self, agent_name, process_type, content, **kwargs):
        """添加消息到队列"""
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


# 固定MessageObserver的输出格式
class Message:
    def __init__(self, message_type: ProcessType, content):
        self.message_type = message_type
        self.content = content

    # 生成json格式，并转成字符串
    def to_json(self):
        return json.dumps({"type": self.message_type.value, "content": self.content}, ensure_ascii=False)
