import logging

import pytest
from fastapi import BackgroundTasks

from sdk.benchmark.generic.integrations.langfuse.webhook_server import (
    WebhookPayload,
    handle_webhook,
)


@pytest.mark.asyncio
async def test_invalid_payload_does_not_expose_parser_or_payload_details(caplog):
    raw_payload = '{"api_key": "secret-value"'
    payload = WebhookPayload(
        datasetName="security-test",
        payload=raw_payload,
    )

    with caplog.at_level(logging.WARNING, logger="benchmark-webhook"):
        response = await handle_webhook(payload, BackgroundTasks())

    assert response == {
        "status": "error",
        "message": "invalid payload JSON",
    }
    serialized_response = str(response)
    assert "secret-value" not in serialized_response
    assert "Expecting" not in serialized_response
    assert raw_payload not in caplog.text
    assert "secret-value" not in caplog.text
