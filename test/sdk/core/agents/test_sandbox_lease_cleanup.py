"""A failed lease cleanup cannot terminate a sibling's shared container."""

from concurrent.futures import TimeoutError
from unittest.mock import Mock

import pytest
from nexent.core.agents import sandbox


@pytest.mark.parametrize("error", [RuntimeError("failed"), TimeoutError()])
@pytest.mark.parametrize("is_lease", [False, True])
def test_cleanup_fallback_respects_container_ownership(mocker, error, is_lease):
    manager = Mock()
    manager.run_sync.side_effect = error
    mocker.patch.object(sandbox, "_get_sandbox_thread_manager", return_value=manager)
    executor = Mock(_nexent_kernel_lease=is_lease)
    sandbox.cleanup_executor(executor, Mock(), timeout=0.1)
    manager.run_sync.assert_called_once()
    if is_lease:
        executor.container.kill.assert_not_called()
    else:
        executor.container.kill.assert_called_once()
