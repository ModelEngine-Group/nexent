from typing import Any, Dict


# Global tracking field management methods
def add_creation_tracking(data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Add creation tracking fields (created_by and updated_by)

    Args:
        data: Data dictionary to add fields to
        user_id: Current user ID

    Returns:
        Dict[str, Any]: Data dictionary with tracking fields added
    """
    data_copy = data.copy()
    data_copy["created_by"] = user_id
    data_copy["updated_by"] = user_id
    return data_copy


def add_update_tracking(data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Add update tracking field (updated_by)

    Args:
        data: Data dictionary to add field to
        user_id: Current user ID

    Returns:
        Dict[str, Any]: Data dictionary with tracking field added
    """
    data_copy = data.copy()
    data_copy["updated_by"] = user_id
    return data_copy
