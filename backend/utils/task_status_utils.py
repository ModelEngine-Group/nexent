from typing import Dict, Any

from nexent.data_process import TaskStatus


def format_status_for_api(status_value) -> str:
    """
    Convert any status format to lowercase string format for API use

    Args:
        status_value: Any status value (enum or string)

    Returns:
        Lowercase status string for API response
    """
    # If enum, directly get value (already lowercase)
    if isinstance(status_value, TaskStatus):
        return status_value.value

    # If string, ensure lowercase
    return str(status_value).lower()


def has_result(task: Dict[str, Any]) -> bool:
    """
    Check if a task should contain result data

    Args:
        task: Task information dictionary

    Returns:
        True if task result should be returned
    """
    status = task.get("status")
    result_exists = "result" in task and task["result"]

    # Only return True if status is completed or forwarding, and result exists
    if isinstance(status, TaskStatus):
        return (status in [TaskStatus.COMPLETED, TaskStatus.FORWARDING]) and result_exists

    # String status handling
    status_str = str(status).lower()
    return status_str in ["completed", "forwarding"] and result_exists


def get_status_display(task: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get task status information for frontend display

    Args:
        task: Task information dictionary

    Returns:
        Dictionary containing status information suitable for frontend display
    """
    # Get API format status (lowercase)
    status = format_status_for_api(task["status"])

    # Build basic response
    response = {"task_id": task["id"], "status": status, "created_at": task["created_at"],
        "updated_at": task["updated_at"]}

    # Add result (if exists and status allows)
    if has_result(task):
        response["result"] = task.get("result")

    # Add error message (if exists)
    if task.get("error"):
        response["error"] = task["error"]

    return response
