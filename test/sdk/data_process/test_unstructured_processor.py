import io
import sys
import types
import pytest
from pytest_mock import MockFixture
from unittest.mock import Mock, MagicMock, patch

from sdk.nexent.data_process.unstructured_processor import UnstructuredProcessor


def setup_partition_mock(mocker: MockFixture, return_value):
    """Install a fake unstructured module chain and provide a mock partition.

    This avoids importing the real dependency and lets us assert calls.
    """
    fake_unstructured = types.ModuleType("unstructured")
    fake_partition_mod = types.ModuleType("unstructured.partition")
    fake_auto_mod = types.ModuleType("unstructured.partition.auto")

    mocker.patch.dict(sys.modules, {
        "unstructured": fake_unstructured,
        "unstructured.partition": fake_partition_mod,
        "unstructured.partition.auto": fake_auto_mod,
    })

    mock_partition = mocker.Mock(return_value=return_value)
    fake_auto_mod.partition = mock_partition
    return mock_partition


class TestUnstructuredProcessor:
    """Test suite for UnstructuredProcessor class"""

    @pytest.fixture
    def processor(self):
        """Create an UnstructuredProcessor instance for testing"""
        return UnstructuredProcessor()

    def test_init(self, processor):
        """Test UnstructuredProcessor initialization"""
        assert processor is not None
        assert processor.default_params["max_characters"] == 1536
        assert processor.default_params["new_after_n_chars"] == 1024
        assert processor.default_params["strategy"] == "fast"
        assert processor.default_params["skip_infer_table_types"] == []
        assert processor.default_params["task_id"] == ""

    def test_process_file(self, processor, mocker: MockFixture):
        """Test process_file method"""
        mock_process_file = mocker.patch.object(
            processor, "_process_file", return_value=[{"content": "test content"}]
        )

        file_data = b"test file data"
        filename = "test.pdf"

        result = processor.process_file(file_data, "basic", filename)

        assert len(result) == 1
        assert result[0]["content"] == "test content"
        mock_process_file.assert_called_once_with(
            file_data=file_data, chunking_strategy="basic", filename=filename
        )

    def test_process_file_with_additional_params(self, processor, mocker: MockFixture):
        """Test process_file with additional parameters"""
        mock_process_file = mocker.patch.object(
            processor, "_process_file", return_value=[{"content": "test"}]
        )

        file_data = b"data"
        filename = "test.pdf"
        additional_params = {"max_characters": 2000, "strategy": "hi_res"}

        result = processor.process_file(
            file_data, "by_title", filename, **additional_params
        )

        assert len(result) == 1
        mock_process_file.assert_called_once_with(
            file_data=file_data,
            chunking_strategy="by_title",
            filename=filename,
            max_characters=2000,
            strategy="hi_res",
        )

    def test_process_file_internal_success(self, processor, mocker: MockFixture):
        """Test internal _process_file method success"""
        # Mock element
        mock_element = Mock()
        mock_element.text = "Test content"
        mock_element.metadata = Mock()
        mock_element.metadata.to_dict = Mock(
            return_value={"languages": ["en"]})

        mock_partition = setup_partition_mock(
            mocker, return_value=[mock_element])

        file_data = b"test data"
        filename = "test.pdf"

        result = processor._process_file(file_data, "basic", filename)

        assert len(result) >= 1
        mock_partition.assert_called_once()

    def test_process_file_no_file_data(self, processor, mocker: MockFixture):
        """Test _process_file with no file data raises ValueError"""
        # Ensure import inside _process_file succeeds even when unstructured is absent
        setup_partition_mock(mocker, return_value=[])
        with pytest.raises(ValueError, match="Must provide binary file_data"):
            processor._process_file(b"", "basic", "test.pdf")

    def test_process_file_none_file_data(self, processor, mocker: MockFixture):
        """Test _process_file with None file data raises ValueError"""
        # Ensure import inside _process_file succeeds even when unstructured is absent
        setup_partition_mock(mocker, return_value=[])
        with pytest.raises(ValueError, match="Must provide binary file_data"):
            processor._process_file(None, "basic", "test.pdf")

    def test_merge_params_default(self, processor):
        """Test merging parameters with empty user params"""
        user_params = {}
        result = processor._merge_params(user_params)

        assert result["max_characters"] == 1536
        assert result["new_after_n_chars"] == 1024
        assert result["strategy"] == "fast"

    def test_merge_params_override(self, processor):
        """Test merging parameters with user overrides"""
        user_params = {"max_characters": 2000, "strategy": "hi_res"}
        result = processor._merge_params(user_params)

        assert result["max_characters"] == 2000
        assert result["strategy"] == "hi_res"
        assert result["new_after_n_chars"] == 1024  # Default preserved

    def test_merge_params_additional(self, processor):
        """Test merging parameters with additional user params"""
        user_params = {"max_characters": 3000, "custom_param": "value"}
        result = processor._merge_params(user_params)

        assert result["max_characters"] == 3000
        assert result["custom_param"] == "value"
        assert result["strategy"] == "fast"

    def test_prepare_partition_kwargs_basic(self, processor):
        """Test preparing partition kwargs with basic strategy"""
        file_data = b"test data"
        params = processor.default_params.copy()

        result = processor._prepare_partition_kwargs(
            file_data, "basic", params)

        assert result["max_characters"] == 1536
        assert result["new_after_n_chars"] == 1024
        assert result["strategy"] == "fast"
        assert result["chunking_strategy"] == "basic"
        assert isinstance(result["file"], io.BytesIO)

    def test_prepare_partition_kwargs_by_title(self, processor):
        """Test preparing partition kwargs with by_title strategy"""
        file_data = b"test data"
        params = processor.default_params.copy()

        result = processor._prepare_partition_kwargs(
            file_data, "by_title", params)

        assert result["chunking_strategy"] == "by_title"

    def test_prepare_partition_kwargs_none_strategy(self, processor):
        """Test preparing partition kwargs with none strategy"""
        file_data = b"test data"
        params = processor.default_params.copy()

        result = processor._prepare_partition_kwargs(file_data, "none", params)

        assert result["chunking_strategy"] is None

    def test_prepare_partition_kwargs_custom_params(self, processor):
        """Test preparing partition kwargs with custom parameters"""
        file_data = b"test data"
        params = {
            "max_characters": 2000,
            "new_after_n_chars": 1500,
            "strategy": "hi_res",
            "skip_infer_table_types": ["pdf"],
        }

        result = processor._prepare_partition_kwargs(
            file_data, "basic", params)

        assert result["max_characters"] == 2000
        assert result["new_after_n_chars"] == 1500
        assert result["strategy"] == "hi_res"
        assert result["skip_infer_table_types"] == ["pdf"]

    def test_process_elements_basic_strategy(self, processor, mocker: MockFixture):
        """Test processing elements with basic strategy"""
        mock_elements = [Mock(), Mock()]
        mock_create_chunked = mocker.patch.object(
            processor, "_create_chunked_documents", return_value=[{"content": "chunk1"}]
        )

        result = processor._process_elements(
            mock_elements, "basic", "test.pdf")

        assert len(result) == 1
        mock_create_chunked.assert_called_once_with(mock_elements, "test.pdf")

    def test_process_elements_by_title_strategy(self, processor, mocker: MockFixture):
        """Test processing elements with by_title strategy"""
        mock_elements = [Mock()]
        mock_create_chunked = mocker.patch.object(
            processor, "_create_chunked_documents", return_value=[{"content": "chunk"}]
        )

        result = processor._process_elements(
            mock_elements, "by_title", "test.pdf")

        assert len(result) == 1
        mock_create_chunked.assert_called_once()

    def test_process_elements_none_strategy(self, processor, mocker: MockFixture):
        """Test processing elements with none strategy"""
        mock_elements = [Mock()]
        mock_create_single = mocker.patch.object(
            processor, "_create_single_document", return_value=[{"content": "full doc"}]
        )

        result = processor._process_elements(mock_elements, "none", "test.pdf")

        assert len(result) == 1
        mock_create_single.assert_called_once_with(mock_elements, "test.pdf")

    def test_create_single_document(self, processor):
        """Test creating single document"""
        element1 = Mock()
        element1.text = "First paragraph"
        element1.metadata = Mock()
        element1.metadata.to_dict = Mock(return_value={"languages": ["en"]})

        element2 = Mock()
        element2.text = "Second paragraph"

        elements = [element1, element2]
        filename = "test.pdf"

        result = processor._create_single_document(elements, filename)

        assert len(result) == 1
        assert "First paragraph" in result[0]["content"]
        assert "Second paragraph" in result[0]["content"]
        assert result[0]["filename"] == "test.pdf"
        assert result[0]["language"] == "en"

    def test_create_single_document_no_language(self, processor):
        """Test creating single document without language info"""
        element1 = Mock()
        element1.text = "Content"
        element1.metadata = Mock()
        element1.metadata.to_dict = Mock(return_value={})

        elements = [element1]

        result = processor._create_single_document(elements, "test.pdf")

        assert len(result) == 1
        assert "language" not in result[0]

    def test_create_single_document_no_metadata(self, processor):
        """Test creating single document when element has no metadata"""
        element1 = Mock()
        element1.text = "Content"
        del element1.metadata

        elements = [element1]

        result = processor._create_single_document(elements, "test.pdf")

        assert len(result) == 1
        assert "language" not in result[0]

    def test_create_single_document_no_text_attribute(self, processor):
        """Test creating single document skips elements without text"""
        element1 = Mock()
        element1.text = "Content"
        element1.metadata = Mock()
        element1.metadata.to_dict = Mock(return_value={})

        element2 = Mock(spec=[])  # No text attribute

        elements = [element1, element2]

        result = processor._create_single_document(elements, "test.pdf")

        assert len(result) == 1
        assert "Content" in result[0]["content"]

    def test_create_chunked_documents(self, processor):
        """Test creating chunked documents"""
        element1 = Mock()
        element1.text = "Chunk 1 content"
        element1.metadata = Mock()
        element1.metadata.to_dict = Mock(return_value={
            "languages": ["en"],
            "page_number": 1,
        })

        element2 = Mock()
        element2.text = "Chunk 2 content"
        element2.metadata = Mock()
        element2.metadata.to_dict = Mock(return_value={"languages": ["en"]})

        elements = [element1, element2]
        filename = "test.pdf"

        result = processor._create_chunked_documents(elements, filename)

        assert len(result) == 2
        assert result[0]["content"] == "Chunk 1 content"
        assert result[0]["filename"] == "test.pdf"
        assert result[0]["metadata"]["chunk_index"] == 0
        assert result[0]["metadata"]["page_number"] == 1
        assert result[0]["language"] == "en"
        assert result[1]["content"] == "Chunk 2 content"
        assert result[1]["metadata"]["chunk_index"] == 1

    def test_create_chunked_documents_with_coordinates(self, processor):
        """Test creating chunked documents with coordinates metadata"""
        element = Mock()
        element.text = "Content"
        element.metadata = Mock()
        element.metadata.to_dict = Mock(return_value={
            "coordinates": {"x": 100, "y": 200}
        })

        elements = [element]

        result = processor._create_chunked_documents(elements, "test.pdf")

        assert len(result) == 1
        assert result[0]["metadata"]["coordinates"] == {"x": 100, "y": 200}

    def test_create_chunked_documents_no_text(self, processor):
        """Test creating chunked documents skips elements without text"""
        element1 = Mock()
        element1.text = "Content"
        element1.metadata = Mock()
        element1.metadata.to_dict = Mock(return_value={})

        element2 = Mock(spec=[])  # No text attribute

        elements = [element1, element2]

        result = processor._create_chunked_documents(elements, "test.pdf")

        assert len(result) == 1

    def test_create_chunked_documents_no_metadata(self, processor):
        """Test creating chunked documents when element has no metadata"""
        element = Mock()
        element.text = "Content"
        del element.metadata

        elements = [element]

        result = processor._create_chunked_documents(elements, "test.pdf")

        assert len(result) == 1
        assert "language" not in result[0]

    def test_create_chunked_documents_no_language(self, processor):
        """Test creating chunked documents without language info"""
        element = Mock()
        element.text = "Content"
        element.metadata = Mock()
        element.metadata.to_dict = Mock(return_value={})

        elements = [element]

        result = processor._create_chunked_documents(elements, "test.pdf")

        assert len(result) == 1
        assert "language" not in result[0]

    def test_get_supported_formats(self, processor):
        """Test getting supported formats"""
        result = processor.get_supported_formats()

        assert ".txt" in result
        assert ".pdf" in result
        assert ".docx" in result
        assert ".doc" in result
        assert ".html" in result
        assert ".htm" in result
        assert ".md" in result
        assert ".rtf" in result
        assert ".odt" in result
        assert ".pptx" in result
        assert ".ppt" in result
        assert len(result) == 11

    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("test.pdf", True),
            ("test.PDF", True),
            ("test.docx", True),
            ("test.txt", True),
            ("test.html", True),
            ("test.md", True),
            ("test.unknown", False),
            ("test.exe", False),
            ("", False),
        ]
    )
    def test_validate_file_format(self, processor, filename, expected):
        """Test file format validation"""
        result = processor.validate_file_format(filename)
        assert result == expected

    def test_validate_file_format_none(self, processor):
        """Test file format validation with None filename"""
        result = processor.validate_file_format(None)
        assert result is False

    def test_get_file_info_success(self, processor, mocker: MockFixture):
        """Test getting file info successfully"""
        mock_stat = Mock()
        mock_stat.st_size = 1024
        mock_stat.st_ctime = 1234567890.0
        mock_stat.st_mtime = 1234567891.0

        mocker.patch("os.path.exists", return_value=True)
        mocker.patch("os.stat", return_value=mock_stat)
        mocker.patch("os.path.basename", return_value="test.pdf")
        mocker.patch("os.path.splitext", return_value=("test", ".pdf"))

        result = processor.get_file_info("/path/to/test.pdf")

        assert result["filename"] == "test.pdf"
        assert result["extension"] == ".pdf"
        assert result["size_bytes"] == 1024
        assert result["is_supported"] is True
        assert result["created_time"] == 1234567890.0
        assert result["modified_time"] == 1234567891.0

    def test_get_file_info_file_not_exists(self, processor, mocker: MockFixture):
        """Test getting file info when file doesn't exist"""
        mocker.patch("os.path.exists", return_value=False)

        with pytest.raises(FileNotFoundError, match="File does not exist"):
            processor.get_file_info("/path/to/nonexistent.pdf")

    def test_get_file_info_unsupported_format(self, processor, mocker: MockFixture):
        """Test getting file info for unsupported format"""
        mock_stat = Mock()
        mock_stat.st_size = 2048
        mock_stat.st_ctime = 1234567890.0
        mock_stat.st_mtime = 1234567891.0

        mocker.patch("os.path.exists", return_value=True)
        mocker.patch("os.stat", return_value=mock_stat)
        mocker.patch("os.path.basename", return_value="test.exe")
        mocker.patch("os.path.splitext", return_value=("test", ".exe"))

        result = processor.get_file_info("/path/to/test.exe")

        assert result["filename"] == "test.exe"
        assert result["extension"] == ".exe"
        assert result["is_supported"] is False

    @pytest.mark.parametrize(
        "chunking_strategy,expected_call",
        [
            ("basic", "basic"),
            ("by_title", "by_title"),
            ("none", "none"),
        ]
    )
    def test_process_file_different_strategies(self, processor, mocker: MockFixture, chunking_strategy, expected_call):
        """Test processing file with different chunking strategies"""
        mock_element = Mock()
        mock_element.text = "Content"
        mock_element.metadata = Mock()
        mock_element.metadata.to_dict = Mock(return_value={})

        mock_partition = setup_partition_mock(
            mocker, return_value=[mock_element])

        result = processor._process_file(
            b"data", chunking_strategy, "test.pdf")

        assert len(result) >= 1
        # Verify partition was called with correct strategy
        call_kwargs = mock_partition.call_args[1]
        if chunking_strategy == "none":
            assert call_kwargs["chunking_strategy"] is None
        else:
            assert call_kwargs["chunking_strategy"] == expected_call

    def test_process_file_with_skip_infer_table_types(self, processor, mocker: MockFixture):
        """Test processing file with skip_infer_table_types parameter"""
        mock_element = Mock()
        mock_element.text = "Content"
        mock_element.metadata = Mock()
        mock_element.metadata.to_dict = Mock(return_value={})

        mock_partition = setup_partition_mock(
            mocker, return_value=[mock_element])

        result = processor._process_file(
            b"data", "basic", "test.pdf", skip_infer_table_types=["pdf", "image"]
        )

        assert len(result) >= 1
        call_kwargs = mock_partition.call_args[1]
        assert call_kwargs["skip_infer_table_types"] == ["pdf", "image"]

    def test_element_type_metadata(self, processor):
        """Test that element type is included in metadata"""
        element = Mock()
        element.text = "Content"
        element.metadata = Mock()
        element.metadata.to_dict = Mock(return_value={})

        elements = [element]

        result = processor._create_chunked_documents(elements, "test.pdf")

        assert len(result) == 1
        assert "element_type" in result[0]["metadata"]

    def test_process_file_with_empty_elements(self, processor, mocker: MockFixture):
        """Test processing file when partition returns empty elements"""
        mock_partition = setup_partition_mock(mocker, return_value=[])

        result = processor._process_file(b"data", "basic", "test.pdf")

        # Should return empty list or single empty document
        assert isinstance(result, list)

    def test_process_file_filename_none(self, processor, mocker: MockFixture):
        """Test processing file with None filename"""
        mock_element = Mock()
        mock_element.text = "Content"
        mock_element.metadata = Mock()
        mock_element.metadata.to_dict = Mock(return_value={})

        setup_partition_mock(mocker, return_value=[mock_element])

        result = processor._process_file(b"data", "basic", None)

        assert len(result) >= 1
        assert result[0]["filename"] is None

    def test_get_supported_formats_includes_new_types(self, processor):
        """Ensure that the new format has been added to the supported list."""
        formats = processor.get_supported_formats()
        assert ".json" in formats
        assert ".epub" in formats
        assert ".csv" in formats
        assert ".xml" in formats
        # HTML already supported
        assert ".html" in formats

    @pytest.mark.parametrize("filename", ["test.json", "test.epub", "test.csv", "test.xml", "test.html"])
    def test_validate_file_format_new_types(self, processor, filename):
        """Verify that the newly added file type can pass format verification."""
        assert processor.validate_file_format(filename) is True

    def test_process_json_file_special_handling(self, processor, mocker):
        """Test JSON files follow the dedicated _partition_json path"""
        json_data = b'{"name": "Alice", "age": 30}'

        # Patch at the actual source modules
        mock_json_chunk_cls = mocker.patch(
            "sdk.nexent.data_process.json_chunk_processor.JSONChunkProcessor"
        )
        mock_comp_elem_cls = mocker.patch(
            "unstructured.documents.elements.CompositeElement"
        )

        # Configure mocks
        mock_json_chunk_cls.return_value.split.return_value = [
            '{"name": "Alice"}', '{"age": 30}']

        def make_element(text):
            m = mocker.Mock(spec=["text"])
            m.text = text
            return m

        mock_comp_elem_cls.side_effect = make_element

        # Call the method
        result = processor._process_file(json_data, "basic", "data.json")

        # Assertions
        assert len(result) == 2
        assert result[0]["content"] == '{"name": "Alice"}'
        assert result[1]["content"] == '{"age": 30}'
        assert "language" not in result[0]

    def test_process_epub_csv_xml_html_uses_partition(self, processor, mocker: MockFixture):
        """Test EPUB/CSV/XML/HTML using unstructured.partition processing"""
        test_cases = [
            (b"EPUB content", "book.epub"),
            (b"name,age\nAlice,30", "data.csv"),
            (b"<root><item>value</item></root>", "data.xml"),
            (b"<html><body>Test</body></html>", "page.html"),
        ]

        for file_data, filename in test_cases:
            # Mock partition returns an element containing text
            mock_element = Mock()
            mock_element.text = "Mocked content from " + filename
            mock_element.metadata.to_dict.return_value = {}

            mock_partition = setup_partition_mock(
                mocker, return_value=[mock_element])

            result = processor._process_file(file_data, "basic", filename)

            # Verify that the partition function is called
            mock_partition.assert_called_once()
            call_kwargs = mock_partition.call_args[1]
            assert isinstance(call_kwargs["file"], io.BytesIO)
            assert call_kwargs["chunking_strategy"] == "basic"

            # Validation result structure
            assert len(result) == 1
            assert result[0]["content"] == "Mocked content from " + filename
            assert result[0]["filename"] == filename

    def test_process_json_with_custom_max_characters(self, processor, mocker):
        json_data = b'{"long_field": "' + b"x" * 2000 + b'"}'

        # Patch both classes
        mock_comp_elem_cls = mocker.patch(
            "unstructured.documents.elements.CompositeElement"
        )
        mock_json_chunk_cls = mocker.patch(
            "sdk.nexent.data_process.json_chunk_processor.JSONChunkProcessor"
        )

        # Configure the split return value of JSONChunkProcessor
        mock_json_chunk_instance = mock_json_chunk_cls.return_value
        mock_json_chunk_instance.split.return_value = [
            '{"long_field": "' + 'x' * 300 + '"}',
            '"' + 'x' * 1700 + '"}'
        ]  # The simulation is split into two parts (to comply with max_characters=500)

        def make_element(text):
            m = mocker.Mock(spec=["text"])
            m.text = text
            return m

        mock_comp_elem_cls.side_effect = make_element

        result = processor.process_file(
            json_data,
            chunking_strategy="basic",
            filename="large.json",
            max_characters=500
        )

        assert len(result) == 2  # or > 0
        assert "language" not in result[0]

    def test_process_unsupported_format_rejected(self, processor):
        """Ensure that unsupported formats (such as .exe) are still rejected"""
        assert processor.validate_file_format("malware.exe") is False
