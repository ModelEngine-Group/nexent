"""
Analyze Excel Tool

Processes Excel files and converts them to JSON format.
Reads Excel files from S3 URLs (s3://bucket/key or /bucket/key), HTTP, and HTTPS URLs,
extracts data and outputs as a standard JSON string.
"""
import io
import json
import logging
from typing import Optional

import pandas as pd
from pydantic import Field
from smolagents.tools import Tool

from nexent.core import MessageObserver
from nexent.core.utils.observer import ProcessType
from nexent.core.utils.tools_common_message import ToolCategory, ToolSign
from nexent.storage import MinIOStorageClient
from nexent.multi_modal.load_save_object import LoadSaveObjectManager


logger = logging.getLogger("analyze_excel_tool")


class AnalyzeExcelTool(Tool):
    """Tool for analyzing Excel files and converting them to JSON format"""

    name = "analyze_excel"
    description = (
        "Process Excel files and convert them to JSON format. "
        "Reads Excel files from S3 URLs (s3://bucket/key or /bucket/key), HTTP, and HTTPS URLs. "
        "Extracts all data and returns a JSON string representation of the Excel content."
    )

    inputs = {
        "file_url": {
            "type": "string",
            "description": "Excel file URL (S3, HTTP, or HTTPS). Supports s3://bucket/key, /bucket/key, http://, and https:// URLs."
        }
    }
    output_type = "string"
    category = ToolCategory.MULTIMODAL.value
    tool_sign = ToolSign.MULTIMODAL_OPERATION.value

    def __init__(
        self,
        storage_client: Optional[MinIOStorageClient] = Field(
            description="Storage client for downloading files from S3 URLs、HTTP URLs、HTTPS URLs.",
            default=None,
            exclude=True
        ),
        observer: MessageObserver = Field(
            description="Message observer",
            default=None,
            exclude=True
        )
    ):
        super().__init__()
        self.storage_client = storage_client
        self.observer = observer
        self.mm = LoadSaveObjectManager(storage_client=self.storage_client)

        self.running_prompt_zh = "正在处理Excel文件并转换为JSON格式..."
        self.running_prompt_en = "Processing Excel file and converting to JSON format..."

        # Dynamically apply the load_object decorator to forward method
        self.forward = self.mm.load_object(input_names=["file_url"])(self._forward_impl)

    def _forward_impl(
        self,
        file_url: bytes,
    ) -> str:
        """
        Process Excel file and convert to JSON string.

        Note: This method is wrapped by load_object decorator which:
        - Downloads the Excel from S3 URL, HTTP URL, or HTTPS URL and passes bytes

        Args:
            file_url: Excel file bytes converted from URL by the decorator.

        Returns:
            str: JSON string representation of the Excel data.
        """
        # Send tool run message
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if file_url is None:
            raise ValueError("file_url cannot be None")

        if not isinstance(file_url, bytes):
            raise ValueError("file_url must be bytes")

        try:
            logger.info("Processing Excel file and converting to JSON")

            # Step 1: Read Excel file with pandas
            df = self._read_excel_file(file_url)

            # Step 2: Convert DataFrame to JSON string
            json_string = self._dataframe_to_json(df)

            logger.info(f"Successfully processed Excel file with {len(df)} rows and {len(df.columns)} columns")
            return json_string

        except Exception as e:
            logger.error(f"Error processing Excel file: {str(e)}", exc_info=True)
            error_msg = f"Error processing Excel file: {str(e)}"
            raise Exception(error_msg)

    def _read_excel_file(self, file_bytes: bytes) -> pd.DataFrame:
        """
        Read Excel file from bytes using pandas.

        Args:
            file_bytes: Excel file content as bytes

        Returns:
            pd.DataFrame: DataFrame containing Excel data
        """
        try:
            file_obj = io.BytesIO(file_bytes)
            df = pd.read_excel(file_obj, engine='openpyxl')
            logger.info(f"Successfully read Excel file with {len(df)} rows and {len(df.columns)} columns")
            return df
        except Exception as e:
            logger.error(f"Failed to read Excel file: {e}")
            raise Exception(f"Failed to read Excel file: {str(e)}")

    def _dataframe_to_json(self, df: pd.DataFrame) -> str:
        """
        Convert DataFrame to JSON string.

        Args:
            df: pandas DataFrame to convert

        Returns:
            str: JSON string representation of the DataFrame
        """
        try:
            # Convert DataFrame to list of dictionaries (records format)
            # Handle NaN values by converting them to None
            data = []
            for _, row in df.iterrows():
                row_dict = {}
                for col in df.columns:
                    value = row[col]
                    # Convert NaN to None, keep other values as is
                    if pd.isna(value):
                        row_dict[col] = None
                    else:
                        row_dict[col] = value
                data.append(row_dict)

            # Create JSON structure with metadata
            json_data = {
                "columns": list(df.columns),
                "rows": len(df),
                "data": data
            }

            json_string = json.dumps(json_data, ensure_ascii=False, indent=2)
            logger.info(f"Successfully converted DataFrame to JSON with {len(data)} records")
            return json_string

        except Exception as e:
            logger.error(f"Failed to convert DataFrame to JSON: {e}")
            raise Exception(f"Failed to convert DataFrame to JSON: {str(e)}")