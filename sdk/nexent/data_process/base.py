# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


STRUCTURE_METADATA_FIELDS = (
    "page_number", "coordinates", "text_as_html", "category_depth", "parent_id", "languages", "is_continuation",
)


class FileProcessor(ABC):
    def process_structure(self, file_data: bytes, filename: str, **params) -> List[Dict]:
        """Format renderers preserve their existing non-retrieval output."""
        return self.process_file(file_data, "none", filename=filename, **params)

    @abstractmethod
    def process_file(
        self, file_data: bytes, chunking_strategy: str, filename: Optional[str], path_or_url: Optional[str], **params
    ) -> List[Dict]:
        pass
