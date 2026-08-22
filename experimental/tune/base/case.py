#!/usr/bin/python3.10
# coding: utf-8
# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved

from typing import List, Dict, Optional, Any, Callable

from pydantic import BaseModel, field_validator, Field, FieldValidationInfo

from experimental.tune.common.exception import ParamCheckFailedException
from experimental.tune.base.exception import CaseValidationException
from experimental.tune.base.constant import TuneConstant


class Case(BaseModel):
    """Definition of prompt optimization user case"""
    messages: List[Dict] = Field(default=[])
    tools: Optional[List[Dict]] = Field(default=None)

    @field_validator("messages")
    @classmethod
    def check_message_list_content(cls, value: List[Dict], info: FieldValidationInfo) -> List[Dict]:
        """check message list content is valid"""
        if not isinstance(value, list):
            raise ParamCheckFailedException(f"input value field name {info.field_name} check failed! "
                                            f"value type not correct, expected list")

        if not value:
            raise ParamCheckFailedException(f"input value field name {info.field_name} check failed! "
                                            f"value is empty")
        if value[-1].get(TuneConstant.MESSAGE_ROLE_KEY) != TuneConstant.ASSISTANT_ROLE:
            raise ParamCheckFailedException(f"the last message role should be {TuneConstant.ASSISTANT_ROLE}")
        return value


class CaseInfo(BaseModel):
    """Definition of case information"""
    role: str
    name: str
    content: str
    tools: Any
    tool_calls: Any
    variable: Any


class CaseManager:
    """Definition of case manager"""
    VALID_ROLES_SET = {
        TuneConstant.USER_ROLE,
        TuneConstant.SYSTEM_ROLE,
        TuneConstant.ASSISTANT_ROLE,
        TuneConstant.TOOL_ROLE
    }

    @staticmethod
    def validate_with_convert(data: List[Dict[str, Any]],
                              convertor: Optional[Callable] = None,
                              default_tools: Optional[List[Dict]] = None) -> List:
        """validate and convert cases to optimizer acceptable input"""
        optimizer_input = []
        if not data:
            raise CaseValidationException(f"input data is empty", TuneConstant.ROOT_CASE_INDEX)

        if len(data) > TuneConstant.DEFAULT_MAX_CASE_NUM:
            raise CaseValidationException(
                f"The number of input cases should be less than {TuneConstant.DEFAULT_MAX_CASE_NUM}",
                TuneConstant.DEFAULT_MAX_CASE_NUM
            )

        if not isinstance(data, list) or not isinstance(data[0], dict):
            raise CaseValidationException("Input type is not json-list", TuneConstant.ROOT_CASE_INDEX)

        for case_idx, case in enumerate(data):
            messages = CaseManager._get_case_value_with_check(case, TuneConstant.MESSAGE_KEY, case_idx)
            if not isinstance(messages, list):
                raise CaseValidationException("Input type is not json-list", TuneConstant.ROOT_CASE_INDEX)
            tools = case.get(TuneConstant.TOOL_ROLE, None) or default_tools
            role = ""
            for msg_idx, msg in enumerate(messages):
                if not isinstance(msg, dict):
                    raise CaseValidationException("Message in 'messages' is not json-dict",
                                                  TuneConstant.ROOT_CASE_INDEX)
                role = CaseManager._get_case_value_with_check(msg, TuneConstant.MESSAGE_ROLE_KEY, case_idx)
                if role not in CaseManager.VALID_ROLES_SET:
                    raise CaseValidationException(f"Invalid role type '{role}' in case-{case_idx}", case_idx)
                content = CaseManager._get_case_value_with_check(msg, TuneConstant.MESSAGE_CONTENT_KEY, msg_idx)
                tool_calls = msg.get(TuneConstant.MESSAGE_TOOL_CALLS_KEY, [])
                if not tool_calls and not content.strip():
                    raise CaseValidationException(f"Empty message content in case-{case_idx}", case_idx)

                tool_name = msg.get(TuneConstant.NAME_KEY, "")
                variable = msg.get(TuneConstant.VARIABLE_KEY, dict())
                if convertor:
                    convertor(optimizer_input, case_idx, msg_idx == (len(messages) - 1),
                              CaseInfo(role=role, tools=tools, content=content,
                                       name=tool_name, tool_calls=tool_calls, variable=variable))

            if role != TuneConstant.ASSISTANT_ROLE:
                raise CaseValidationException(
                    f"The last message role should be {TuneConstant.ASSISTANT_ROLE} in case-{case_idx}", case_idx
                )
        return optimizer_input

    @staticmethod
    def default_convertor(cases: List, idx: int, is_last: bool, info: CaseInfo) -> None:
        """default optimizer input convertor"""
        if len(cases) <= idx:
            cases.append(dict(
                question="",
                label="",
                tools=info.tools,
                variable=dict()
            ))
        case = cases[-1]
        if info.variable:
            case[TuneConstant.VARIABLE_KEY] = info.variable
        if info.role == TuneConstant.ASSISTANT_ROLE:
            content = str(info.tool_calls) if info.tool_calls else info.content
            if is_last:
                if not case.get(TuneConstant.QUESTION_KEY, ""):
                    raise CaseValidationException(f"case-{idx} is not a question-label pair", idx)
                case[TuneConstant.LABEL_KEY] = content
            else:
                case[TuneConstant.QUESTION_KEY] = f"{info.role}: {content}\n"
        elif info.role == TuneConstant.TOOL_ROLE:
            content = f"{info.role}: name={info.name}, content={info.content}\n"
            case[TuneConstant.QUESTION_KEY] += content
        else:
            content = str(info.tool_calls) if info.tool_calls else info.content
            case[TuneConstant.QUESTION_KEY] += f"{info.role}: {content}\n"

    @staticmethod
    def _get_case_value_with_check(data: Dict[str, Any], key: str, index: int) -> Any:
        """get case value with existence check"""
        value = data.get(key, None)
        if value is None:
            raise CaseValidationException(f"{key} is not in \"case={index}\"", index)
        return value