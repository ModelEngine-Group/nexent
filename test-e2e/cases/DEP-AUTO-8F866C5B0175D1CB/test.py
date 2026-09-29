'''D5 special-case test: one-shot legacy tag backfill for unified tag management.

DEP-AUTO-8F866C5B0175D1CB

Runs the deploy-provided PostgreSQL 15 docker integration suite that materializes
the legacy schema, exercises the read-only preflight conflict scan, performs the
keywords definition/value/assignment backfill for tool/skill/agent_repository/
skill_repository/mcp_record/mcp_community/mcp_market legacy tags, verifies
idempotent reruns and post_backfill parity, and asserts fail-closed rollback on
conflict or capacity overflow.
'''

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from shared.config import repo_root

CASE_ID = 'DEP-AUTO-8F866C5B0175D1CB'

_REQUIRED_ASSETS = (
    'deploy/sql/migrations/v2.5.2_unified_tag_management.sql',
    'deploy/sql/preflight/unified_tag_management_preflight.sql',
    'deploy/sql/init.sql',
    'deploy/tests/test_unified_tag_management.sh',
)


def _repo_root() -> Path:
    return repo_root()


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D5')
def test_unified_tag_management_backfill() -> None:
    root = _repo_root()
    for relative in _REQUIRED_ASSETS:
        assert (root / relative).is_file(), f'required deploy asset missing: {relative}'

    suite = root / 'deploy/tests/test_unified_tag_management.sh'
    env = dict(os.environ)
    env.setdefault('POSTGRES_TEST_IMAGE', 'postgres:15-alpine')
    completed = subprocess.run(
        ['bash', str(suite)],
        cwd=str(root / 'deploy'),
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    output = completed.stdout + chr(10) + completed.stderr
    assert completed.returncode == 0, (
        'unified tag management migration suite failed (exit '
        + str(completed.returncode)
        + '); output=' + repr(output[-4000:])
    )
    assert 'PASS: all unified tag management integration tests passed' in output, (
        'migration suite finished without the expected PASS summary'
    )
