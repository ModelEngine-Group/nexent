from adapters.exception import JiuwenSDKError, JiuwenSDKUnavailableError, NexentCapabilityError


def __getattr__(name: str):
    """Load the optional OpenJiuwen evaluation adapter only when requested."""
    if name != "JiuwenSDKAdapter":
        raise AttributeError(name)
    try:
        from adapters.jiuwen_sdk_adapter import JiuwenSDKAdapter
    except ModuleNotFoundError:
        return None
    return JiuwenSDKAdapter

__all__ = [
    "JiuwenSDKError",
    "JiuwenSDKUnavailableError",
    "NexentCapabilityError",
    "JiuwenSDKAdapter",
]
