import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from .extract_image import UniversalImageExtractor
from io import BytesIO

from .base import FileProcessor
from .file_splitter import FileSplitter
from .openpyxl_processor import OpenPyxlProcessor
from .unstructured_processor import UnstructuredProcessor


logger = logging.getLogger("data_process.core")
logger.setLevel(logging.DEBUG)


class DataProcessCore:
    """
    Core data processing functionality class with distributed processing capabilities

    Supported file types:
    - Excel files: .xlsx, .xls
    - Generic files: .txt, .pdf, .docx, .doc, .html, .htm, .md, .rtf, .odt, .pptx, .ppt, .epub, .xml, .csv, .json

    Supported input methods:
    - In-memory byte data
    """

    # Supported Excel file extensions
    EXCEL_EXTENSIONS = {".xlsx", ".xls"}

    # Supported chunking strategies
    CHUNKING_STRATEGIES = {"basic", "by_title", "none"}
    
    EXTRACT_IMAGE_EXTENSIONS = {".pdf", ".doc",
                                ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}

    # Supported processors
    PROCESSORS = {"Unstructured", "OpenPyxl", "UniversalImageExtractor"}

    # Supported split extensions (exclude ppt/pptx/html)
    SPLIT_EXTENSIONS = {
        ".csv",
        ".epub",
        ".xlsx",
        ".xls",
        ".json",
        ".md",
        ".pdf",
        ".txt",
        ".xml",
        ".doc",
        ".docx",
    }

    def __init__(self):
        """
        Initialize the core data processing component
        """
        self.processors: Dict[str, FileProcessor] = {
            "Unstructured": UnstructuredProcessor(),
            "OpenPyxl": OpenPyxlProcessor(),
            "UniversalImageExtractor": UniversalImageExtractor(),
            "FileSplitter": FileSplitter(),
        }
        logger.debug("DataProcessCore initialization completed")

    def file_process(
        self,
        file_data: bytes,
        filename: str,
        chunking_strategy: str = "basic",
        processor: Optional[str] = None,
        **params,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Facade pattern that automatically detects file type and processes files

        Args:
            file_data: File content byte data (for in-memory processing)
            filename: Filename
            chunking_strategy: Chunking strategy, options: "basic", "by_title", "none"
            processor: Optional processor to use. If None, auto-detects from filename.
                       Options: "Unstructured", "OpenPyxl"
            **params: Additional processing parameters

        Returns:
            Tuple[List[Dict], List[Dict]]: (chunks, images_info)
            chunks: List of processed chunks, each dictionary contains the following fields:
            - content: Text content
            - filename: Filename
            - metadata: Metadata (optional, includes chunk_index, source_type, etc.)
            - language: Language identifier (optional)
            images_info: List of extracted image metadata dicts (may be empty)

        Raises:
            ValueError: Invalid parameters
            ImportError: Missing required dependencies
        """
        # Parameter validation
        self._validate_parameters(chunking_strategy, processor)

        # Select appropriate processor
        if processor:
            processor_name = processor
            _, extractor = self._select_processor_by_filename(filename, params)
        else:
            processor_name, extractor = self._select_processor_by_filename(
                filename, params)

        processor_instance = self.processors.get(processor_name)
        extract_image_processor_instance = (
            self.processors.get(extractor) if extractor else None
        )

        if not processor_instance:
            raise ValueError(f"Unsupported processor: {processor_name}")
        
        if extract_image_processor_instance:
            img_info = extract_image_processor_instance.process_file(
                file_data, chunking_strategy, filename, **params)
        else:
            img_info = []

        # Process in-memory file
        logger.info(
            f"Processing in-memory file: {filename} with {processor_name} processor")
        try:
            return processor_instance.process_file(file_data, chunking_strategy, filename=filename, **params), img_info
        except Exception as e:
            logger.error(f"File processing failed for {filename}: {str(e)}")
            raise

    def file_split(
        self,
        file_data: bytes,
        filename: str,
        splitter: Optional[str] = None,
        **params,
    ) -> List[BytesIO]:
        """
        Split file into smaller parts using the unified splitter

        Args:
            file_data: File content byte data
            filename: Filename
            splitter: Optional splitter name (reserved for future use)
            **params: Additional splitter parameters (e.g., max_size, encoding, libreoffice_path)

        Returns:
            List of BytesIO parts

        Raises:
            ValueError: Invalid parameters
            RuntimeError: Split failed
        """
        _, ext = os.path.splitext(filename.lower())
        if ext not in self.SPLIT_EXTENSIONS:
            return [BytesIO(file_data)]

        splitter_name = splitter or "FileSplitter"
        splitter_instance = self.processors.get(splitter_name)
        if not splitter_instance:
            logger.error(f"Splitter not found: {splitter_name}")
            return [BytesIO(file_data)]

        max_size = params.pop("max_size", 5 * 1024 * 1024)

        try:
            parts = splitter_instance.file_process(file_data, filename, max_size=max_size, **params)
            if not isinstance(parts, list) or not all(isinstance(p, BytesIO) for p in parts):
                logger.error("Invalid split result format: expected List[BytesIO]")
                return [BytesIO(file_data)]
            logger.info(f"Successfully split file: {filename}")
            return parts
        except Exception as e:
            logger.error(f"File split failed for {filename}: {str(e)}")
            return [BytesIO(file_data)]

    def _validate_parameters(self, chunking_strategy: str, processor: Optional[str]) -> None:
        """Validate input parameters"""
        # Check chunking strategy
        if chunking_strategy not in self.CHUNKING_STRATEGIES:
            raise ValueError(
                f"Unsupported chunking strategy: {chunking_strategy}. "
                f"Supported strategies: {', '.join(self.CHUNKING_STRATEGIES)}"
            )

        # Check processor type if provided
        if processor and processor not in self.PROCESSORS:
            raise ValueError(
                f"Unsupported processor type: {processor}. Supported types: {', '.join(self.PROCESSORS)}")

        logger.debug(
            f"Parameter validation passed: chunking_strategy={chunking_strategy}, processor={processor}")

    def _select_processor_by_filename(
        self, filename: str, params: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Optional[str]]:
        """Selects a processor based on the file extension."""
        _, file_extension = os.path.splitext(filename)
        file_extension = file_extension.lower()

        extract_image = None
        model_type = params.get("model_type")
        if model_type == "multi_embedding" and file_extension in self.EXTRACT_IMAGE_EXTENSIONS:
            extract_image = "UniversalImageExtractor"
        if file_extension in self.EXCEL_EXTENSIONS:
            return "OpenPyxl", extract_image
        else:
            return "Unstructured", extract_image

    def get_supported_file_types(self) -> Dict[str, List[str]]:
        """
        Get supported file types

        Returns:
            Dictionary containing supported file types:
            - excel: List of Excel file extensions
            - generic: List of generic file extensions
        """
        unstructured_processor = self.processors.get("Unstructured")

        generic_formats = []
        if isinstance(unstructured_processor, UnstructuredProcessor) and hasattr(
            unstructured_processor, "get_supported_formats"
        ):
            generic_formats = unstructured_processor.get_supported_formats()
        else:
            generic_formats = [
                ".txt",
                ".pdf",
                ".docx",
                ".doc",
                ".html",
                ".htm",
                ".md",
                ".rtf",
                ".odt",
                ".pptx",
                ".ppt",
                ".epub",
                ".json",
                ".xml",
                ".csv",
            ]

        return {"excel": list(self.EXCEL_EXTENSIONS), "generic": generic_formats}

    def get_supported_strategies(self) -> List[str]:
        """
        Get supported chunking strategies

        Returns:
            List of supported chunking strategies
        """
        return list(self.CHUNKING_STRATEGIES)

    def get_supported_processors(self) -> List[str]:
        """
        Get supported processor types

        Returns:
            List of supported processor types
        """
        return list(self.PROCESSORS)

    def validate_file_type(self, filename: str) -> bool:
        """
        Validate if file type is supported

        Args:
            filename: Filename

        Returns:
            Whether the file type is supported
        """
        if not filename:
            return False

        _, ext = os.path.splitext(filename.lower())
        supported_types = self.get_supported_file_types()

        return ext in supported_types["excel"] or ext in supported_types["generic"]

    def get_processor_info(self, filename: str) -> Dict[str, str]:
        """
        Get processor information for the file

        Args:
            filename: Filename

        Returns:
            Processor information dictionary containing:
            - processor_type: Processor type ("excel" or "generic")
            - file_extension: File extension
            - is_supported: Whether it's supported
        """
        _, ext = os.path.splitext(filename.lower()) if filename else ("", "")

        processor_type = "excel" if ext in self.EXCEL_EXTENSIONS else "generic"
        is_supported = self.validate_file_type(filename)

        return {"processor_type": processor_type, "file_extension": ext, "is_supported": str(is_supported)}
