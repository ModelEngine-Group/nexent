"""SAI-D1-004: case-local preserved component regression."""
from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import AgentConfig, ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from shared.sai_component import (
    ORIGINAL_SANDBOX_CLEANUP as ORIGINAL_SANDBOX_CLEANUP,
)
from shared.sai_component import (
    manager as manager,
)
from shared.sai_component import (
    setup_factory as setup_factory,
)


def test_SAI_D1_004_injected_clients(setup_factory, monkeypatch):
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    from nexent.storage.minio import MinIOStorageClient

    client = object.__new__(MinIOStorageClient)
    client.s3_client = boto3.client('s3', region_name='us-east-1',
        endpoint_url='http://localhost:9000', config=Config(signature_version=UNSIGNED))
    factory, _, _, _, _ = setup_factory
    captured = []

    def tool(owner, config):
        captured.append(config)
        return Mock()

    monkeypatch.setattr(NexentAgent, 'create_tool', tool)
    config = AgentConfig(name='injected', description='client', model_name='test', tools=[
        ToolConfig(name='analyze_image', class_name='AnalyzeImageTool', params={'options': [1]}, metadata={'storage_client': client}),
    ])
    child = factory._create_subagent_definition(config, {})
    try:
        child(task='LEFT')
        child(task='RIGHT')
        assert all(c.metadata['storage_client'] is client for c in captured)
        captured[0].params['options'].append(2)
        assert captured[1].params['options'] == config.tools[0].params['options'] == [1]
    finally:
        client.s3_client.close()


pytestmark = [pytest.mark.case_id("SAI-D1-004"), pytest.mark.stage("D1")]
