from experimental.tune.common.exception import JiuWenBaseException, StatusCode
from experimental.tune.base.constant import TuneConstant

class CaseValidationException(JiuWenBaseException):
    """Definition of cases validation exception"""
    def __init__(self, message: str, error_index: int = TuneConstant.ROOT_CASE_INDEX):
        super().__init__(StatusCode.PROMPT_OPTIMIZE_CASE_VALIDATION_ERROR.code,
                         StatusCode.PROMPT_OPTIMIZE_CASE_VALIDATION_ERROR.errmsg.format(
                             error_msg=message
                         ))

        self._error_index = error_index

    @property
    def error_index(self):
        """index of the error case"""
        return self._error_index


class OnStopException(JiuWenBaseException):
    """Definition of on-stop exception"""
    def __init__(self, message: str):
        super().__init__(StatusCode.SUCCESS.code, message)