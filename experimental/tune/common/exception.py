from enum import Enum

class JiuWenException(Exception):
    def __init__(self,
                 message,
                 *args, **kwargs):
        super().__init__(message, args, kwargs)

class JiuWenBaseException(Exception):
    def __init__(self,
                 error_code,
                 message):
        super().__init__(error_code, message)
        self._error_code = error_code
        self._message = message

    def __str__(self):
        return f"[{self._error_code}]{self._message}"

    @property
    def error_code(self):
        return self._error_code

    @property
    def message(self):
        return self._message


class ParamCheckFailedException(JiuWenBaseException):
    def __init__(self, message: str):
        super().__init__(error_code=StatusCode.PARAM_CHECK_FAILED_ERROR.code,
                         message=f"{StatusCode.PARAM_CHECK_FAILED_ERROR.errmsg}, root cause = {message}")


class StatusCode(Enum):
    SUCCESS = (200, "success")

    PARAM_CHECK_FAILED_ERROR = (100002, "Error occur when input parameter varification failed")
    LLM_CONFIG_MISS_ERROR = (100021, "LLM service configuration is missing: {error_msg}")
    LLM_FALSE_RESULT_ERROR = (102003, "LLM service return false result due to {error_msg}")

    PROMPT_OPTIMIZE_REFINE_INSTRUCTION_ERROR = (
        102162, "Prompt optimization failed to refine instruction, root cause: {error_msg}"
    )

    PROMPT_OPTIMIZE_RESTART_TASK_ERROR = (102159, "Prompt optimization restart task error: {error_msg}")
    PROMPT_OPTIMIZE_EVALUATE_ERROR = (102157, "Prompt optimization evaluate failed, root cause: {error_msg}")
    PROMPT_OPTIMIZE_INVALID_PARAMS_ERROR = (
        102154, "Prompt optimization parameters are invalid, root cause = {error_msg}")
    PROMPT_OPTIMIZE_CASE_VALIDATION_ERROR = (
        102161, "Prompt optimization validate input case failed, root cause = {error_msg}"
    )

    @property
    def code(self) -> int:
        return self.value[0]

    @property
    def errmsg(self) -> str:
        return self.value[1]