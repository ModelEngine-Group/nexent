"""
Save Excel Tool

Converts JSON data to Excel format and saves it.
Receives JSON string, converts it to DataFrame, saves as Excel file,
and returns a downloadable URL path.
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


logger = logging.getLogger("save_excel_tool")


class SaveExcelTool(Tool):
    """Tool for converting JSON data to Excel format and saving it"""

    name = "save_excel"
    description = (
        "Convert JSON data to Excel format and save it. "
        "Receives JSON string containing Excel data structure, "
        "converts it to Excel file, and returns a downloadable URL path."
    )

    inputs = {
        "json_data": {
            "type": "string",
            "description": "JSON string containing Excel data in the format: {\"columns\": [...], \"data\": [...]}"
        }
    }
    output_type = "string"
    category = ToolCategory.MULTIMODAL.value
    tool_sign = ToolSign.MULTIMODAL_OPERATION.value

    def __init__(
        self,
        storage_client: Optional[MinIOStorageClient] = Field(
            description="Storage client for uploading files to storage.",
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

        self.running_prompt_zh = "正在将JSON数据转换为Excel文件并保存..."
        self.running_prompt_en = "Converting JSON data to Excel file and saving..."

        # Define DataFrame to Excel bytes transformer
        def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
            """Convert DataFrame to Excel bytes"""
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            return output.getvalue()

        # Dynamically apply the save_object decorator to forward method
        self.forward = self.mm.save_object(
            output_names=["excel_file"],
            output_transformers=[dataframe_to_excel_bytes]
        )(self._forward_impl)

        # Wrap the forward method to transform the returned S3 URL to frontend download URL
        original_forward = self.forward

        def url_transforming_forward(json_data: str) -> str:
            """Forward method with URL transformation"""
            s3_url = original_forward(json_data)
            # Convert S3 URL to frontend download URL
            if isinstance(s3_url, str) and s3_url.startswith("s3://"):
                # Extract object name from s3://bucket/object_name
                parts = s3_url.replace("s3://", "").split("/", 1)
                if len(parts) == 2:
                    object_name = parts[1]
                    # Ensure .xlsx extension is present
                    if not object_name.endswith('.xlsx'):
                        object_name += '.xlsx'
                    return f"/api/file/download/{object_name}?download=stream"
            return s3_url

        self.forward = url_transforming_forward

    def _forward_impl(
        self,
        json_data: str,
    ) -> pd.DataFrame:
        """
        Convert JSON string to DataFrame for saving as Excel.

        Note: This method is wrapped by save_object decorator which:
        - Converts the returned DataFrame to Excel bytes and uploads to storage

        Args:
            json_data: JSON string containing Excel data structure.

        Returns:
            pd.DataFrame: DataFrame to be saved as Excel file.
        """
        # Send tool run message
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)

        if json_data is None or json_data == "":
            raise ValueError("json_data cannot be None or empty")

        if not isinstance(json_data, str):
            raise ValueError("json_data must be a string")

        try:
            logger.info("Converting JSON data to DataFrame for Excel saving")

            # Step 1: Parse JSON string
            df = self._json_to_dataframe(json_data)

            logger.info(f"Successfully converted JSON to DataFrame with {len(df)} rows and {len(df.columns)} columns")
            return df

        except Exception as e:
            logger.error(f"Error converting JSON to Excel: {str(e)}", exc_info=True)
            error_msg = f"Error converting JSON to Excel: {str(e)}"
            raise Exception(error_msg)

    def _json_to_dataframe(self, json_string: str) -> pd.DataFrame:
        """
        Convert JSON string to pandas DataFrame.

        Args:
            json_string: JSON string in the format {"columns": [...], "data": [...]}

        Returns:
            pd.DataFrame: DataFrame containing the data
        """
        try:
            # Parse JSON string
            json_data = json.loads(json_string)

            # Validate JSON structure
            if not isinstance(json_data, dict):
                raise ValueError("JSON data must be an object")

            if "data" not in json_data:
                raise ValueError("JSON data must contain a 'data' field")

            data = json_data["data"]
            if not isinstance(data, list):
                raise ValueError("'data' field must be an array")

            if len(data) == 0:
                # Handle empty data case
                columns = json_data.get("columns", [])
                df = pd.DataFrame(columns=columns)
            else:
                # Create DataFrame from data
                df = pd.DataFrame(data)

                # Reorder columns if columns field is provided
                if "columns" in json_data and isinstance(json_data["columns"], list):
                    expected_columns = json_data["columns"]
                    # Only reorder if all expected columns exist in the DataFrame
                    if all(col in df.columns for col in expected_columns):
                        df = df[expected_columns]

            logger.info(f"Successfully converted JSON to DataFrame with {len(df)} rows and {len(df.columns)} columns")
            return df

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON format: {e}")
            raise ValueError(f"Invalid JSON format: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to convert JSON to DataFrame: {e}")
            raise Exception(f"Failed to convert JSON to DataFrame: {str(e)}")
