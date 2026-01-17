"""
Analyze Excel ICD Tool

Processes Excel files to add ICD codes for surgery names by calling an external API.
Reads Excel files, extracts surgery names, calls search_icd API for each surgery,
and adds ICD codes as a new column.
"""
import io
import logging
from typing import List, Optional

import httpx
import pandas as pd
from pydantic import Field
from smolagents.tools import Tool

from nexent.core import MessageObserver
from nexent.core.utils.observer import ProcessType
from nexent.core.utils.tools_common_message import ToolCategory, ToolSign
from nexent.storage import MinIOStorageClient
from nexent.multi_modal.load_save_object import LoadSaveObjectManager


logger = logging.getLogger("analyze_excel_icd_tool")


class AnalyzeExcelIcdTool(Tool):
    """Tool for analyzing Excel files and adding ICD codes for surgery names"""

    name = "analyze_excel_icd"
    description = (
        "Process Excel files to add ICD codes for surgery names. "
        "Reads Excel files from S3 URLs (s3://bucket/key or /bucket/key), HTTP, and HTTPS URLs. "
        "For each row's 'surgery' column, calls the search_icd API to get ICD codes "
        "and adds them as a new 'icd_code' column. Returns the path to the processed Excel file."
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
        ),
        api_base_url: str = Field(
            description="Base URL for the search_icd API",
            default="http://localhost:5024",
            exclude=True
        )
    ):
        super().__init__()
        self.storage_client = storage_client
        self.observer = observer
        self.api_base_url = api_base_url
        self.mm = LoadSaveObjectManager(storage_client=self.storage_client)

        self.running_prompt_zh = "正在处理Excel文件并添加ICD编码..."
        self.running_prompt_en = "Processing Excel file and adding ICD codes..."

        # Define DataFrame to Excel bytes transformer
        def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
            """Convert DataFrame to Excel bytes"""
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            return output.getvalue()

        # Dynamically apply the load_object and save_object decorators to forward method
        self.forward = self.mm.save_object(
            output_names=["processed_excel"],
            output_transformers=[dataframe_to_excel_bytes]
        )(self.mm.load_object(input_names=["file_url"])(self._forward_impl))

        # Wrap the forward method to transform the returned S3 URL to frontend download URL
        original_forward = self.forward

        def url_transforming_forward(file_url: str) -> str:
            """Forward method with URL transformation"""
            s3_url = original_forward(file_url)
            # Convert S3 URL to frontend download URL
            if isinstance(s3_url, str) and s3_url.startswith("s3://"):
                # Extract object name from s3://bucket/object_name
                parts = s3_url.replace("s3://", "").split("/", 1)
                if len(parts) == 2:
                    object_name = parts[1]
                    # Ensure .xlsx extension is present
                    if not object_name.endswith('.xlsx'):
                        object_name += '.xlsx'
                    return f"http://localhost:3000/api/file/download/{object_name}?download=stream"
            return s3_url

        self.forward = url_transforming_forward

    def _forward_impl(
        self,
        file_url: bytes,
    ) -> pd.DataFrame:
        """
        Process Excel file and add ICD codes.

        Note: This method is wrapped by load_object and save_object decorators which:
        - Downloads the Excel from S3 URL, HTTP URL, or HTTPS URL and passes bytes
        - Converts the returned DataFrame to Excel bytes and uploads to storage

        Args:
            file_url: Excel file bytes converted from URL by the decorator.

        Returns:
            pd.DataFrame: Processed DataFrame with ICD codes added.
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
            logger.info("Processing Excel file and adding ICD codes")

            # Step 1: Read Excel file with pandas
            df = self._read_excel_file(file_url)

            # Step 2: Validate surgery column exists
            if 'surgery' not in df.columns:
                raise ValueError("Excel file must contain a 'surgery' column")

            # Step 3: Process each surgery and get ICD codes
            icd_codes = []
            for index, row in df.iterrows():
                surgery_name = str(row['surgery']).strip() if pd.notna(row['surgery']) else ""
                if surgery_name:
                    try:
                        icd_code = self._get_icd_code(surgery_name)
                        icd_codes.append(icd_code)
                        logger.info(f"Processed row {index + 1}: surgery='{surgery_name}' -> icd_code='{icd_code}'")
                    except Exception as e:
                        logger.error(f"Failed to get ICD code for surgery '{surgery_name}' at row {index + 1}: {e}")
                        icd_codes.append("")  # Empty string for failed API calls
                else:
                    icd_codes.append("")

            # Step 4: Add ICD code column
            df['icd_code'] = icd_codes

            logger.info(f"Successfully processed Excel file with {len(df)} rows. Added icd_code column.")
            return df

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

    def _get_icd_code(self, surgery_name: str) -> str:
        """
        Call search_icd API to get ICD code for surgery name.

        Args:
            surgery_name: Name of the surgery

        Returns:
            str: ICD code from API response
        """
        api_url = f"{self.api_base_url}/api/search_icd"

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(api_url, params={"surgery_name": surgery_name})

            if response.status_code == 200:
                result = response.json()
                # Extract ICD code from data.label field
                data = result.get("data", {})
                icd_code = data[0].get("label", "")
                logger.info(f"API call successful for '{surgery_name}': got ICD code '{icd_code}'")
                return icd_code
            else:
                error_detail = response.json().get('detail', 'unknown error') if response.headers.get(
                    'content-type', '').startswith('application/json') else response.text
                logger.error(f"API call failed for '{surgery_name}' (status {response.status_code}): {error_detail}")
                raise Exception(f"API call failed: {error_detail}")

        except Exception as e:
            logger.error(f"Failed to call search_icd API for '{surgery_name}': {str(e)}")
            raise
