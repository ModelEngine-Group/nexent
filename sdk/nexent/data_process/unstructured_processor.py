import io
import os
from typing import Dict, List, Optional

from .base import FileProcessor


class UnstructuredProcessor(FileProcessor):
    """
    Unified generic file processing class that supports in-memory file processing.
    Uses unified internal methods to reduce code duplication.
    """

    def __init__(self):
        """Initialize generic file processor"""
        self.default_params = {
            "max_characters": 1536,
            "new_after_n_chars": 1024,
            "strategy": "fast",
            "skip_infer_table_types": [],
            "task_id": "",
        }

    def process_file(self, file_data: bytes, chunking_strategy: str, filename: str, **params) -> List[Dict]:
        """
        Process file in memory (e.g., file fetched from MinIO) and return structured chunks.

        Args:
            file_data: File byte data
            chunking_strategy: Chunking strategy ("basic", "by_title", "none")
            filename: Filename
            **params: Additional processing parameters

        Returns:
            List of dictionaries containing processing results
        """
        return self._process_file(
            file_data=file_data, chunking_strategy=chunking_strategy, filename=filename, **params
        )

    def _process_file(
        self, file_data: bytes, chunking_strategy: str = "basic", filename: Optional[str] = None, **params
    ) -> List[Dict]:
        """
        Core file processing method that uniformly processes files from byte data.

        Args:
            file_data: File byte data
            chunking_strategy: Chunking strategy
            filename: Filename
            **params: Additional parameters

        Returns:
            List of standardized chunk dictionaries
        """
        from unstructured.partition.auto import partition

        # Validate input parameters
        if not file_data:
            raise ValueError("Must provide binary file_data")

        # Merge parameters
        processed_params = self._merge_params(params)

        # Prepare partition parameters
        partition_kwargs = self._prepare_partition_kwargs(
            file_data, chunking_strategy, processed_params)

        # Execute file partitioning
        elements = partition(**partition_kwargs)

        # Process results
        return self._process_elements(elements, chunking_strategy, filename)

    def _merge_params(self, user_params: Dict) -> Dict:
        """
        Merge default parameters with user-provided parameters.

        Args:
            user_params: User-provided parameters

        Returns:
            Merged parameter dictionary
        """
        merged_params = self.default_params.copy()
        merged_params.update(user_params)
        return merged_params

    def _prepare_partition_kwargs(self, file_data: bytes, chunking_strategy: str, params: Dict) -> Dict:
        """
        Prepare parameters required for unstructured.partition.

        Args:
            file_data: File byte data
            chunking_strategy: Chunking strategy
            params: Processing parameters

        Returns:
            Parameter dictionary for partition function
        """
        # Base parameters
        partition_kwargs = {
            "max_characters": params["max_characters"],
            "new_after_n_chars": params["new_after_n_chars"],
            "strategy": params["strategy"],
            "skip_infer_table_types": params["skip_infer_table_types"],
            "chunking_strategy": chunking_strategy if chunking_strategy != "none" else None,
        }

        # Set file input source
        partition_kwargs["file"] = io.BytesIO(file_data)

        return partition_kwargs

    def _process_elements(self, elements: List, chunking_strategy: str, filename: Optional[str]) -> List[Dict]:
        """
        Process partitioned elements to generate standardized document chunks.

        Args:
            elements: List of elements after unstructured partitioning
            chunking_strategy: Chunking strategy
            filename: Filename

        Returns:
            List of standardized document chunks
        """
        if chunking_strategy == "none":
            return self._create_single_document(elements, filename)
        else:
            return self._create_chunked_documents(elements, filename)

    def _create_single_document(self, elements: List, filename: Optional[str]) -> List[Dict]:
        """
        Create a single document (no chunking).

        Args:
            elements: List of document elements
            filename: Filename

        Returns:
            List containing a single document
        """
        full_text = "\n\n".join(
            [el.text for el in elements if hasattr(el, "text")])

        doc = {
            "content": full_text,
            "filename": filename,
        }

        # Add language information (if available)
        if elements and hasattr(elements[0], "metadata"):
            languages = elements[0].metadata.to_dict().get("languages")
            if languages:
                doc["language"] = languages[0]

        return [doc]

    def _create_chunked_documents(self, elements: List, filename: Optional[str]) -> List[Dict]:
        """
        Create chunked documents.

        Args:
            elements: List of document elements
            filename: Filename

        Returns:
            List of chunked documents
        """
        result = []

        for index, element in enumerate(elements):
            if not hasattr(element, "text"):
                continue

            doc = {
                "content": element.text,
                "filename": filename,
                "metadata": {"chunk_index": index, "element_type": type(element).__name__},
            }

            # Add language information
            if hasattr(element, "metadata"):
                metadata = element.metadata.to_dict()
                languages = metadata.get("languages")
                if languages:
                    doc["language"] = languages[0]

                # Add other useful metadata
                if "page_number" in metadata:
                    doc["metadata"]["page_number"] = metadata["page_number"]
                if "coordinates" in metadata:
                    doc["metadata"]["coordinates"] = metadata["coordinates"]

            result.append(doc)

        return result

    def get_supported_formats(self) -> List[str]:
        """
        Return list of supported file formats.

        Returns:
            List of supported file formats
        """
        return [".txt", ".pdf", ".docx", ".doc", ".html", ".htm", ".md", ".rtf", ".odt", ".pptx", ".ppt"]

    def validate_file_format(self, filename: str) -> bool:
        """
        Validate if file format is supported.

        Args:
            filename: Filename

        Returns:
            Whether the format is supported
        """
        if not filename:
            return False

        _, ext = os.path.splitext(filename.lower())
        return ext in self.get_supported_formats()

    def get_file_info(self, file_path: str) -> Dict:
        """
        Get basic information about the file.

        Args:
            file_path: File path

        Returns:
            File information dictionary
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File does not exist: {file_path}")

        stat = os.stat(file_path)
        filename = os.path.basename(file_path)
        _, ext = os.path.splitext(filename)

        return {
            "filename": filename,
            "extension": ext.lower(),
            "size_bytes": stat.st_size,
            "is_supported": self.validate_file_format(filename),
            "created_time": stat.st_ctime,
            "modified_time": stat.st_mtime,
        }
