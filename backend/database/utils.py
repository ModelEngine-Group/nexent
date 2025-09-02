from typing import Any, Dict


# 全局追踪字段管理方法
def add_creation_tracking(data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    添加创建追踪字段（created_by和updated_by）

    Args:
        data: 要添加字段的数据字典
        user_id: 当前用户ID

    Returns:
        Dict[str, Any]: 添加追踪字段后的数据字典
    """
    data_copy = data.copy()
    data_copy["created_by"] = user_id
    data_copy["updated_by"] = user_id
    return data_copy


def add_update_tracking(data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    添加更新追踪字段（updated_by）

    Args:
        data: 要添加字段的数据字典
        user_id: 当前用户ID

    Returns:
        Dict[str, Any]: 添加追踪字段后的数据字典
    """
    data_copy = data.copy()
    data_copy["updated_by"] = user_id
    return data_copy
