# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Preserved preview behavior assertions at the canonical lookup sites."""
from time import monotonic
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nexent.storage.models import OperationContext

from test.backend.management.import_patching import patch_import_context


def context():
    return OperationContext('owned-preview-contract', monotonic() + 120)

class TestResolvePreviewFile:
    """Test cases for resolve_preview_file function"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize('object_name,content_type', [('test/document.pdf', 'application/pdf'), ('test/image.png', 'image/png'), ('test/image.jpeg', 'image/jpeg'), ('test/readme.txt', 'text/plain'), ('test/data.csv', 'text/csv'), ('test/readme.md', 'text/markdown'), ('test/data.json', 'application/json')])
    async def test_direct_types_returned_as_is(self, object_name, content_type):
        """PDF, images, and text files resolve to themselves without conversion."""
        from management.services.file.preview import resolve_preview_file
        with patch_import_context('management.services.file.preview._io', return_value=1024, new_callable=AsyncMock), patch_import_context('management.services.file.preview.get_content_type', return_value=content_type):
            actual_name, actual_ct, total_size = await resolve_preview_file(object_name)
            assert actual_name == object_name
            assert actual_ct == content_type
            assert total_size == 1024

    @pytest.mark.asyncio
    async def test_office_cache_hit_returns_pdf_path(self):
        """When a valid cached PDF exists, returns converted PDF path without re-converting."""
        from management.services.file.preview import resolve_preview_file
        docx_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        with patch_import_context('management.services.file.preview._io', side_effect=[2048, 5000], new_callable=AsyncMock), patch_import_context('management.services.file.preview.get_content_type', return_value=docx_type), patch_import_context('management.services.file.preview._is_pdf_cache_valid', return_value=True):
            actual_name, actual_ct, total_size = await resolve_preview_file('test/document.docx')
            assert actual_ct == 'application/pdf'
            assert actual_name.endswith('.pdf')
            assert total_size == 5000

    @pytest.mark.asyncio
    async def test_office_cache_miss_triggers_conversion(self):
        """When no valid cache exists, triggers conversion and returns resulting PDF path."""
        from management.services.file.preview import resolve_preview_file
        docx_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        with patch_import_context('management.services.file.preview._io', side_effect=[2048, 6000], new_callable=AsyncMock), patch_import_context('management.services.file.preview.get_content_type', return_value=docx_type), patch_import_context('management.services.file.preview._is_pdf_cache_valid', return_value=False), patch_import_context('management.services.file.preview._convert_office_to_cached_pdf', new_callable=AsyncMock) as mock_convert:
            actual_name, actual_ct, total_size = await resolve_preview_file('test/document.docx')
            mock_convert.assert_called_once()
            assert actual_ct == 'application/pdf'
            assert actual_name.endswith('.pdf')
            assert total_size == 6000

    @pytest.mark.asyncio
    async def test_file_too_large_raises_exception(self):
        """Files exceeding FILE_PREVIEW_SIZE_LIMIT raise FileTooLargeException."""
        from contracts.errors.exceptions import FileTooLargeException
        from management.services.file.preview import (
            FILE_PREVIEW_SIZE_LIMIT,
            resolve_preview_file,
        )
        oversized = FILE_PREVIEW_SIZE_LIMIT + 1
        with patch_import_context('management.services.file.preview._io', return_value=oversized, new_callable=AsyncMock), pytest.raises(FileTooLargeException) as exc_info:
            await resolve_preview_file('test/large_file.pdf')
        assert str(FILE_PREVIEW_SIZE_LIMIT // (1024 * 1024)) in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_unsupported_file_type_raises_exception(self):
        """Unsupported content types raise UnsupportedFileTypeException."""
        from contracts.errors.exceptions import UnsupportedFileTypeException
        from management.services.file.preview import resolve_preview_file
        with patch_import_context('management.services.file.preview._io', return_value=1024, new_callable=AsyncMock), patch_import_context('management.services.file.preview.get_content_type', return_value='application/octet-stream'):
            with pytest.raises(UnsupportedFileTypeException) as exc_info:
                await resolve_preview_file('test/unknown.bin')
            assert 'Unsupported file type for preview' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_direct_preview_file_raises_not_found(self):
        """Missing direct-preview file should raise NotFoundException instead of resolving as empty."""
        from contracts.errors.exceptions import NotFoundException
        from management.services.file.preview import resolve_preview_file
        with patch_import_context('management.services.file.preview._io', new_callable=AsyncMock, side_effect=NotFoundException('File not found')), pytest.raises(NotFoundException) as exc_info:
            await resolve_preview_file('test/missing.pdf')
        assert 'File not found' in str(exc_info.value)

class TestGetPreviewStream:
    """Unit tests for get_preview_stream function."""

    def test_full_stream_returned_when_no_range(self):
        """Returns full stream when start and end are both None."""
        from management.services.file.preview import get_preview_stream
        mock_stream = MagicMock()
        with patch_import_context('management.services.file.preview.get_file_stream_raw', return_value=mock_stream) as mock_get:
            result = get_preview_stream('test/document.pdf')
            assert result is mock_stream
            mock_get.assert_called_once_with('test/document.pdf')

    def test_range_stream_returned_when_start_end_given(self):
        """Returns partial stream when start and end are provided."""
        from management.services.file.preview import get_preview_stream
        mock_stream = MagicMock()
        with patch_import_context('management.services.file.preview.get_file_range', return_value=mock_stream) as mock_get:
            result = get_preview_stream('test/document.pdf', start=0, end=1023)
            assert result is mock_stream
            mock_get.assert_called_once_with('test/document.pdf', 0, 1023)

    def test_raises_not_found_when_stream_is_none(self):
        """Raises NotFoundException when no-range stream source returns None."""
        from contracts.errors.exceptions import NotFoundException
        from management.services.file.preview import get_preview_stream
        with patch_import_context('management.services.file.preview.get_file_stream_raw', return_value=None):
            with pytest.raises(NotFoundException) as exc_info:
                get_preview_stream('test/missing.pdf')
            assert 'File not found' in str(exc_info.value)

    def test_raises_value_error_when_only_one_range_bound_provided(self):
        """Raises ValueError when start and end are not provided together."""
        from management.services.file.preview import get_preview_stream
        with pytest.raises(ValueError) as exc_info:
            get_preview_stream('test/document.pdf', start=0)
        assert 'provided together' in str(exc_info.value)

class TestConvertOfficeToCachedPdf:
    """Retain preview cache and error contracts after removing the HTTP hop."""

    @pytest.mark.asyncio
    async def test_skips_conversion_on_double_check_cache_hit(self):
        from management.services.file import preview
        with patch.object(preview, '_is_pdf_cache_valid', return_value=True), patch.object(preview, 'convert_preview', new_callable=AsyncMock) as convert:
            assert await preview._convert_office_to_cached_pdf('docs/report.docx', 'preview/report.pdf', context=context()) is None
        convert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_full_conversion_success(self):
        from management.services.file import preview
        with patch.object(preview, '_is_pdf_cache_valid', return_value=False), patch.object(preview, 'convert_preview', new_callable=AsyncMock) as convert:
            assert await preview._convert_office_to_cached_pdf('docs/report.docx', 'preview/report.pdf', context=context()) is None
        convert.assert_awaited_once()
        assert convert.await_args.args == ('docs/report.docx', 'preview/report.pdf')
        assert 0 < convert.await_args.kwargs['timeout'] <= 120

    @pytest.mark.asyncio
    async def test_storage_error_re_raises_exception(self):
        from contracts.errors.exceptions import OfficeConversionException
        from management.services.file import preview
        from nexent.storage.errors import Unavailable
        error = Unavailable()
        with patch.object(preview, '_is_pdf_cache_valid', return_value=False), patch.object(preview, 'convert_preview', new_callable=AsyncMock, side_effect=error), pytest.raises(OfficeConversionException) as caught:
            await preview._convert_office_to_cached_pdf('docs/report.docx', 'preview/report.pdf', context=context())
        assert caught.value.__cause__ is error

    @pytest.mark.asyncio
    async def test_copy_failure_re_raises_without_deleting_shared_cache(self):
        from contracts.errors.exceptions import OfficeConversionException
        from management.services.file import preview
        with patch.object(preview, '_is_pdf_cache_valid', return_value=False), patch.object(preview, 'convert_preview', new_callable=AsyncMock, side_effect=RuntimeError('copy failed')), patch.object(preview, 'PreviewObjects') as delete, pytest.raises(OfficeConversionException):
            await preview._convert_office_to_cached_pdf('docs/report.docx', 'preview/report.pdf', context=context())
        delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_office_conversion_exception_passthrough(self):
        from contracts.errors.exceptions import OfficeConversionException
        from management.services.file import preview
        error = OfficeConversionException('local conversion failed')
        with patch.object(preview, '_is_pdf_cache_valid', return_value=False), patch.object(preview, 'convert_preview', new_callable=AsyncMock, side_effect=error), pytest.raises(OfficeConversionException) as caught:
            await preview._convert_office_to_cached_pdf('docs/report.docx', 'preview/report.pdf', context=context())
        assert caught.value is error

    @pytest.mark.asyncio
    async def test_non_office_exception_is_wrapped(self):
        from contracts.errors.exceptions import OfficeConversionException
        from management.services.file import preview
        with patch.object(preview, '_is_pdf_cache_valid', return_value=False), patch.object(preview, 'convert_preview', new_callable=AsyncMock, side_effect=RuntimeError('ordinary failure')), pytest.raises(OfficeConversionException) as caught:
            await preview._convert_office_to_cached_pdf('docs/report.docx', 'preview/report.pdf', context=context())
        assert 'Office file conversion failed' in str(caught.value)
        assert isinstance(caught.value.__cause__, RuntimeError)

    @pytest.mark.asyncio
    async def test_reuses_existing_lock_for_same_object(self):
        import asyncio

        from management.services.file import preview
        existing = asyncio.Lock()
        preview._conversion_locks['docs/existing.docx'] = existing
        with patch.object(preview, '_is_pdf_cache_valid', return_value=True):
            await preview._convert_office_to_cached_pdf('docs/existing.docx', 'preview/existing.pdf', context=context())
            assert preview._conversion_locks['docs/existing.docx'] is existing
