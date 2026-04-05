import pytest
from pytest_mock import MockFixture
from unittest.mock import Mock, MagicMock

from sdk.nexent.data_process.core import DataProcessCore


def _unpack_chunks(result):
    if isinstance(result, tuple):
        return result[0]
    return result


def _unpack_images(result):
    if isinstance(result, tuple):
        return result[1]
    return []


class TestDataProcessCore:
    """Test suite for DataProcessCore class"""

    @pytest.fixture
    def core(self):
        """Create a DataProcessCore instance for testing"""
        return DataProcessCore()

    def test_init(self, core):
        """Test DataProcessCore initialization"""
        assert core is not None
        assert "Unstructured" in core.processors
        assert "OpenPyxl" in core.processors
        assert "UniversalImageExtractor" in core.processors
        assert len(core.processors) == 3

    def test_file_process_with_excel_file(self, core, mocker: MockFixture):
        """Test file processing with Excel file"""
        # Mock OpenPyxl processor
        mock_processor = Mock()
        mock_processor.process_file.return_value = [
            {"content": "test content", "filename": "test.xlsx",
                "metadata": {"chunk_index": 0}}
        ]
        core.processors["OpenPyxl"] = mock_processor
        core.processors["UniversalImageExtractor"] = Mock(
            process_file=Mock(return_value=[])
        )

        file_data = b"fake excel data"
        filename = "test.xlsx"

        result = core.file_process(
            file_data, filename, chunking_strategy="basic")

        chunks = _unpack_chunks(result)
        assert len(chunks) == 1
        assert chunks[0]["content"] == "test content"
        mock_processor.process_file.assert_called_once_with(
            file_data, "basic", filename=filename
        )

    def test_file_process_with_pdf_file(self, core, mocker: MockFixture):
        """Test file processing with PDF file"""
        # Mock Unstructured processor
        mock_processor = Mock()
        mock_processor.process_file.return_value = [
            {"content": "pdf content", "filename": "test.pdf"}
        ]
        core.processors["Unstructured"] = mock_processor

        file_data = b"fake pdf data"
        filename = "test.pdf"

        result = core.file_process(
            file_data, filename, chunking_strategy="by_title")

        chunks = _unpack_chunks(result)
        assert len(chunks) == 1
        assert chunks[0]["content"] == "pdf content"
        mock_processor.process_file.assert_called_once_with(
            file_data, "by_title", filename=filename
        )

    def test_file_process_with_explicit_processor(self, core, mocker: MockFixture):
        """Test file processing with explicitly specified processor"""
        mock_processor = Mock()
        mock_processor.process_file.return_value = [{"content": "test"}]
        core.processors["Unstructured"] = mock_processor
        core.processors["UniversalImageExtractor"] = Mock(
            process_file=Mock(return_value=[])
        )

        file_data = b"data"
        filename = "test.xlsx"

        # Explicitly use Unstructured processor for Excel file
        result = core.file_process(
            file_data, filename, chunking_strategy="basic", processor="Unstructured"
        )

        chunks = _unpack_chunks(result)
        assert len(chunks) == 1
        mock_processor.process_file.assert_called_once()

    def test_file_process_with_additional_params(self, core, mocker: MockFixture):
        """Test file processing with additional parameters"""
        mock_processor = Mock()
        mock_processor.process_file.return_value = [{"content": "test"}]
        core.processors["Unstructured"] = mock_processor

        file_data = b"data"
        filename = "test.pdf"
        additional_params = {"max_characters": 2000, "strategy": "fast"}

        result = core.file_process(
            file_data, filename, chunking_strategy="basic", **additional_params
        )

        chunks = _unpack_chunks(result)
        assert len(chunks) == 1
        mock_processor.process_file.assert_called_once_with(
            file_data, "basic", filename=filename, max_characters=2000, strategy="fast"
        )

    def test_file_process_invalid_chunking_strategy(self, core):
        """Test file processing with invalid chunking strategy"""
        file_data = b"data"
        filename = "test.pdf"

        with pytest.raises(ValueError, match="Unsupported chunking strategy"):
            core.file_process(file_data, filename, chunking_strategy="invalid")

    def test_file_process_invalid_processor(self, core):
        """Test file processing with invalid processor"""
        file_data = b"data"
        filename = "test.pdf"

        with pytest.raises(ValueError, match="Unsupported processor type"):
            core.file_process(
                file_data, filename, chunking_strategy="basic", processor="InvalidProcessor"
            )

    def test_file_process_unsupported_processor_type(self, core):
        """Test file processing when processor is not in processors dict"""
        file_data = b"data"
        filename = "test.pdf"

        # Remove Unstructured processor
        core.processors.pop("Unstructured", None)

        with pytest.raises(ValueError, match="Unsupported processor"):
            core.file_process(file_data, filename, chunking_strategy="basic")

    def test_file_process_processing_error(self, core, mocker: MockFixture):
        """Test file processing when processor raises an exception"""
        mock_processor = Mock()
        mock_processor.process_file.side_effect = Exception(
            "Processing failed")
        core.processors["Unstructured"] = mock_processor

        file_data = b"data"
        filename = "test.pdf"

        with pytest.raises(Exception, match="Processing failed"):
            core.file_process(file_data, filename, chunking_strategy="basic")

    @pytest.mark.parametrize(
        "chunking_strategy",
        ["basic", "by_title", "none"]
    )
    def test_validate_parameters_valid_strategies(self, core, chunking_strategy):
        """Test parameter validation with valid chunking strategies"""
        # Should not raise exception
        core._validate_parameters(chunking_strategy, None)

    @pytest.mark.parametrize(
        "processor",
        ["Unstructured", "OpenPyxl", "UniversalImageExtractor"]
    )
    def test_validate_parameters_valid_processors(self, core, processor):
        """Test parameter validation with valid processors"""
        # Should not raise exception
        core._validate_parameters("basic", processor)

    def test_validate_parameters_invalid_strategy(self, core):
        """Test parameter validation with invalid chunking strategy"""
        with pytest.raises(ValueError, match="Unsupported chunking strategy"):
            core._validate_parameters("invalid_strategy", None)

    def test_validate_parameters_invalid_processor(self, core):
        """Test parameter validation with invalid processor"""
        with pytest.raises(ValueError, match="Unsupported processor type"):
            core._validate_parameters("basic", "InvalidProcessor")

    @pytest.mark.parametrize(
        "filename,expected_processor,expected_extractor",
        [
            ("test.xlsx", "OpenPyxl", "UniversalImageExtractor"),
            ("test.xls", "OpenPyxl", "UniversalImageExtractor"),
            ("test.XLSX", "OpenPyxl", "UniversalImageExtractor"),
            ("test.pdf", "Unstructured", "UniversalImageExtractor"),
            ("test.docx", "Unstructured", "UniversalImageExtractor"),
            ("test.pptx", "Unstructured", None),
            ("test.txt", "Unstructured", None),
            ("test.html", "Unstructured", None),
        ]
    )
    def test_select_processor_by_filename(self, core, filename, expected_processor, expected_extractor):
        """Test processor selection based on filename"""
        params = {"model_type": "multi_embedding"} if expected_extractor else {}
        processor_name, extractor = core._select_processor_by_filename(filename, params)
        assert processor_name == expected_processor
        assert extractor == expected_extractor

    def test_get_supported_file_types(self, core):
        """Test getting supported file types"""
        result = core.get_supported_file_types()

        assert "excel" in result
        assert "generic" in result
        assert ".xlsx" in result["excel"]
        assert ".xls" in result["excel"]
        assert len(result["generic"]) > 0

    def test_get_supported_file_types_with_unstructured_formats(self, core, mocker: MockFixture):
        """Test getting supported file types when UnstructuredProcessor has get_supported_formats"""
        mock_processor = MagicMock()
        mock_processor.get_supported_formats.return_value = [
            ".pdf", ".docx", ".txt"]

        # Need to make isinstance check pass
        mocker.patch(
            "sdk.nexent.data_process.core.isinstance",
            return_value=True
        )
        core.processors["Unstructured"] = mock_processor

        result = core.get_supported_file_types()

        assert result["generic"] == [".pdf", ".docx", ".txt"]

    def test_get_supported_file_types_without_unstructured_method(self, core):
        """Test getting supported file types when UnstructuredProcessor lacks get_supported_formats"""
        # Replace with a mock that doesn't have get_supported_formats
        core.processors["Unstructured"] = Mock(spec=[])

        result = core.get_supported_file_types()

        # Should return default formats
        assert ".txt" in result["generic"]
        assert ".pdf" in result["generic"]
        assert ".docx" in result["generic"]

    def test_get_supported_strategies(self, core):
        """Test getting supported chunking strategies"""
        result = core.get_supported_strategies()

        assert "basic" in result
        assert "by_title" in result
        assert "none" in result
        assert len(result) == 3

    def test_get_supported_processors(self, core):
        """Test getting supported processor types"""
        result = core.get_supported_processors()

        assert "Unstructured" in result
        assert "OpenPyxl" in result
        assert "UniversalImageExtractor" in result
        assert len(result) == 3

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("test.xlsx", True),
            ("test.xls", True),
            ("test.pdf", True),
            ("test.docx", True),
            ("test.txt", True),
            ("test.unknown", False),
            ("test.exe", False),
            ("", False),
        ]
    )
    def test_validate_file_type(self, core, filename, expected):
        """Test file type validation"""
        result = core.validate_file_type(filename)
        assert result == expected

    def test_validate_file_type_empty_filename(self, core):
        """Test file type validation with empty filename"""
        result = core.validate_file_type("")
        assert result is False

    def test_validate_file_type_none_filename(self, core):
        """Test file type validation with None filename"""
        result = core.validate_file_type(None)
        assert result is False

    @pytest.mark.parametrize(
        "filename,expected_type,expected_ext",
        [
            ("test.xlsx", "excel", ".xlsx"),
            ("test.xls", "excel", ".xls"),
            ("test.pdf", "generic", ".pdf"),
            ("test.docx", "generic", ".docx"),
            ("test.txt", "generic", ".txt"),
        ]
    )
    def test_get_processor_info(self, core, filename, expected_type, expected_ext):
        """Test getting processor information"""
        result = core.get_processor_info(filename)

        assert result["processor_type"] == expected_type
        assert result["file_extension"] == expected_ext
        assert "is_supported" in result

    def test_get_processor_info_empty_filename(self, core):
        """Test getting processor information with empty filename"""
        result = core.get_processor_info("")

        assert result["processor_type"] == "generic"
        assert result["file_extension"] == ""
        assert result["is_supported"] == "False"

    def test_get_processor_info_none_filename(self, core):
        """Test getting processor information with None filename"""
        result = core.get_processor_info(None)

        assert result["processor_type"] == "generic"
        assert result["file_extension"] == ""
        assert result["is_supported"] == "False"

    def test_get_processor_info_case_insensitive(self, core):
        """Test getting processor information with uppercase extension"""
        result = core.get_processor_info("TEST.XLSX")

        assert result["processor_type"] == "excel"
        assert result["file_extension"] == ".xlsx"

    def test_file_process_returns_images_when_extractor_available(self, core, mocker: MockFixture):
        """Test image extraction is returned for supported file types."""
        mock_processor = Mock()
        mock_processor.process_file.return_value = [{"content": "test"}]
        mock_extractor = Mock()
        mock_extractor.process_file.return_value = [
            {"image_bytes": b"img", "image_format": "png", "position": {"page_number": 1}}
        ]
        core.processors["Unstructured"] = mock_processor
        core.processors["UniversalImageExtractor"] = mock_extractor

        result = core.file_process(
            b"data", "sample.pdf", chunking_strategy="basic", model_type="multi_embedding"
        )

        chunks = _unpack_chunks(result)
        images = _unpack_images(result)
        assert len(chunks) == 1
        assert len(images) == 1
        mock_extractor.process_file.assert_called_once()

    def test_file_process_with_explicit_processor_still_extracts_images(self, core):
        """Test explicit processor still triggers image extraction."""
        core.processors["Unstructured"] = Mock(process_file=Mock(return_value=[{"content": "ok"}]))
        core.processors["UniversalImageExtractor"] = Mock(
            process_file=Mock(return_value=[{"image_bytes": b"x", "image_format": "png", "position": {}}])
        )

        result = core.file_process(
            b"data",
            "report.pdf",
            chunking_strategy="basic",
            processor="Unstructured",
            model_type="multi_embedding",
        )

        chunks = _unpack_chunks(result)
        images = _unpack_images(result)
        assert len(chunks) == 1
        assert len(images) == 1
