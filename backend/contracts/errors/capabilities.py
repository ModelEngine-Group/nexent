# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Errors exposed by optional model capabilities."""

class JiuwenSDKError(Exception):
    """Jiuwen SDK operation failed."""
    pass


class JiuwenSDKUnavailableError(JiuwenSDKError):
    """The Jiuwen SDK is unavailable."""
    pass


class NexentCapabilityError(Exception):
    """The active Nexent mode does not support this capability."""
    pass
