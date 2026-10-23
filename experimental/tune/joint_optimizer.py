# -*- coding: utf-8 -*-

"""
prompt optimization evaluators
"""

import re
import random
import threading
import copy
from os.path import dirname, join
from dataclasses import dataclass
from typing import List, Optional, Tuple

from logging import getLogger
logger = getLogger(__name__)
from experimental.tune.common.exception import JiuWenBaseException, StatusCode
from experimental.tune.base.exception import OnStopException
from experimental.tune.base.constant import TuneConstant, TaskStatus
from experimental.tune.base.utils import (LLMModelProcess, LLMModelInfo, TaskInfo, load_yaml_to_dict, JointParameters,
                             placeholder_to_dict, calculate_runtime, History, OptimizeInfo, get_example_question)
from experimental.tune.base.context_manager import ContextManager, STOP_EVENT, Context
from experimental.tune.joint_evaluator import JointEvaluatorWithRef
from experimental.tune.base.case import CaseManager

@dataclass
class SpecificMatch:
    QUESTION_KEY = "[query]:"
    ANSWER_KEY = "[assistant answer]:"
    EXAMPLE_DELIMITER_PATTERN = r"(?s)(?<=<INS>)(.*?)(?=</INS>)"

class JointOptimizer:
    def __init__(self):
        self._opt_model = None
        self._infer_model = None
        self.evaluator = None
        self.dataset = None
        self.params = JointParameters()
        self.cur_iteration = 0
        self.best_accuracy = 0.0
        self.sampled_incorrect_data = []
        self.variable = []
        default_opt_prompt_config_path = join(dirname(__file__), "joint_prompt_pool.yaml")
        self.prompt_pool = load_yaml_to_dict(default_opt_prompt_config_path)
        self.instr_optimizer = None

    @staticmethod
    def get_optimize_placeholder(placeholder):
        """return a list of placeholders requiring optimization"""
        try:
            if not placeholder:
                return None
            return [p.get("name") for p in placeholder if p.get("need_optimize")]
        except Exception as e:
            logger.warning(f"get optimize placeholder error: {e}")
            return None

    @staticmethod
    def extract_optimized_prompt_from_response(content) -> Optional[str]:
        """extract optimized prompt from response"""
        optimized_prompt_pattern = r"<PROMPT_OPTIMIZED>(.*?)</PROMPT_OPTIMIZED>"
        match = re.search(optimized_prompt_pattern, content, re.DOTALL)
        if not match:
            return None
        optimized_prompt = match.group(1)
        return optimized_prompt.replace("<prompt_base>", "").replace("</prompt_base>", "")

    @staticmethod
    def extract_optimized_placeholder_from_response(content) -> Optional[List]:
        """extract optimized placeholder from response"""
        optimized_placeholder_pattern = r"<PLACEHOLDER_OPTIMIZED>(.*?)</PLACEHOLDER_OPTIMIZED>"
        match = re.search(optimized_placeholder_pattern, content, re.DOTALL)
        if not match:
            return None
        optimized_placeholder = match.group(1)
        single_placeholder_pattern = re.compile(r"<(.*?)>(.*?)</\1>", re.S)
        matches = single_placeholder_pattern.findall(optimized_placeholder)
        return [{TuneConstant.NAME_KEY: tag.strip(),
                 TuneConstant.MESSAGE_CONTENT_KEY: content.strip()
                 } for tag, content in matches]

    @staticmethod
    def fill_prompt(instruction: str, placeholder: List) -> str:
        if not placeholder:
            return instruction
        for p in placeholder:
            name = p.get(TuneConstant.NAME_KEY)
            content = p.get(TuneConstant.MESSAGE_CONTENT_KEY)
            if name and content:
                instruction = instruction.replace(f"{{{{{name}}}}}", content)
        return instruction

    @staticmethod
    def extract_examples_from_response(content):
        """extract examples from response"""
        optimized_examples = []
        question_pattern = re.compile(
            re.escape(SpecificMatch.QUESTION_KEY) + r"(.*?)" +
            re.escape(SpecificMatch.ANSWER_KEY) + r"(.*)",
            re.DOTALL
        )

        for text in re.findall(SpecificMatch.EXAMPLE_DELIMITER_PATTERN, content):
            match = question_pattern.search(text.strip())
            if match:
                question = match.group(1).strip()
                answer_with_reason = match.group(2).strip()
                optimized_examples.append({TuneConstant.QUESTION_KEY: question,
                                           TuneConstant.LABEL_KEY: answer_with_reason})
        return optimized_examples

    @staticmethod
    def prepare_optimization_template(template, instruction, placeholders, error_cases, reflection, tools):
        """generate a critique prompt"""
        prompt = template.replace("{{PROMPT_META_TEMPLATE}}", instruction)
        prompt = prompt.replace("{{PLACEHOLDER_CONTENTS}}", placeholders)
        prompt = prompt.replace("{{ERROR_CASES}}", error_cases)
        prompt = prompt.replace("{{REFLECTIONS_ON_ERROR_CASES}}", reflection)
        prompt = prompt.replace("{{API_TOOLS_DESCRIPTION}}", tools)
        return prompt

    @staticmethod
    def validate_placeholder(prompt, placeholders):
        """validate the placeholder"""
        placeholders_in_prompt = re.findall(r"\{\{([\w_]+)\}\}", prompt)
        placeholder_names = [item.get("name", "") for item in placeholders]
        for item in placeholders:
            if not item.get("name"):
                raise JiuWenBaseException(
                    error_code=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.code,
                    message=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.errmsg.format(
                        error_msg="Placeholder item 'name' cannot be empty"))
            if not item.get("content"):
                raise JiuWenBaseException(
                    error_code=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.code,
                    message=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.errmsg.format(
                        error_msg="Placeholder item 'content' cannot be empty"))
            if "need_optimize" not in item:
                raise JiuWenBaseException(
                    error_code=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.code,
                    message=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.errmsg.format(
                        error_msg="Placeholder item 'need_optimize' cannot be empty"))

            if not isinstance(item["name"], str):
                raise JiuWenBaseException(
                    error_code=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.code,
                    message=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.errmsg.format(
                        error_msg="Placeholder item 'name' must be a string"))
            if not isinstance(item["content"], str):
                raise JiuWenBaseException(
                    error_code=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.code,
                    message=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.errmsg.format(
                        error_msg="Placeholder item 'content' must be a string"))
            if not isinstance(item["need_optimize"], bool):
                raise JiuWenBaseException(
                    error_code=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.code,
                    message=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.errmsg.format(
                        error_msg="Placeholder item 'need_optimize' must be a boolean"))
        if not all(name in placeholders_in_prompt for name in placeholder_names):
            missing_names = ", ".join([name for name in placeholder_names if name not in placeholders_in_prompt])
            raise JiuWenBaseException(
                error_code=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.code,
                message=StatusCode.PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR.errmsg.format(
                    error_msg=f"Placeholder names {missing_names} not found in prompt"))
        logger.info("Schema validation succeeded.")

    @staticmethod
    def _check_stop_event(context: Context) -> bool:
        """check optimization stop event"""
        task_id = context.get("id", "")
        if context and context.get(STOP_EVENT) and context.get(STOP_EVENT).is_set():
            raise OnStopException(f"Task {task_id} stopped")
        return True

    @staticmethod
    def get_variable_from_dataset(dataset, prompt):
        """get variable from dataset"""
        variable = set()
        for case in dataset:
            vars = case.get(TuneConstant.VARIABLE_KEY, {})
            variable.update(vars)

        reordered_variable = [(prompt.find(f"{{{{{v}}}}}"), v) for v in variable]
        reordered_variable = [v[1] for v in sorted(reordered_variable, key=lambda x: x[0], reverse=False)]
        return reordered_variable

    def chat_completion(self, user_prompt, system_prompt=None, is_assistant=False):
        """generate chat completion"""
        messages = []
        if system_prompt:
            messages.append({TuneConstant.MESSAGE_ROLE_KEY: TuneConstant.SYSTEM_ROLE,
                             TuneConstant.MESSAGE_CONTENT_KEY: system_prompt})
        messages.append({TuneConstant.MESSAGE_ROLE_KEY: TuneConstant.USER_ROLE,
                         TuneConstant.MESSAGE_CONTENT_KEY: user_prompt})
        retries = TuneConstant.DEFAULT_LLM_CALL_RETRY_NUM
        for i in range(retries):
            try:
                response = self._opt_model.chat(messages) if not is_assistant else self._infer_model.chat(messages)
                if not response or response.get(TuneConstant.MESSAGE_CONTENT_KEY) is None:
                    raise JiuWenBaseException(
                        StatusCode.LLM_FALSE_RESULT_ERROR.code,
                        StatusCode.LLM_FALSE_RESULT_ERROR.errmsg.format(
                            error_msh="call llm service get empty response"
                        )
                    )
                return response.get(TuneConstant.MESSAGE_CONTENT_KEY)
            except (JiuWenBaseException, KeyError, AttributeError, TypeError) as e:
                logger.info(f"Inference failed at round {i}/{retries}: {str(e)}")
                if i == retries - 1:
                    raise e
        return None

    def resample_examples(self, sampled_incorrect_data):
        """resampling examples"""
        dataset = copy.deepcopy(self.dataset)
        num_samples = self.params.num_examples + self.params.num_cot_examples
        if len(sampled_incorrect_data) >= num_samples:
            return sampled_incorrect_data
        if len(dataset) <= num_samples:
            return dataset

        num_to_add = num_samples - len(sampled_incorrect_data)
        unique_data = []
        query_set = set()
        for data in sampled_incorrect_data:
            if not self.variable:
                if data.get(TuneConstant.QUESTION_KEY, "") not in query_set:
                    query_set.add(data[TuneConstant.QUESTION_KEY])
                    unique_data.append(data)
                    continue
            if str(data[TuneConstant.VARIABLE_KEY]) in query_set:
                query_set.add(data[TuneConstant.VARIABLE_KEY])
                unique_data.append(data)
        remaining_data = [data for data in dataset if data not in unique_data]
        sampled_new_data = random.sample(remaining_data, num_to_add)
        return sampled_new_data + sampled_incorrect_data

    def evaluate(self, prompt, context: Context):
        """evaluate dataset"""
        try:
            accuracy, sampled_incorrect_data = self.evaluator.evaluate(prompt, self.dataset,
                                                                       context.get(STOP_EVENT))
        except JiuWenBaseException as e:
            raise e
        if not self._check_stop_event(context) or accuracy is None or sampled_incorrect_data is None:
            return None,None
        sampled_data = self.resample_examples(sampled_incorrect_data)
        return accuracy, sampled_data

    def get_task_description(self):
        """get task description"""
        prompt = self.prompt_pool.get("get_task_description").format(
            instruction=self.params.base_instructions
        )
        return self.chat_completion(prompt)

    def get_answer_format(self):
        """get answer format"""
        prompt = self.prompt_pool.get("get_answer_format").format(
            instruction=self.params.base_instructions
        )
        return self.chat_completion(prompt)

    def init_parameters(self, optimize_info: OptimizeInfo, raw_prompt, context: Context):
        """init parameters"""
        self.params.num_iterations = optimize_info.num_iterations
        self.params.num_examples = optimize_info.num_examples
        self.params.num_cot_examples = optimize_info.num_cot_examples
        self.params.placeholders = copy.deepcopy(optimize_info.placeholder)
        self.params.original_placeholders = copy.deepcopy(optimize_info.placeholder)
        self.params.base_instructions = raw_prompt[0]
        self.params.opt_placeholder_names = self.get_optimize_placeholder(self.params.placeholders)
        self.params.filled_instructions = self.fill_prompt(self.params.base_instructions,
                                                           self.params.placeholders)
        self.save_state(context, force_save=True)
        try:
            self.params.task_description = self.get_task_description()
            self.params.answer_format = self.get_answer_format()
        except JiuWenBaseException as e:
            raise e

    def prompt_combine(self, instruction: str, example_string=None, cot_example_string=None):
        """prompt combine"""
        variable_section = "\n".join([f"【{key}】: {{{{{key}}}}}" for key in self.variable])

        prompt_parts = [
            instruction,
            f"\n## 示例\n{example_string}" if example_string else "",
            f"\n## 包含思维链示例\n{cot_example_string}" if cot_example_string else "",
            f"\n{self.params.answer_format.strip()}" if self.params.answer_format else "",
            f"\n\n用户输入:\n{variable_section}" if variable_section else "",
            f"\n Output:"
        ]
        return "".join(prompt_parts)

    def update_placeholder(self, new_placeholders: List, placeholders_to_update: List):
        """update placeholders"""
        if not new_placeholders or not self.params.opt_placeholder_names:
            return
        for update_ph in new_placeholders:
            name = update_ph.get(TuneConstant.NAME_KEY)
            content = update_ph.get(TuneConstant.MESSAGE_CONTENT_KEY)
            if not name or not content or name not in self.params.opt_placeholder_names:
                continue
            for i, base_ph in enumerate(placeholders_to_update):
                if name == base_ph.get(TuneConstant.NAME_KEY):
                    placeholders_to_update[i][TuneConstant.MESSAGE_CONTENT_KEY] = content
                    break

    def optimize_instruction_by_gradient(self, tools: Optional[List]) -> Tuple[Optional[str], Optional[List]]:
        """optimize instruction by text gradient"""
        instruction = self.params.base_instructions

        error_example_string = "".join(
            self.prompt_pool["quest_reason_ans_error"].format(
                question=get_example_question(example),
                answer=example.get(TuneConstant.LABEL_KEY, ""),
                predict=example.get(TuneConstant.PREDICT_KEY, ""),
            ) for example in self.sampled_incorrect_data
        )

        if tools:
            tool_prefix = TuneConstant.DEFAULT_TOOL_CALL_PROMPT_PREFIX.replace(
                "{{APIS_DESCRIPTION}}", str(tools) if tools else "None"
            )
            prompt = tool_prefix + instruction
        else:
            prompt = instruction
        prompt_critique_template = self.prompt_pool["prompt_critique_template"].format(
            instruction=prompt,
            examples=error_example_string
        )
        text_gradient = self.chat_completion(prompt_critique_template)
        if not self.params.placeholders:
            prompt_update_result = self.optimize_instruction_without_placeholder(instruction, error_example_string,
                                                                                 text_gradient, tools)
            placeholder_update_result = None
        else:
            prompt_update_result, placeholder_update_result = self.optimize_instruction_with_placeholder(
                instruction, error_example_string, text_gradient, tools
            )
        return prompt_update_result, placeholder_update_result

    def optimize_instruction_without_placeholder(self, instruction, error_example_string, text_gradient, tools):
        """update instruction"""
        optimize_prompt_template = self.prompt_pool["optimize_prompt_instruction_template"]
        optimize_prompt_template = optimize_prompt_template.replace("{{PROMPT_META_TEMPLATE}}", instruction)
        optimize_prompt_template = optimize_prompt_template.replace("{{ERROR_CASES}}", error_example_string)
        optimize_prompt_template = optimize_prompt_template.replace("{{REFLECTIONS_ON_ERROR_CASES}}", text_gradient)
        optimize_prompt_template = optimize_prompt_template.replace("{{API_TOOLS_DESCRIPTION}}", str(tools) if tools else "None")
        optimized_instruction_response = self.chat_completion(optimize_prompt_template)
        return self.extract_optimized_prompt_from_response(optimized_instruction_response)

    def optimize_instruction_with_placeholder(self, instruction, error_example_string, text_gradient, tools):
        """update instruction with placeholder"""
        # optimize instruction
        placeholder_content = "".join(
            f"<{p.get(TuneConstant.NAME_KEY)}>\n"
            f"{p.get(TuneConstant.MESSAGE_CONTENT_KEY)}\n"
            f"</{p.get(TuneConstant.NAME_KEY)}>\n" for p in self.params.placeholders
        )
        placeholder_content += "".join(
            f"<{v}>\n{{{{{v}}}}}\n</{v}>\n" for v in self.variable
        )
        prompt_critique_template = self.prepare_optimization_template(
            self.prompt_pool["optimize_prompt_instruction_template_with_placeholder"],
            instruction, placeholder_content, error_example_string, text_gradient, str(tools) if tools else "None"
        )
        optimized_instruction_response = self.chat_completion(prompt_critique_template)
        optimized_instruction = self.extract_optimized_prompt_from_response(optimized_instruction_response)

        # optimize placeholder
        opt_placeholder_names = str(self.params.opt_placeholder_names) if self.params.opt_placeholder_names else ""
        optimized_placeholder = copy.deepcopy(self.params.placeholders)
        if not self.params.opt_placeholder_names:
            return optimized_instruction, optimized_placeholder
        fixed_placeholders = [p for p in self.params.placeholders
                              if p.get(TuneConstant.NAME_KEY) not in self.params.opt_placeholder_names]
        need_opt_placeholders = [p for p in self.params.placeholders
                                 if p.get(TuneConstant.NAME_KEY) in self.params.opt_placeholder_names]
        instruction = self.fill_prompt(instruction, fixed_placeholders)
        placeholder_content = "".join(
            f"<{p.get(TuneConstant.NAME_KEY)}>\n"
            f"{p.get(TuneConstant.MESSAGE_CONTENT_KEY)}\n"
            f"</{p.get(TuneConstant.NAME_KEY)}>\n" for p in need_opt_placeholders
        )
        placeholder_critique_template = self.prepare_optimization_template(
            self.prompt_pool["optimize_prompt_placeholder_template"],
            instruction, placeholder_content, error_example_string, text_gradient, str(tools) if tools else "None"
        )
        placeholder_critique_template = placeholder_critique_template.replace(
            "{{PLACEHOLDER_TO_OPTIMIZE}}", opt_placeholder_names
        )
        updated_placeholders_response = self.chat_completion(placeholder_critique_template)
        updated_placeholders = self.extract_optimized_placeholder_from_response(updated_placeholders_response)
        self.update_placeholder(updated_placeholders, optimized_placeholder)
        return optimized_instruction, optimized_placeholder

    def select_best_examples(self, context: Context) -> List:
        """select best examples"""
        if not self._check_stop_event(context) or self.params.num_examples == 0:
            return []

        try:
            error_example_string = "".join(
                self.prompt_pool["quest_reason_ans"].format(
                    question=get_example_question(example),
                    answer=example.get(TuneConstant.LABEL_KEY, ""),
                ) for example in self.sampled_incorrect_data
            )
            gt_example = random.sample(self.dataset, 1)[0]
            gt_example_string = self.prompt_pool["gt_quest_reason_ans"].format(
                question=get_example_question(gt_example),
                answer=gt_example.get(TuneConstant.LABEL_KEY, "")
            )
            examples_select_template = self.prompt_pool["examples_select_template"].format(
                gt_example=gt_example_string,
                task_description=self.params.base_instructions,
                num_examples=self.params.num_examples,
                error_examples=error_example_string
            )
            response = self.chat_completion(examples_select_template)
            return self.extract_examples_from_response(response)

        except (KeyError, TypeError, AttributeError, IndexError) as e:
            logger.warning(f"Error occur while selecting best examples: {e}")
            return []

    def generate_best_reasoning_examples(self, context: Context) -> List:
        """generate best reasoning examples"""
        if not self._check_stop_event(context) or self.params.num_cot_examples == 0:
            return []

        try:
            examples_string = self._get_example_string(self.params.cot_examples)
            error_example_string = "".join(
                self.prompt_pool["quest_reason_ans_error"].format(
                    question=get_example_question(example),
                    answer=example.get(TuneConstant.LABEL_KEY, ""),
                    predict=example.get(TuneConstant.PREDICT_KEY, "")
                ) for example in self.sampled_incorrect_data
            )

            examples_critique_template = self.prompt_pool["error_examples_critique_template"].format(
                examples=examples_string,
                task_description=self.params.filled_instructions,
                num_examples=self.params.num_cot_examples,
                error_examples=error_example_string
            )
            response = self.chat_completion(examples_critique_template)
            examples_optimization_template = self.prompt_pool["examples_optimization_template"].format(
                examples=examples_string,
                critique=response,
                task_description=self.params.filled_instructions,
                num_examples=self.params.num_cot_examples
            )
            response = self.chat_completion(examples_optimization_template)
            return self.extract_examples_from_response(response)
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning(f"Error occur while generating best reasoning examples: {e}")
            return []

    def get_example_reasoning(self, question, answer):
        """get example reason from question and answer"""
        try:
            reasoning_template = self.prompt_pool["get_example_reasoning_template"].format(
                task_descriotion=self.params.task_description,
                instruction=self.params.base_instructions,
                question=question,
                answer=answer
            )
            response = self.chat_completion(reasoning_template)
            return response
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning(f"Error occur while getting example reason from question: {e}")
            return ""

    def evaluate_baseline(self, context: Context) -> History:
        """evaluate baseline"""
        if not self._check_stop_event(context):
            raise JiuWenBaseException(StatusCode.PROMPT_OPTIMIZE_EVALUATE_ERROR.code,
                                      StatusCode.PROMPT_OPTIMIZE_EVALUATE_ERROR.errmsg.format(
                                          error_msg="evaluation baseline stopped"
                                      ))
        prompt = self.fill_prompt(self.params.base_instructions, self.params.placeholders)
        self.best_accuracy, self.sampled_incorrect_data = self.evaluate(prompt, context)
        if self.best_accuracy is None or self.sampled_incorrect_data is None:
            raise JiuWenBaseException(StatusCode.PROMPT_OPTIMIZE_EVALUATE_ERROR.code,
                                      StatusCode.PROMPT_OPTIMIZE_EVALUATE_ERROR.errmsg.format(
                                          error_msg="evaluation baseline failed"
                                      ))
        return History(optimized_prompt=prompt, iteration_round=0, success_rate=self.best_accuracy)

    def sample_example(self, num_examples: int):
        """sample example"""
        dataset = copy.deepcopy(self.dataset)
        error_cases = self.sampled_incorrect_data
        if num_examples >= len(dataset):
            return [{
                TuneConstant.QUESTION_KEY: get_example_question(data),
                TuneConstant.LABEL_KEY: data.get(TuneConstant.LABEL_KEY, "")
            } for data in dataset]

        sampled_examples = []
        if error_cases:
            num_error_examples = min(num_examples, len(error_cases))
            sampled_examples.extend(random.sample(error_cases, num_error_examples))

            if len(sampled_examples) < num_examples:
                num_remaining_examples = num_examples - len(sampled_examples)
                remaining_examples = [ex for ex in dataset if ex not in sampled_examples]
                sampled_examples.extend(random.sample(remaining_examples, num_remaining_examples))
        else:
            sampled_examples.extend(random.sample(dataset, num_examples))

        return [{
            TuneConstant.QUESTION_KEY: get_example_question(data),
            TuneConstant.LABEL_KEY: data.get(TuneConstant.LABEL_KEY, "")
        } for data in sampled_examples]

    def prepare_fewshot_examples(self):
        """prepare fewshot examples"""
        self.params.examples = self.sample_example(self.params.num_examples)
        raw_cot_examples = self.sample_example(self.params.num_cot_examples)
        if not self.params.cot_examples:
            return
        self.params.cot_examples = [
            {**example,
             TuneConstant.LABEL_KEY: self.get_example_reasoning(
                 get_example_question(example), example.get(TuneConstant.LABEL_KEY, "")
             )}
            for example in raw_cot_examples
        ]

    def do_optimize(self,
                    task_info: TaskInfo,
                    raw_templates: List[str],
                    optimize_info: OptimizeInfo,
                    opt_model_info: LLMModelInfo,
                    infer_model_info: LLMModelInfo
                    ):
        """do prompt optimization"""
        original_prompt = raw_templates[0]
        infer_model_info = infer_model_info or opt_model_info
        context = dict(id=task_info.task_id, name=task_info.task_name, desc=task_info.task_description,
                       create_time=task_info.create_time, run_time=0,
                       raw_templates=raw_templates, optimize_info=optimize_info,
                       opt_model_info=opt_model_info, infer_model_info=infer_model_info,
                       error_msg="", stop_event=threading.Event(), status=TaskStatus.TASK_RUNNING,
                       history=[], cur_iteration=0, best_accuracy=0.0)
        ContextManager().set(task_info.task_id, context)
        try:
            self._opt_model = LLMModelProcess(opt_model_info)
            self._infer_model = LLMModelProcess(infer_model_info)
            result_compare_template = self.prompt_pool["result_compare_template"].replace(
                "{user_compare_rules}", optimize_info.user_compare_rules
            )
            self.evaluator = JointEvaluatorWithRef(opt_model_info, infer_model_info,
                                                   optimize_info, result_compare_template)
            self.dataset = CaseManager.validate_with_convert([case.model_dump() for case in optimize_info.cases],
                                                             CaseManager.default_convertor,
                                                             default_tools=optimize_info.tools)
            self.variable = self.get_variable_from_dataset(self.dataset, original_prompt)
            self.validate_placeholder(original_prompt, optimize_info.placeholder)
            self.init_parameters(optimize_info, raw_templates, context)
            baseline_history = self.evaluate_baseline(context)
            for v in self.variable:
                self.params.base_instructions = self.params.base_instructions.replace(f"{{{{{v}}}}}", v)
            self.params.filled_instructions = self.fill_prompt(self.params.base_instructions, optimize_info.placeholder)
            self.prepare_fewshot_examples()
            self.save_state(context, baseline_history)
            self.optimize_prompt_iteratively(context, 0)
        except OnStopException:
            ContextManager().set_context_attr(task_info.task_id, TaskStatus.TASK_STATUS, TaskStatus.TASK_STOPPED)
            logger.info(f"Joint optimization task {task_info.task_id} stopped.")
            return
        except Exception as e:
            context[TaskStatus.TASK_STATUS] = TaskStatus.TASK_FAILED
            context["run_time"] = calculate_runtime(context.get("create_time", ""))
            checkpoint = ContextManager().get_checkpoint(task_info.task_id) or context
            error_reason = str(e) if isinstance(e, JiuWenBaseException) else "other reason"
            checkpoint["error_msg"] = f"Joint optimization task failed, reason: {error_reason}"
            checkpoint["run_time"] = calculate_runtime(context.get("create_time", ""))
            checkpoint[TaskStatus.TASK_STATUS] = TaskStatus.TASK_FAILED
            ContextManager().set_checkpoint(task_info.task_id, checkpoint)

    def continue_optimize(self, task_id: str):
        """continue optimization"""
        context = ContextManager().get_checkpoint(task_id)
        context["id"] = task_id
        ContextManager().set(task_id, context)
        run_time = calculate_runtime(context.get("create_time", ""))
        ContextManager().set_context_attr(task_id, TaskStatus.TASK_STATUS, TaskStatus.TASK_RUNNING)
        ContextManager().set_context_attr(task_id, "run_time", run_time)
        raw_templates: List[str] = context.get("raw_templates", [])
        optimize_info: OptimizeInfo = context.get("optimize_info", None)
        opt_model_info: LLMModelInfo = context.get("opt_model_info", None)
        infer_model_info: LLMModelInfo = context.get("infer_model_info", None)
        is_loaded = self.load_state(context)
        if optimize_info is None or not is_loaded:
            raise JiuWenBaseException(StatusCode.PROMPT_OPTIMIZE_RESTART_TASK_ERROR.code,
                                      StatusCode.PROMPT_OPTIMIZE_RESTART_TASK_ERROR.errmsg.format(
                                          error_msg="load context failed"
                                      ))
        if self.cur_iteration == 0:
            return self.do_optimize(
                TaskInfo(task_id=task_id, task_name=context.get("name"),
                         task_description=context.get("desc", ""), create_time=context.get("create_time", "")),
                raw_templates, optimize_info, opt_model_info, infer_model_info
            )
        try:
            self._opt_model = LLMModelProcess(opt_model_info)
            self._infer_model = LLMModelProcess(infer_model_info)
            result_compare_template = self.prompt_pool["result_compare_template"].replace(
                "{user_compare_rules}", optimize_info.user_compare_rules
            )
            self.evaluator = JointEvaluatorWithRef(opt_model_info, infer_model_info,
                                                   optimize_info, result_compare_template)

            self.dataset = CaseManager.validate_with_convert([case.model_dump() for case in optimize_info.cases],
                                                             CaseManager.default_convertor,
                                                             default_tools=optimize_info.tools)
            self.variable = self.get_variable_from_dataset(self.dataset, raw_templates[0])
            logger.info(f"Prompt optimization task {task_id} restarted.")
            self.optimize_prompt_iteratively(context, self.cur_iteration)
        except OnStopException:
            ContextManager().set_context_attr(task_id, TaskStatus.TASK_STATUS, TaskStatus.TASK_STOPPED)
            logger.info(f"Joint optimization task {task_id} stopped.")
            return
        except Exception as e:
            context[TaskStatus.TASK_STATUS] = TaskStatus.TASK_FAILED
            context["run_time"] = calculate_runtime(context.get("create_time", ""))
            checkpoint = ContextManager().get_checkpoint(task_id) or context
            error_reason = str(e) if isinstance(e, JiuWenBaseException) else "other reason"
            checkpoint["error_msg"] = f"Joint optimization task failed, reason: {error_reason}"
            checkpoint["run_time"] = calculate_runtime(context.get("create_time", ""))
            checkpoint[TaskStatus.TASK_STATUS] = TaskStatus.TASK_FAILED
            ContextManager().set_checkpoint(task_id, checkpoint)

    def load_state(self, context: Context):
        """load task state"""
        if "params" not in context:
            return False
        self.params: JointParameters = context.get("params")
        self.cur_iteration = context.get("cur_iteration", 0)
        self.best_accuracy = context.get("best_accuracy", 0.0)
        self.params.filled_instructions = self.fill_prompt(self.params.base_instructions, self.params.placeholders)
        self.sampled_incorrect_data = context.get("sampled_incorrect_data", [])
        return True

    def save_state(self, context: Context, history: Optional[History] = None, force_save: bool = False):
        """save task state"""
        if not force_save and not self._check_stop_event(context):
            return

        example_string = self._get_example_string(self.params.examples)
        cot_example_string = self._get_example_string(self.params.cot_examples)
        self.params.full_prompt = self.prompt_combine(self.params.filled_instructions,
                                                      example_string, cot_example_string)
        context["cur_iteration"] = self.cur_iteration
        context["params"] = self.params
        context["best_accuracy"] = self.best_accuracy
        context["sampled_incorrect_data"] = self.sampled_incorrect_data
        context["run_time"] = calculate_runtime(context.get("create_time", ""))
        if history:
            original_placeholder = {}
            if self.params.original_placeholders:
                for ph in self.params.original_placeholders:
                    original_placeholder[ph.get(TuneConstant.NAME_KEY)] = ph.get(TuneConstant.MESSAGE_CONTENT_KEY)
            history.original_placeholder = original_placeholder
            context.get("history", []).append(history)
        task_id = context.get("id")
        ContextManager().set_checkpoint(task_id, context)

    def optimize_prompt_iteratively(self, context: Context, begin_iteration: int):
        """optimize prompt iteratively"""
        logger.info("Optimizing prompt instruction and examples iteratively...")
        history = None
        need_optimize_example = self.params.num_examples > 0 or self.params.num_cot_examples > 0
        for iter in range(begin_iteration, self.params.num_iterations):
            self.cur_iteration = iter + 1
            is_optimize_instruction = random.choice([True, False]) if need_optimize_example else True
            logger.info(f"Task-{context.get('id')} at iteration {iter} / {self.params.num_iterations} "
                        f"start optimize {'instruction' if is_optimize_instruction else 'examples'}")
            if is_optimize_instruction:
                history = self._optimize_instruction(context)
            else:
                history = self._optimize_examples(context)

            if iter < self.params.num_iterations - 1:
                self.save_state(context, history)
        context[TaskStatus.TASK_STATUS] = TaskStatus.TASK_FINISHED
        context["run_time"] = calculate_runtime(context.get("create_time", ""))
        self.save_state(context, history)
        logger.info(f"Joint optimization task-{context.get('id')} finished.")

    def _optimize_instruction(self, context: Context) -> Optional[History]:
        """optimize instruction"""
        optimize_info: OptimizeInfo = context.get("optimize_info", None)
        tools = optimize_info.tools
        optimized_instruction, optimized_placeholder = self.optimize_instruction_by_gradient(tools)
        if not optimized_instruction:
            raise JiuWenBaseException(
                StatusCode.PROMPT_OPTIMIZE_REFINE_INSTRUCTION_ERROR.code,
                StatusCode.PROMPT_OPTIMIZE_REFINE_INSTRUCTION_ERROR.errmsg.format(
                    error_msg="optimize instruction failed, get empty result"
                )
            )
        full_prompt = self._get_full_prompt(optimized_instruction, optimized_placeholder)
        accuracy, error_cases = self.evaluate(full_prompt, context)
        if accuracy is None:
            raise JiuWenBaseException(
                StatusCode.PROMPT_OPTIMIZE_REFINE_INSTRUCTION_ERROR.code,
                StatusCode.PROMPT_OPTIMIZE_REFINE_INSTRUCTION_ERROR.errmsg.format(
                    error_msg="failed to get evaluation result"
                )
            )
        if accuracy > self.best_accuracy:
            self.sampled_incorrect_data = error_cases
            self.best_accuracy = accuracy
            self.params.base_instructions = optimized_instruction
            self.update_placeholder(optimized_placeholder, self.params.placeholders)
            self.params.filled_instructions = self.fill_prompt(optimized_instruction, optimized_placeholder)
            self.params.full_prompt = full_prompt
        opt_placeholder_dict = {}
        if optimized_placeholder and self.params.opt_placeholder_names:
            for p in optimized_placeholder:
                placeholder_name = p.get(TuneConstant.NAME_KEY)
                if placeholder_name in self.params.opt_placeholder_names:
                    opt_placeholder_dict[placeholder_name] = p.get(TuneConstant.MESSAGE_CONTENT_KEY, "")
        return History(optimized_prompt=optimized_instruction,
                       optimized_placeholder=opt_placeholder_dict,
                       examples=self._get_examples_string_list(self.params.examples) +
                                self._get_examples_string_list(self.params.cot_examples),
                       filled_prompt=full_prompt,
                       success_rate=accuracy,
                       iteration_round=self.cur_iteration)

    def _optimize_examples(self, context: Context) -> Optional[History]:
        """optimize examples"""
        if self.params.num_examples == 0 and self.params.num_cot_examples == 0:
            return None
        selected_examples = []
        if self.params.num_examples > 0:
            for _ in range(TuneConstant.DEFAULT_LLM_CALL_RETRY_NUM):
                selected_examples = self.select_best_examples(context)
                if selected_examples:
                    break
        cot_examples = self.generate_best_reasoning_examples(context)
        examples_string = self._get_example_string(selected_examples)
        cot_examples_string = self._get_example_string(cot_examples)

        full_prompt = self.prompt_combine(self.params.filled_instructions, examples_string, cot_examples_string)
        accuracy, error_cases = self.evaluate(full_prompt, context)

        if accuracy is None:
            raise JiuWenBaseException(
                StatusCode.PROMPT_OPTIMIZE_REFINE_INSTRUCTION_ERROR.code,
                StatusCode.PROMPT_OPTIMIZE_REFINE_INSTRUCTION_ERROR.errmsg.format(
                    error_msg="failed to get evaluation result"
                )
            )

        if accuracy > self.best_accuracy:
            self.sampled_incorrect_data = error_cases
            self.best_accuracy = accuracy
            self.params.examples = selected_examples or []
            self.params.cot_examples = cot_examples or []
            self.params.full_prompt = full_prompt
        return History(optimized_prompt=self.params.base_instructions,
                       optimized_placeholder=placeholder_to_dict(self.params.placeholders),
                       examples=self._get_examples_string_list(self.params.examples) +
                                self._get_examples_string_list(self.params.cot_examples),
                       filled_prompt=full_prompt,
                       success_rate=accuracy,
                       iteration_round=self.cur_iteration)

    def _get_example_string(self, examples: List):
        """get example string"""
        if not examples:
            return ""
        return "\n".join(self._get_examples_string_list(examples))

    def _get_examples_string_list(self, examples: List) -> List[str]:
        """get example string list"""
        if not examples:
            return []
        example_string_template = self.prompt_pool["quest_reason_ans"]
        example_string_list = []
        for i, example in enumerate(examples):
            formated_example_string = example_string_template.format(
                question=get_example_question(example),
                answer=example.get(TuneConstant.LABEL_KEY, "")
            )
            example_string_list.append(f"示例{i + 1}:\n{formated_example_string}")
        return example_string_list

    def _get_full_prompt(self, instruction, placeholders):
        """get full prompt"""
        filled_instruction = self.fill_prompt(instruction, placeholders)
        example_string = self._get_example_string(self.params.examples)
        cot_example_string = self._get_example_string(self.params.cot_examples)
        full_prompt = self.prompt_combine(filled_instruction, example_string, cot_example_string)
        return full_prompt