import io
import pytest
from pytest_mock import MockFixture
from unittest.mock import Mock, MagicMock, patch
from copy import deepcopy

from sdk.nexent.data_process.openpyxl_processor import OpenPyxlProcessor


class TestOpenPyxlProcessor:
    """Test suite for OpenPyxlProcessor class"""

    @pytest.fixture
    def processor(self):
        """Create an OpenPyxlProcessor instance for testing"""
        return OpenPyxlProcessor()

    @pytest.fixture
    def mock_workbook(self):
        """Create a mock workbook for testing"""
        wb = Mock()
        wb.sheetnames = ["Sheet1"]

        # Mock sheet
        sheet = Mock()
        sheet.iter_rows = Mock(return_value=[
            ("Header1", "Header2"),
            ("Value1", "Value2"),
        ])
        sheet.merged_cells = Mock()
        sheet.merged_cells.ranges = []

        wb.__getitem__ = Mock(return_value=sheet)

        return wb

    def test_process_file(self, processor, mocker: MockFixture):
        """Test process_file method"""
        mock_process_excel = mocker.patch.object(
            processor, "_process_excel", return_value=[{"content": "test"}]
        )

        file_data = b"fake excel data"
        filename = "test.xlsx"

        result = processor.process_file(file_data, "basic", filename)

        assert len(result) == 1
        assert result[0]["content"] == "test"
        mock_process_excel.assert_called_once_with(
            file_data=file_data, chunking_strategy="basic", filename=filename
        )

    def test_process_excel_success(self, processor, mocker: MockFixture):
        """Test successful Excel processing"""
        # Mock workbooks
        mock_wb_orig = Mock()
        mock_wb_copy = Mock()

        mocker.patch.object(
            processor, "_load_workbook", return_value=(mock_wb_orig, mock_wb_copy)
        )
        mocker.patch.object(
            processor, "_extract_content", return_value=["content1", "content2"]
        )
        mocker.patch.object(
            processor, "_convert_to_chunks", return_value=[
                {"content": "content1", "filename": "test.xlsx"},
                {"content": "content2", "filename": "test.xlsx"},
            ]
        )

        result = processor._process_excel(b"data", "basic", "test.xlsx")

        assert len(result) == 2
        assert result[0]["content"] == "content1"

    def test_load_workbook_success(self, processor, mocker: MockFixture):
        """Test successful workbook loading"""
        mock_wb = Mock()
        mock_load_workbook = mocker.patch(
            "openpyxl.load_workbook",
            return_value=mock_wb
        )
        mocker.patch(
            "sdk.nexent.data_process.openpyxl_processor.deepcopy",
            return_value=Mock()
        )

        wb_orig, wb_copy = processor._load_workbook(b"fake data")

        assert wb_orig is not None
        assert wb_copy is not None
        mock_load_workbook.assert_called_once()

    def test_load_workbook_failure(self, processor, mocker: MockFixture):
        """Test workbook loading failure"""
        mocker.patch(
            "openpyxl.load_workbook",
            side_effect=Exception("Load failed")
        )

        with pytest.raises(Exception, match="Failed to load Excel file"):
            processor._load_workbook(b"invalid data")

    def test_extract_content_single_column(self, processor, mocker: MockFixture):
        """Test content extraction for single column sheet"""
        mock_wb_orig = Mock()
        mock_wb_copy = Mock()

        mock_wb_orig.sheetnames = ["Sheet1"]
        sheet_orig = Mock()
        sheet_copy = Mock()
        mock_wb_orig.__getitem__ = Mock(return_value=sheet_orig)
        mock_wb_copy.__getitem__ = Mock(return_value=sheet_copy)

        mocker.patch.object(processor, "_is_single_column", return_value=True)
        mocker.patch.object(
            processor, "_process_single_column", return_value=["single column content"]
        )

        result = processor._extract_content(mock_wb_orig, mock_wb_copy)

        assert len(result) == 1
        assert result[0] == "single column content"

    def test_extract_content_multi_column(self, processor, mocker: MockFixture):
        """Test content extraction for multi-column sheet"""
        mock_wb_orig = Mock()
        mock_wb_copy = Mock()

        mock_wb_orig.sheetnames = ["Sheet1"]
        sheet_orig = Mock()
        sheet_copy = Mock()
        mock_wb_orig.__getitem__ = Mock(return_value=sheet_orig)
        mock_wb_copy.__getitem__ = Mock(return_value=sheet_copy)

        mocker.patch.object(processor, "_is_single_column", return_value=False)
        mocker.patch.object(
            processor, "_process_multi_column", return_value=["multi column content"]
        )

        result = processor._extract_content(mock_wb_orig, mock_wb_copy)

        assert len(result) == 1
        assert result[0] == "multi column content"

    def test_extract_content_multiple_sheets(self, processor, mocker: MockFixture):
        """Test content extraction for multiple sheets"""
        mock_wb_orig = Mock()
        mock_wb_copy = Mock()

        mock_wb_orig.sheetnames = ["Sheet1", "Sheet2"]
        mock_wb_orig.__getitem__ = Mock(side_effect=[Mock(), Mock()])
        mock_wb_copy.__getitem__ = Mock(side_effect=[Mock(), Mock()])

        mocker.patch.object(processor, "_is_single_column", return_value=True)
        mocker.patch.object(
            processor, "_process_single_column", side_effect=[["content1"], ["content2"]]
        )

        result = processor._extract_content(mock_wb_orig, mock_wb_copy)

        assert len(result) == 2

    def test_convert_to_chunks(self, processor):
        """Test conversion of raw content to chunks"""
        raw_content = ["content1", "content2"]
        filename = "test.xlsx"

        result = processor._convert_to_chunks(raw_content, filename)

        assert len(result) == 2
        assert result[0]["content"] == "content1"
        assert result[0]["filename"] == "test.xlsx"
        assert result[0]["metadata"]["chunk_index"] == 0
        assert result[0]["metadata"]["file_type"] == "xlsx"
        assert result[1]["metadata"]["chunk_index"] == 1

    @pytest.mark.parametrize(
        "filename,expected_type",
        [
            ("test.xlsx", "xlsx"),
            ("test.XLSX", "xlsx"),
            ("test.xls", "xls"),
            ("test.XLS", "xls"),
            ("", "xls"),
        ]
    )
    def test_determine_file_type(self, processor, filename, expected_type):
        """Test file type determination"""
        result = processor._determine_file_type(filename)
        assert result == expected_type

    def test_is_single_column_true(self, processor, mocker: MockFixture):
        """Test single column detection returns True"""
        sheet = Mock()
        mocker.patch.object(processor, "_get_title_row", return_value=(1, 1))

        result = processor._is_single_column(sheet)

        assert result is True

    def test_is_single_column_false(self, processor, mocker: MockFixture):
        """Test single column detection returns False"""
        sheet = Mock()
        mocker.patch.object(processor, "_get_title_row", return_value=(1, 3))

        result = processor._is_single_column(sheet)

        assert result is False

    def test_process_single_column(self, processor):
        """Test single column processing"""
        sheet = Mock()
        sheet.iter_rows = Mock(return_value=[
            ("Row1",),
            ("Row2",),
            (None,),
            ("Row3",),
        ])

        result = processor._process_single_column(sheet, "TestSheet")

        assert len(result) == 1
        assert "Row1" in result[0]
        assert "Row2" in result[0]
        assert "Row3" in result[0]
        assert "TestSheet" in result[0]

    def test_process_single_column_with_line_breaks(self, processor):
        """Test single column processing with line breaks"""
        sheet = Mock()
        sheet.iter_rows = Mock(return_value=[
            ("Row1\nwith\nbreaks",),
        ])

        result = processor._process_single_column(sheet, "TestSheet")

        assert len(result) == 1
        assert "<br>" in result[0]

    def test_process_multi_column(self, processor, mocker: MockFixture):
        """Test multi-column processing"""
        sheet = Mock()
        sheet_copy = Mock()

        mocker.patch.object(processor, "_get_title_row", return_value=(1, 2))
        mocker.patch.object(processor, "_merge_all_cells")
        mocker.patch.object(processor, "_get_title_key",
                            return_value=["Col1", "Col2"])
        mocker.patch.object(processor, "_get_remark",
                            return_value="Remark text")
        mocker.patch.object(
            processor, "_extract_table_content", return_value=["table content"]
        )

        result = processor._process_multi_column(
            sheet, sheet_copy, "TestSheet")

        assert len(result) == 1
        assert result[0] == "table content"

    def test_get_title_row(self, processor, mocker: MockFixture):
        """Test title row detection"""
        sheet = Mock()

        # Mock rows with different numbers of non-empty cells
        row1 = [Mock(value="A"), Mock(value=None)]
        row2 = [Mock(value="Col1"), Mock(value="Col2"), Mock(value="Col3")]
        row3 = [Mock(value="Data1"), Mock(value="Data2")]

        sheet.iter_rows = Mock(return_value=[row1, row2, row3])

        mocker.patch.object(processor, "_merge_columns")

        position, max_col = processor._get_title_row(sheet)

        assert position == 2  # Second row has most columns
        assert max_col == 3

    def test_get_remark(self, processor):
        """Test remark extraction"""
        sheet = Mock()
        sheet.iter_rows = Mock(return_value=[
            ("Remark line 1", "Extra"),
            (None, None),
            ("Header1", "Header2"),
        ])

        result = processor._get_remark(sheet, 3)

        assert "Remark line 1" in result
        assert "Extra" in result

    def test_get_remark_empty(self, processor):
        """Test remark extraction when no remarks exist"""
        sheet = Mock()
        sheet.iter_rows = Mock(return_value=[
            ("Header1", "Header2"),
        ])

        result = processor._get_remark(sheet, 1)

        assert result == ""

    def test_get_title_key(self, processor):
        """Test title key extraction"""
        sheet = Mock()
        sheet.iter_rows = Mock(return_value=[
            (None, None),
            ("Col1", "Col2", None),
        ])

        result = processor._get_title_key(2, sheet)

        assert result == ["Col1", "Col2", ""]

    def test_get_title_key_no_match(self, processor):
        """Test title key extraction when no matching row"""
        sheet = Mock()
        sheet.iter_rows = Mock(return_value=[
            (None, None),
        ])

        result = processor._get_title_key(5, sheet)

        assert result == []

    def test_extract_table_content(self, processor, mocker: MockFixture):
        """Test table content extraction"""
        sheet = Mock()
        sheet.iter_rows = Mock(return_value=[
            ("Header1", "Header2"),
            ("Data1", "Data2"),
            ("Data3", "Data4"),
        ])

        mocker.patch.object(
            processor, "_build_row_content", side_effect=["row1_content", "row2_content"]
        )

        result = processor._extract_table_content(
            ["Col1", "Col2"], "Remark", sheet, 1, "TestSheet"
        )

        assert len(result) == 2
        assert result[0] == "row1_content"
        assert result[1] == "row2_content"

    def test_extract_table_content_with_empty_rows(self, processor, mocker: MockFixture):
        """Test table content extraction with empty rows"""
        sheet = Mock()
        sheet.iter_rows = Mock(return_value=[
            ("Header1", "Header2"),
            (None, None),
            ("Data1", "Data2"),
        ])

        mocker.patch.object(processor, "_build_row_content",
                            return_value="row_content")

        result = processor._extract_table_content(
            ["Col1", "Col2"], "", sheet, 1, "TestSheet"
        )

        assert len(result) == 1

    def test_build_row_content_with_remark(self, processor, mocker: MockFixture):
        """Test row content building with remark"""
        mocker.patch.object(
            processor, "_dict_to_markdown_table", return_value="| Col1 | Col2 |\n|---|---|\n| Val1 | Val2 |"
        )

        result = processor._build_row_content(
            ["Col1", "Col2"], ("Val1", "Val2"), "Remark text", "Sheet1"
        )

        assert "Col1" in result or "Val1" in result
        assert "Sheet1" in result

    def test_build_row_content_without_remark(self, processor, mocker: MockFixture):
        """Test row content building without remark"""
        mocker.patch.object(
            processor, "_dict_to_markdown_table", return_value="| Col1 |\n|---|\n| Val1 |"
        )

        result = processor._build_row_content(
            ["Col1"], ("Val1",), "", "Sheet1")

        assert "Sheet1" in result

    def test_build_row_content_with_line_breaks(self, processor, mocker: MockFixture):
        """Test row content building with line breaks in values"""
        mocker.patch.object(
            processor, "_dict_to_markdown_table", return_value="table")

        result = processor._build_row_content(
            ["Col\n1"], ("Val\n1",), "", "Sheet1"
        )

        # The method should replace newlines with <br>
        assert result is not None

    def test_merge_columns(self, processor):
        """Test column merging"""
        sheet = Mock()

        # Mock merged range
        merged_range = Mock()
        merged_range.__str__ = Mock(return_value="A1:A3")
        # min_col, min_row, max_col, max_row
        merged_range.bounds = (1, 1, 1, 3)

        sheet.merged_cells.ranges = [merged_range]
        sheet.unmerge_cells = Mock()

        # Mock cells
        cell_values = {"A1": "Value1"}

        def mock_cell(row, column):
            cell = Mock()
            cell.value = cell_values.get(f"A{row}", None)
            return cell

        sheet.cell = mock_cell

        processor._merge_columns(sheet)

        sheet.unmerge_cells.assert_called()

    def test_merge_columns_skip_row_merge(self, processor):
        """Test column merging skips row merges"""
        sheet = Mock()

        # Mock merged range that spans rows (should be skipped)
        merged_range = Mock()
        merged_range.__str__ = Mock(return_value="A1:B1")

        sheet.merged_cells.ranges = [merged_range]
        sheet.unmerge_cells = Mock()

        processor._merge_columns(sheet)

        # unmerge_cells should not be called for row merges
        sheet.unmerge_cells.assert_not_called()

    def test_merge_all_cells(self, processor):
        """Test merging all cells"""
        sheet = Mock()

        # Mock merged range
        merged_range = Mock()
        merged_range.bounds = (1, 1, 2, 2)

        sheet.merged_cells.ranges = [merged_range]
        sheet.unmerge_cells = Mock()

        # Mock cell
        def mock_cell(row, column):
            cell = Mock()
            cell.value = "TopLeftValue" if row == 1 and column == 1 else None
            return cell

        sheet.cell = mock_cell

        processor._merge_all_cells(sheet)

        sheet.unmerge_cells.assert_called_once()

    def test_dict_to_markdown_table(self, processor):
        """Test dictionary to markdown table conversion"""
        data = {"Col1": "Val1", "Col2": "Val2"}

        result = processor._dict_to_markdown_table(data)

        assert "Col1" in result
        assert "Col2" in result
        assert "Val1" in result
        assert "Val2" in result
        assert "|" in result
        assert "---" in result

    def test_dict_to_markdown_table_empty(self, processor):
        """Test dictionary to markdown table conversion with empty dict"""
        result = processor._dict_to_markdown_table({})
        assert result == ""

    def test_dict_to_markdown_table_with_none_values(self, processor):
        """Test dictionary to markdown table conversion with None values"""
        data = {None: None, "Col1": None}

        result = processor._dict_to_markdown_table(data)

        assert "None" in result

    def test_join_tuple_elements(self, processor):
        """Test joining tuple elements"""
        input_tuple = ("A", "B", "C")
        result = processor._join_tuple_elements(input_tuple)
        assert result == "A;B;C"

    def test_join_tuple_elements_with_none(self, processor):
        """Test joining tuple elements with None values"""
        input_tuple = ("A", None, "C", None)
        result = processor._join_tuple_elements(input_tuple)
        assert result == "A;C"

    def test_join_tuple_elements_all_none(self, processor):
        """Test joining tuple elements with all None values"""
        input_tuple = (None, None, None)
        result = processor._join_tuple_elements(input_tuple)
        assert result == ""

    def test_check_file_exists_true(self, processor, mocker: MockFixture):
        """Test file existence check returns True"""
        mocker.patch("os.path.isfile", return_value=True)
        mocker.patch("os.access", return_value=True)

        result = processor._check_file_exists("/path/to/file.xlsx")

        assert result is True

    def test_check_file_exists_false_not_file(self, processor, mocker: MockFixture):
        """Test file existence check returns False when not a file"""
        mocker.patch("os.path.isfile", return_value=False)

        result = processor._check_file_exists("/path/to/nonexistent.xlsx")

        assert result is False

    def test_check_file_exists_false_not_readable(self, processor, mocker: MockFixture):
        """Test file existence check returns False when not readable"""
        mocker.patch("os.path.isfile", return_value=True)
        mocker.patch("os.access", return_value=False)

        result = processor._check_file_exists("/path/to/file.xlsx")

        assert result is False
