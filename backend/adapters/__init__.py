from adapters.exception import JiuwenSDKError, JiuwenSDKUnavailableError, NexentCapabilityError

try:
    from adapters.jiuwen_sdk_adapter import JiuwenSDKAdapter
except ModuleNotFoundError:
    JiuwenSDKAdapter = None  # type: ignore[assignment, misc]

# Trigger platform adapter registry loading so that LocalKBAdapter is registered
# before any call to ExternalKBAdapterRegistry.instantiate(). This is a safety
# net; canonical loading happens via ``services.external_kb_service`` importing
# ``nexent.core.knowledge_base.platform_adapters``.
try:
    from nexent.core.knowledge_base import platform_adapters as _platform_adapters  # noqa: F401
except Exception:
    pass

__all__ = [
    "JiuwenSDKError",
    "JiuwenSDKUnavailableError",
    "NexentCapabilityError",
    "JiuwenSDKAdapter",
]

