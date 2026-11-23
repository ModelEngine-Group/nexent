# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Upload bytes must come from the validated file, not a later path lookup."""

import ctypes
import json
import os
import sys
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nexent.core.tools.upload_to_s3_tool import UploadToS3Tool


@pytest.fixture
def upload(tmp_path):
    root = tmp_path / 'run'
    (root / 'outputs').mkdir(parents=True)
    source = root / 'outputs' / 'report.txt'
    source.write_bytes(b'SAFE')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / source.name).write_bytes(b'PRIVATE')
    client = Mock(default_bucket='test')
    received, handles = [], []

    def accept(stream, key):
        handles.append(stream)
        received.append((stream.read(), key))
        return True, ''

    client.upload_fileobj.side_effect = accept
    client.upload_file.side_effect = lambda path, key: (received.append((Path(path).read_bytes(), key)) or (True, ''))
    callback = Mock()
    tool = UploadToS3Tool(workspace_path=str(root), minio_client=client,
                         user_id='user', run_id='run', on_upload=callback)
    return tool, source, outside, received, handles, callback


def test_upload_uses_and_closes_validated_stream(upload):
    tool, source, _, received, handles, callback = upload
    result = json.loads(tool.forward('report.txt'))
    assert received == [(b'SAFE', 'workspace/user/run/outputs/report.txt')]
    assert len(handles) == 1 and handles[0].closed
    assert result['size'] == result['file_size_bytes'] == 4
    callback.assert_called_once_with(result)
    assert os.path.normcase(str(source)) in tool.uploaded_paths
    tool.minio_client.upload_file.assert_not_called()


@pytest.mark.skipif(os.name != 'posix', reason='Real POSIX replacement is also exercised in Kubernetes')
@pytest.mark.parametrize('parent', [False, True])
def test_replacement_before_open_cannot_upload_outside(upload, monkeypatch, parent):
    tool, source, outside, received, _, callback = upload
    original = tool._upload_path_candidates
    replaced = []

    def candidates(value):
        paths = original(value)
        target = source.parent if parent else source
        target.rename(target.with_name(target.name + '-saved'))
        target.symlink_to(outside if parent else outside / source.name, target_is_directory=parent)
        replaced.append(True)
        return paths

    monkeypatch.setattr(tool, '_upload_path_candidates', candidates)
    with pytest.raises(Exception):
        tool.forward('report.txt')
    assert replaced == [True] and received == []
    callback.assert_not_called()
    assert tool.uploaded_paths == set()


@pytest.mark.skipif(os.name != 'posix', reason='Real POSIX replacement is also exercised in Kubernetes')
@pytest.mark.parametrize('parent', [False, True])
def test_replacement_after_open_uploads_original_bytes(upload, monkeypatch, parent):
    tool, source, outside, received, handles, _ = upload
    original = tool.minio_client.upload_fileobj.side_effect
    replaced = []

    def replace_then_read(stream, key):
        target = source.parent if parent else source
        target.rename(target.with_name(target.name + '-saved'))
        target.symlink_to(outside if parent else outside / source.name, target_is_directory=parent)
        replaced.append(True)
        return original(stream, key)

    tool.minio_client.upload_fileobj.side_effect = replace_then_read
    result = json.loads(tool.forward('report.txt'))
    assert replaced == [True] and received[0][0] == b'SAFE'
    assert handles[0].closed and result['size'] == 4


@pytest.mark.parametrize('failure', ['result', 'exception'])
def test_upload_failure_closes_stream_without_success_side_effects(upload, failure):
    tool, _, _, _, handles, callback = upload

    def fail(stream, key):
        handles.append(stream)
        if failure == 'exception':
            raise OSError('storage unavailable')
        return False, 'storage unavailable'

    tool.minio_client.upload_fileobj.side_effect = fail
    with pytest.raises(Exception, match='storage unavailable'):
        tool.forward('report.txt')
    assert handles[0].closed
    callback.assert_not_called()
    assert tool.uploaded_paths == set()


@pytest.mark.skipif(os.name != 'posix', reason='POSIX symbolic links')
def test_existing_in_workspace_symlink_still_uploads(upload):
    tool, source, _, received, _, _ = upload
    source.with_name('alias.txt').symlink_to(source)
    assert json.loads(tool.forward('alias.txt'))['status'] == 'success'
    assert received[0][0] == b'SAFE'


@pytest.mark.parametrize(('workspace', 'handle_path', 'length', 'error'), [
    (r'C:\run', r'\\?\C:\run\report.txt', None, None),
    (r'\\server\share\run', r'\\?\UNC\server\share\run\report.txt', None, None),
    (r'C:\run', r'\\?\C:\outside\report.txt', None, ValueError),
    (r'C:\run', '', 0, OSError),
    (r'C:\run', '', 32768, OSError),
])
def test_windows_handle_path_verification(monkeypatch, tmp_path, workspace, handle_path, length, error):
    import nexent.core.tools.upload_to_s3_tool as module

    source = tmp_path / 'report.txt'
    source.write_bytes(b'SAFE')
    stream = source.open('rb')
    windows_workspace = PureWindowsPath(workspace)
    windows_source = windows_workspace / source.name

    def final_path(handle, buffer, size, flags):
        assert (handle, size, flags) == (47, 32768, 0)
        buffer.value = handle_path
        return len(handle_path) if length is None else length

    get_handle = Mock(return_value=47)
    win_dll = Mock(return_value=SimpleNamespace(GetFinalPathNameByHandleW=final_path))
    open_file = Mock(return_value=stream)
    monkeypatch.setitem(sys.modules, 'msvcrt', SimpleNamespace(get_osfhandle=get_handle))
    monkeypatch.setattr(ctypes, 'WinDLL', win_dll, raising=False)
    monkeypatch.setattr(module, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(module, 'Path', PureWindowsPath)
    monkeypatch.setattr(module, 'open', open_file, raising=False)

    try:
        with module._open_upload_file(str(windows_source), windows_workspace) as opened:
            assert error is None
            assert opened.read() == b'SAFE'
    except (OSError, ValueError) as exc:
        assert error is not None and isinstance(exc, error)
    assert stream.closed
    open_file.assert_called_once_with(windows_source, 'rb')
    win_dll.assert_called_once_with('kernel32', use_last_error=True)
    get_handle.assert_called_once()


@pytest.mark.skipif(os.name != 'nt', reason='Windows extended-length path compatibility')
def test_windows_extended_workspace_path_still_uploads(upload):
    tool, _, _, received, _, _ = upload
    tool.workspace_path = '\\\\?\\' + tool.workspace_path
    assert json.loads(tool.forward('report.txt'))['status'] == 'success'
    assert received[0][0] == b'SAFE'


@pytest.mark.skipif(os.name != 'nt', reason='Windows opened-handle target verification')
def test_windows_opened_outside_target_is_rejected(upload, monkeypatch):
    import nexent.core.tools.upload_to_s3_tool as module

    tool, source, outside, received, _, callback = upload
    opened = []
    def redirected_open(path, mode):
        stream = open(outside / source.name, mode)
        opened.append(stream)
        return stream
    monkeypatch.setattr(module, 'open', redirected_open, raising=False)
    with pytest.raises(Exception):
        tool.forward('report.txt')
    assert len(opened) == 1 and opened[0].closed
    assert received == [] and tool.uploaded_paths == set()
    callback.assert_not_called()
