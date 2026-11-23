# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read only the execution results authorized to the current Agent instance."""
from smolagents.tools import Tool


class ReadExecutionOutputTool(Tool):
    _nexent_execute_on_host = True
    name = "read_execution_output"
    description = "Read original execution output using OUTPUT_REF, with Unicode character offset and a bounded length."
    inputs = {
        "output_ref": {"type": "string", "description": "Exact OUTPUT_REF from a compact execution result."},
        "offset": {"type": "integer", "description": "Unicode character offset; initially zero.", "nullable": True},
        "max_chars": {"type": "integer", "description": "Maximum characters, up to 16000.", "nullable": True},
    }
    output_type = "string"

    def __init__(self, history, owner, on_read):
        super().__init__()
        self.history = history
        self.owner = owner
        self.on_read = on_read

    def forward(self, output_ref: str, offset: int = 0, max_chars: int = 4000) -> str:
        result = self.history.read(self.owner, output_ref, offset, max_chars)
        self.on_read()
        return result

    def context_item(self, metadata):
        """Describe the executable reader in the same resource list as other tools."""
        from ..agents.context.models import ContextItemInput

        return ContextItemInput(
            id=f"tool:{self.name}", type="tool",
            content={"name": self.name, "description": self.description,
                     "inputs": self.inputs, "output_type": self.output_type},
            source=(f"tool:{self.name}",), priority=50, metadata=dict(metadata),
        )
