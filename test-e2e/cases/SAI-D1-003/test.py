"""SAI-D1-003: case-local preserved component regression."""
from unittest.mock import Mock

import pytest
from nexent.core.agents.subagent_wrapper import SubAgentToolWrapper
from shared.sai_component import (
    ORIGINAL_SANDBOX_CLEANUP as ORIGINAL_SANDBOX_CLEANUP,
)
from shared.sai_component import ORIGINAL_WORKSPACE_INITIALIZE
from shared.sai_component import (
    manager as manager,
)
from shared.sai_component import (
    setup_factory as setup_factory,
)


def test_SAI_D1_003_metadata_workspace_and_external(setup_factory):
    factory, child, _, cleaned, initialized = setup_factory
    factory.workspace_path = 'logical-workspace'
    metadata = {'nested': {'region': 'east'}}
    factory._set_runtime_metadata_for_agent_tree(factory.agent, metadata)
    left, right = child(task='LEFT'), child(task='RIGHT')
    left['metadata']['nested']['region'] = 'changed'
    assert right['metadata']['nested']['region'] == 'east'
    assert child.get_runtime_metadata()['nested']['region'] == 'east'
    assert factory.agent.state['metadata']['nested']['region'] == 'east'
    assert len(initialized) == len(cleaned) == 2
    assert all(owner.workspace_path == 'logical-workspace' for owner in initialized)
    assert all(owner is not factory for owner in initialized)
    left_nested = left['agent'].managed_agents['grandchild']
    right_nested = right['agent'].managed_agents['grandchild']
    assert left_nested is not right_nested
    nested_metadata = left_nested.get_runtime_metadata()
    nested_metadata['nested']['region'] = 'nested-change'
    left_nested.set_runtime_metadata(nested_metadata)
    assert right_nested.get_runtime_metadata()['nested']['region'] == 'east'
    parent_executor = Mock(_nexent_backend='docker')
    factory._sandbox_executors = [parent_executor]
    for owner in initialized:
        own_executor = Mock(_nexent_backend='docker', _nexent_kernel_recovery_supported=False)
        owner._sandbox_executors = [own_executor, own_executor]
        ORIGINAL_WORKSPACE_INITIALIZE(owner)
        own_executor.assert_called_once()
        assert 'outputs' in own_executor.call_args.args[0]
    parent_executor.assert_not_called()
    inner = Mock(return_value='external-result')
    wrapper = SubAgentToolWrapper(inner, Mock())
    assert wrapper(task='external') == 'external-result'
    inner.assert_called_once_with(task='external')


pytestmark = [pytest.mark.case_id("SAI-D1-003"), pytest.mark.stage("D1")]
