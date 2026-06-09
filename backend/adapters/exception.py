class JiuwenSDKError(Exception):
    """Jiuwen SDK 调用失败的通用异常"""
    pass


class JiuwenSDKUnavailableError(JiuwenSDKError):
    """Jiuwen SDK 不可用（依赖缺失或未启用）"""
    pass


class NexentCapabilityError(Exception):
    """nexent 原生模式不支持该能力"""
    pass
