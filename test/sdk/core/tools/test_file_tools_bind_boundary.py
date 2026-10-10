"""Bind-mode tools preserve successful operations and reject cross-base effects."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from nexent.core.agents.sandbox_workspace import SandboxWorkspace
from nexent.core.tools.create_file_tool import CreateFileTool
from nexent.core.tools.delete_file_tool import DeleteFileTool
from nexent.core.tools.download_from_s3_tool import DownloadFromS3Tool
from nexent.core.tools.read_file_tool import ReadFileTool
from nexent.core.tools.upload_to_s3_tool import UploadToS3Tool


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / 'outputs').mkdir()
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'inputs' / 'secret.txt').write_text('keep', encoding='utf-8')
    return SandboxWorkspace(tmp_path, '/mnt/run')


@pytest.mark.parametrize('tool_type', [CreateFileTool, ReadFileTool, DeleteFileTool])
def test_cross_base_absolute_path_has_no_side_effect(workspace, tool_type):
    tool = tool_type(init_path=str(workspace.host_root / 'outputs'), observer=None)
    tool.workspace_mapping = workspace
    arguments = ['/mnt/run/inputs/secret.txt']
    if tool_type is CreateFileTool:
        arguments.append('overwrite')
    with pytest.raises(Exception, match='outputs'):
        tool.forward(*arguments)
    assert (workspace.host_root / 'inputs' / 'secret.txt').read_text(encoding='utf-8') == 'keep'


@pytest.mark.parametrize('absolute', [False, True])
def test_create_read_delete_roundtrip(workspace, absolute):
    tools = [tool_type(init_path=str(workspace.host_root / 'outputs'), observer=None)
             for tool_type in (CreateFileTool, ReadFileTool, DeleteFileTool)]
    for tool in tools:
        tool.workspace_mapping = workspace
    path = '/mnt/run/outputs/new/file.txt' if absolute else 'new/file.txt'
    created = json.loads(tools[0].forward(path, 'hello'))
    assert created['absolute_path'] == '/mnt/run/outputs/new/file.txt'
    assert 'hello' in tools[1].forward(created['absolute_path'])
    deleted = json.loads(tools[2].forward(created['absolute_path']))
    assert deleted['absolute_path'] == created['absolute_path']
    assert not (workspace.host_root / 'outputs' / 'new' / 'file.txt').exists()


def test_delete_missing_file_reports_failure(workspace):
    tool = DeleteFileTool(init_path=str(workspace.host_root / 'outputs'), observer=None)
    tool.workspace_mapping = workspace
    with pytest.raises(Exception, match='does not exist'):
        tool.forward('missing.txt')


def test_delete_permission_failure_preserves_file(workspace, mocker):
    target = workspace.host_root / 'outputs' / 'file.txt'
    target.write_text('keep', encoding='utf-8')
    tool = DeleteFileTool(init_path=str(target.parent), observer=None)
    tool.workspace_mapping = workspace
    remove = mocker.patch('nexent.core.tools.delete_file_tool.os.remove', side_effect=PermissionError('denied'))
    with pytest.raises(Exception, match='Permission denied'):
        tool.forward('file.txt')
    remove.assert_called_once_with(str(target))
    assert target.read_text(encoding='utf-8') == 'keep'


def test_upload_keeps_access_to_inputs(workspace):
    tool = UploadToS3Tool(workspace_path=str(workspace.host_root))
    tool.workspace_mapping = workspace
    assert tool._upload_path_candidates('/mnt/run/inputs/secret.txt') == [
        str(workspace.host_root / 'inputs' / 'secret.txt'),
    ]


def test_download_creates_new_nested_target(workspace):
    client = Mock()
    client.get_file_size.return_value = 5
    def download(key, path, bucket):
        Path(path).write_text('hello', encoding='utf-8')
        return True, ''
    client.download_file.side_effect = download
    tool = DownloadFromS3Tool(
        workspace_path=str(workspace.host_root), minio_client=client, validate_url_access=lambda _: None,
    )
    tool.workspace_mapping = workspace
    result = json.loads(tool.forward('s3://bucket/input.txt', '/mnt/run/inputs/new/input.txt'))
    assert result['local_path'] == '/mnt/run/inputs/new/input.txt'
    assert (workspace.host_root / 'inputs' / 'new' / 'input.txt').read_text(encoding='utf-8') == 'hello'
