# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Operations file output, shared levels, rotation and startup failure contracts."""

import logging

import pytest

import infrastructure.logging as shared_logging
from ops.logging import build_logging_config


@pytest.mark.parametrize(('level', 'debug', 'expected'), [('INFO', False, 'INFO'), ('WARNING', False, 'WARNING'), ('INFO', True, 'DEBUG')])
def test_shared_settings_and_server_routes(tmp_path, monkeypatch, level, debug, expected):
    monkeypatch.setattr(shared_logging, 'LOG_DIR', str(tmp_path))
    monkeypatch.setattr(shared_logging, 'LOG_LEVEL', level)
    monkeypatch.setattr(shared_logging, 'IS_DEBUG', debug)
    config = build_logging_config()
    assert config['root']['level'] == expected
    assert config['root']['handlers'] == ['console', 'file_ops']
    assert config['handlers']['file_ops']['filename'] == str(tmp_path / 'ops/nexent_ops.log')
    for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
        assert config['loggers'][name]['handlers'] == ['console', 'file_ops']
        assert config['loggers'][name]['propagate'] is False


def test_file_output_rotates_with_shared_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(shared_logging, 'LOG_DIR', str(tmp_path))
    monkeypatch.setattr(shared_logging, 'LOG_MAX_BYTES', 64)
    config = build_logging_config()['handlers']['file_ops']
    handler = shared_logging.HybridRotatingFileHandler(
        config['filename'], when=config['when'], interval=config['interval'],
        backupCount=config['backupCount'], maxBytes=config['maxBytes'], encoding=config['encoding'],
    )
    try:
        handler.handle(logging.LogRecord('ops', logging.INFO, __file__, 1, 'x' * 100, (), None))
        handler.handle(logging.LogRecord('uvicorn.access', logging.INFO, __file__, 1, 'request after rotation', (), None))
        handler.flush()
        assert 'request after rotation' in (tmp_path / 'ops/nexent_ops.log').read_text(encoding='utf-8')
        assert any('x' * 100 in p.read_text(encoding='utf-8') for p in (tmp_path / 'ops').glob('nexent_ops.log.*'))
    finally:
        handler.close()


def test_invalid_log_directory_rejects_startup(tmp_path, monkeypatch):
    invalid = tmp_path / 'not-a-directory'
    invalid.write_text('occupied', encoding='utf-8')
    monkeypatch.setattr(shared_logging, 'LOG_DIR', str(invalid))
    with pytest.raises((NotADirectoryError, FileExistsError)):
        build_logging_config()
