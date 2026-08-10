"""Evaluation status constants."""


class EvalRunStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvalCaseStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EvalPassStatus:
    PASS = "pass"
    FAIL = "fail"


# Used in generate_analysis_report_impl
MAX_FAILURE_EXAMPLES = 5
