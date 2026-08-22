# -*- coding: utf-8 -*-

"""
prompt optimization utils
"""

from typing import List, Dict, Optional, Any, Union
from datetime import datetime, timezone, timedelta

from pydantic import BaseModel, Field, FieldValidationInfo, field_validator
import yaml

from experimental.tune.common.exception import JiuWenBaseException, StatusCode
from experimental.tune.base.case import Case
from experimental.tune.base.constant import TuneConstant
from experimental.tune.common.singleton import Singleton


class TaskInfo(BaseModel):
    """prompt optimization input task info"""
    task_id: str = Field(...)
    task_name: str = Field(default="optimization task")
    task_description: str = Field(default="")
    create_time: str = Field(default=datetime.now(tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"))


class OptimizeInfo(BaseModel):
    """definition of prompt optimization info"""
    cases: List[Case] = Field(default=[])
    num_iterations: int = Field(default=TuneConstant.DEFAULT_ITERATION_NUM)
    num_parallel: int = Field(default=TuneConstant.DEFAULT_LLM_PARALLEL_DEGREE,
                              ge=TuneConstant.MIN_LLM_PARALLEL_DEGREE, le=TuneConstant.MAX_LLM_PARALLEL_DEGREE)
    num_examples: int = Field(default=TuneConstant.DEFAULT_EXAMPLE_NUM,
                              ge=TuneConstant.MIN_EXAMPLE_NUM, le=TuneConstant.MAX_EXAMPLE_NUM)
    num_cot_examples: int = Field(default=TuneConstant.DEFAULT_COT_EXAMPLE_NUM,
                                  ge=TuneConstant.MIN_COT_EXAMPLE_NUM, le=TuneConstant.MAX_COT_EXAMPLE_NUM)
    num_retires: int = Field(default=TuneConstant.DEFAULT_LLM_CALL_RETRY_NUM,
                             ge=TuneConstant.MIN_LLM_CALL_RETRY_NUM, le=TuneConstant.MAX_LLM_CALL_RETRY_NUM)
    optimize_method: str = Field(default=TuneConstant.OPTIMIZATION_METHOD_JOINT)
    placeholder: Optional[List] = Field(default=[])
    evaluation_method: str = Field(default=TuneConstant.DEFAULT_EVALUATION_METHOD)
    tools: Union[List[Dict[str, Any]], Any] = Field(default=[])
    user_compare_rules: str = Field(default="None")


class JointParameters(BaseModel):
    """Joint optimization parameters"""
    num_examples: int = Field(default=TuneConstant.DEFAULT_EXAMPLE_NUM)
    num_cot_examples: int = Field(default=TuneConstant.DEFAULT_COT_EXAMPLE_NUM)
    base_instructions: str = Field(default="")
    filled_instructions: str = Field(default="")
    full_prompt: str = Field(default="")
    answer_format: str = Field(default="")
    task_description: str = Field(default="")
    num_iterations: int = Field(default=TuneConstant.DEFAULT_ITERATION_NUM)
    opt_placeholder_names: List[str] = Field(default=[])
    placeholders: List = Field(default=[])
    original_placeholders: List = Field(default=[])
    examples: List = Field(default=[])
    cot_examples: List = Field(default=[])


class History(BaseModel):
    """optimization history for every round"""
    optimized_prompt: str = Field(default="")
    original_placeholder: Dict[str, str] = Field(default={})
    optimized_placeholder: Dict[str, str] = Field(default={})
    examples: List[str] = Field(default=[])
    filled_prompt: str = Field(default="")
    success_rate: float = Field(default=0.0)
    iteration_round: int = Field(default=0)


class BaseModelInfo(BaseModel):
    api_key: Optional[str] = Field(default="", alias="api_key")
    api_base: Optional[str] = Field(default="", alias="api_base")
    model_name: str = Field(default="", alias="model")
    temperature: float = Field(default=0.95)
    top_p: float = Field(default=0.1)
    streaming: bool = Field(default=False, alias="stream")
    timeout: float = Field(default=60.0)

    @field_validator('model_name', mode='before')
    @classmethod
    def handle_model_name(cls, v, values):
        if not v and 'model' in values.data:
            return values.data['model']
        return v

    class Config:
        populate_by_name = True
        extra = "forbid"

class Response(BaseModel):
    content: str = ""


class BaseChatModel:
    def invoke(self, messages: List[Any]):
        return Response(content="")


class ModelFactory(metaclass=Singleton):
    def get_model(self, model_provider: str, model_info: BaseModelInfo) -> BaseChatModel:
        return BaseChatModel()


class LLMModelInfo(BaseModel):
    """LLM model config info"""
    url: str = Field(default="", min_length=0, max_length=256)
    model: str = Field(default="", min_length=0, max_length=256)
    type: str = Field(default="", min_length=0, max_length=256)
    headers: Optional[Dict] = Field(default={})
    model_source: str = Field(default="", min_length=0, max_length=256)
    api_key: str = Field(default="", min_length=0, max_length=256)


class LLMModelProcess:
    """LLM invoke process"""
    def __init__(self, llm_model_info: LLMModelInfo):
        if llm_model_info.headers is None:
            raise JiuWenBaseException(
                error_code=StatusCode.LLM_CONFIG_MISS_ERROR.code,
                message=StatusCode.LLM_CONFIG_MISS_ERROR.errmsg.format(
                    error_msg="prompt optimization llm config is missing"
                )
            )
        if not llm_model_info.model_source or not llm_model_info.model:
            raise JiuWenBaseException(
                error_code=StatusCode.LLM_CONFIG_MISS_ERROR.code,
                message=StatusCode.LLM_CONFIG_MISS_ERROR.errmsg.format(
                    error_msg="prompt optimization llm config is missing"
                )
            )
        model_info = BaseModelInfo(
            api_key=llm_model_info.api_key,
            api_base=llm_model_info.url,
            model=llm_model_info.model,
            temperature=0.0,
            top_p=0.0
        )
        self.chat_llm = ModelFactory().get_model(llm_model_info.model_source, model_info)

    def chat(self, messages: List[Any]) -> Dict:
        """chat"""
        reply_message = self.chat_llm.invoke(messages)
        return dict(content=reply_message.content)


def load_yaml_to_dict(file_path: str) -> Dict:
    """load yaml file"""
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            yaml_content = f.read()
            parsed_dict = yaml.safe_load(yaml_content)
        except Exception as e:
            raise JiuWenBaseException(
                error_code=StatusCode.LLM_CONFIG_MISS_ERROR.code,
                message=StatusCode.LLM_CONFIG_MISS_ERROR.errmsg
            )
    return parsed_dict

def calculate_runtime(start_time: str) -> int:
    """calculate task runtime"""
    if not start_time:
        raise JiuWenBaseException(
            error_code=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.code,
            message=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.errmsg.format(
                error_msg="invalid start time"
            )
        )
    try:
        start_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        cur_time = datetime.now(tz=timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        cur_time = datetime.strptime(cur_time, "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        raise JiuWenBaseException(
            error_code=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.code,
            message=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.errmsg.format(
                error_msg="invalid time format"
            )
        ) from e
    return int((cur_time - start_time).total_seconds())


def placeholder_to_dict(placeholder_list: List, select_all: bool = False) -> Dict:
    """convert placeholder list to dict"""
    if not placeholder_list:
        return {}

    placeholder_dict = {}
    for placeholder in placeholder_list:
        if select_all or placeholder.get("need_optimize"):
            placeholder_dict[placeholder["name"]] = placeholder["content"]
    return placeholder_dict


def examples_to_string_list(example_list: List) -> List[str]:
    """convert example list to string list"""
    if not example_list:
        return []
    example_string_format = (f"[query]: {TuneConstant.QUESTION_KEY}\n"
                             f"[assistant answer]: {TuneConstant.LABEL_KEY}")
    example_string_list = []
    for example in example_list:
        example_string_list.append(example_string_format.format(
            question=example.get(TuneConstant.QUESTION_KEY, ""),
            label=example.get(TuneConstant.LABEL_KEY, "")
        ))
    return example_string_list

def get_example_question(example):
    """get example question"""
    content = example.get(TuneConstant.QUESTION_KEY, "")
    if TuneConstant.RAW_PROMPT_TAG in content:
        return str(example.get(TuneConstant.VARIABLE_KEY, ""))
    return content