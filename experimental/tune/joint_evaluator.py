# -*- coding: utf-8 -*-

"""
prompt optimization evaluators
"""

import re
import json
import threading
import copy
import random
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging import getLogger
logger = getLogger(__name__)

from experimental.tune.base.exception import JiuWenBaseException
from experimental.tune.base.utils import OptimizeInfo, LLMModelProcess, LLMModelInfo
from experimental.tune.base.exception import OnStopException
from experimental.tune.base.constant import TuneConstant


class JointEvaluatorWithRef:
    """Prompt evaluator, evaluate the response of model"""
    def __init__(self, opt_model_info: LLMModelInfo, infer_model_info: LLMModelInfo,
                 optimize_info: OptimizeInfo, compare_prompt: str):
        self.opt_model = LLMModelProcess(opt_model_info)
        self.infer_model = LLMModelProcess(infer_model_info)
        self._num_retires = optimize_info.num_retires
        self._llm_parallel = optimize_info.num_parallel
        self._evaluation_method = optimize_info.evaluation_method
        self._compare_answer_prompt = compare_prompt

    @staticmethod
    def parse_json(json_like_string: str) -> Dict[str, Any]:
        """Parse json string"""
        pattern = r"```json(.*?)```"
        match = re.search(pattern, json_like_string, re.DOTALL)

        if match:
            json_string = match.group(1).strip()
            try:
                parsed_data = json.loads(json_string)
            except json.decoder.JSONDecodeError:
                logger.warning("Failed to decode json string")
                return None
            return parsed_data

        logger.warning("No valid json string found")
        return None

    @staticmethod
    def compare_text(label: str, predict: str):
        """Compare the predicted text with label"""
        if not isinstance(label, str) or not isinstance(predict, str):
            return 0, "Failed to compare non-string result"
        result = label.strip() == predict.strip()
        return int(result), "Same" if result else "Different"

    def compare_llm(self, question, label, predict):
        """Compare the predicted text with label by LLM"""
        prompt_template = self._compare_answer_prompt.format(
            question=question,
            answer_match=predict,
            actual_answer=label
        )
        try:
            response = self.handle_inference_with_retry(prompt_template, is_assistant=False)
        except JiuWenBaseException:
            return 0, "Failed to compare result due to LLM calling"

        if not response or "content" not in response:
            return 0, "Failed to get response from LLM"

        compare_result = self.parse_json(response.get("content"))
        if not compare_result:
            return 0, "Parse llm compare result failed"

        result = compare_result.get("result", False)
        score = 0
        reason = compare_result.get("reason", "")
        if result is True or (isinstance(result, str) and result.strip().lower() == "true"):
            score = 1
        return score, reason

    def evaluate_result(self, question, label, predict):
        """evaluate result"""
        if self._evaluation_method == TuneConstant.EVALUATION_METHOD_TEXT:
            return self.compare_text(label, predict)
        return self.compare_llm(question, label, predict)

    def chat_completion(self, user_prompt, system_prompt, is_assistant: bool = True):
        """get llm response"""
        messages = []
        if system_prompt:
            messages.append({TuneConstant.MESSAGE_ROLE_KEY: TuneConstant.SYSTEM_ROLE,
                             TuneConstant.MESSAGE_CONTENT_KEY: system_prompt})
        messages.append({TuneConstant.MESSAGE_ROLE_KEY: TuneConstant.USER_ROLE,
                         TuneConstant.MESSAGE_CONTENT_KEY: user_prompt})
        return self.infer_model.chat(messages) if is_assistant else self.opt_model.chat(messages)

    def handle_inference_with_retry(self, user_prompt, system_prompt=None, is_assistant: bool = True):
        """chat llm with retry"""
        for i in range(self._num_retires):
            try:
                return self.chat_completion(user_prompt, system_prompt, is_assistant)
            except JiuWenBaseException as e:
                logger.info(f"Inference failed at round {i}/{self._num_retires}: {str(e)}")
                if i == self._num_retires - 1:
                    raise e
        return None

    def infer_and_compare_example(self, prompt, example, stop_event: threading.Event):
        """inference and compare example"""
        if stop_event.is_set():
            raise OnStopException("Task stop from evaluation")
        question, label = example.get(TuneConstant.QUESTION_KEY), example.get(TuneConstant.LABEL_KEY)
        example_evaluation = copy.deepcopy(example)
        tools = example_evaluation.pop(TuneConstant.TOOLS_KEY, None)
        variable = example_evaluation.get(TuneConstant.VARIABLE_KEY, None)
        if variable:
            for var_name, var_content in variable.items():
                prompt = prompt.replace(f"{{{{{var_name}}}}}", var_content)
        if TuneConstant.RAW_PROMPT_TAG in question:
            full_question = question.replace(TuneConstant.RAW_PROMPT_TAG, prompt)
            response = self.handle_inference_with_retry(full_question)
            question = str(variable)
        else:
            if tools:
                system_prompt_prefix = TuneConstant.DEFAULT_TOOL_CALL_PROMPT_PREFIX.replace(
                    "{{APIS_DESCRIPTION}}", str(tools) if tools else ""
                )
                response = self.handle_inference_with_retry(question, system_prompt_prefix + prompt)
            else:
                response = self.handle_inference_with_retry(question, prompt)
        predict = response.get(TuneConstant.MESSAGE_CONTENT_KEY, "")
        if not predict:
            example_evaluation["score"] = 0
            example_evaluation["predict"] = None
            return example_evaluation, 0, "Failed to get predict"

        compare_result, reason = self.evaluate_result(question, label, predict)
        example_evaluation["score"] = compare_result
        example_evaluation["predict"] = predict
        return example_evaluation, compare_result, reason

    def evaluate(self, prompt, dataset, stop_event: threading.Event):
        """evaluate dataset"""
        eval_results = []
        score_results = []
        num_workers = min(self._llm_parallel, len(dataset))

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [
                executor.submit(self.infer_and_compare_example, prompt, example, stop_event)
                for example in dataset
            ]

            for future in as_completed(futures):
                if stop_event.is_set():
                    raise OnStopException("Task stop from evaluation")

                try:
                    example_evaluation, compare_result, _ = future.result()
                except Exception as e:
                    logger.error(f"Error occur during evaluation: {str(e)}")
                    raise e
                score_results.append(compare_result)
                eval_results.append(example_evaluation)
        accuracy = sum(score_results) / len(score_results) if score_results else 0
        eval_results = [item for item in eval_results if item.get("score", 0) == 0]
        eval_results = random.sample(eval_results, min(TuneConstant.DEFAULT_MAX_SAMPLED_EXAMPLE_NUM,
                                                       len(eval_results)))
        return accuracy, eval_results