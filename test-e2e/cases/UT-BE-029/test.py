"""D1 contracts for tags, HITL, model catalog, logging and sandbox cleanup."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError


STAGE = pytest.mark.stage("D1")








@STAGE
@pytest.mark.case_id("UT-BE-029")
def test_hybrid_log_handler_rotates_on_size_and_keeps_machine_readable_output(tmp_path) -> None:
    from utils.logging_utils import HybridRotatingFileHandler

    target = tmp_path / "runtime.log"
    handler = HybridRotatingFileHandler(
        target, when="midnight", interval=1, backupCount=2, maxBytes=32, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger(f"nexent-test-{id(handler)}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    try:
        logger.info("first-visible-line")
        logger.info("second-visible-line")
        logger.info("third-visible-line")
    finally:
        handler.close()
        logger.removeHandler(handler)
    files = list(tmp_path.glob("runtime.log*"))
    assert 2 <= len(files) <= 3
    combined = "\n".join(item.read_text(encoding="utf-8") for item in files)
    assert "third-visible-line" in combined
    assert "\x1b[" not in combined


