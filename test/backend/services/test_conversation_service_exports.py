# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Agent subscriptions consume the conversation service's public read facade."""

import pytest


@pytest.mark.parametrize("name", ["get_last_unit_for_message", "get_latest_assistant_message"])
def test_subscription_read_exports_remain_available(name):
    from management.db.conversation import repository
    from management.services.conversation import service
    assert getattr(service, name) is getattr(repository, name)
