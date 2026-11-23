"""Filesystem locations for Benchmark data kept outside the source repository."""

from __future__ import annotations

import os
from pathlib import Path


GENERIC_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = GENERIC_DIR.parents[2]
DEFAULT_BENCHMARK_DATA_ROOT = REPO_ROOT.parent / "nexent-data" / "benchmark"
BENCHMARK_DATA_ROOT = Path(
    os.environ.get(
        "NEXENT_BENCHMARK_DATA_ROOT",
        str(DEFAULT_BENCHMARK_DATA_ROOT),
    )
).expanduser().resolve()
DATASET_ROOT = BENCHMARK_DATA_ROOT / "datasets"
ARTIFACT_ROOT = BENCHMARK_DATA_ROOT / "artifacts"


def ensure_benchmark_data_directories() -> None:
    """Create external Benchmark data directories when the caller needs writes."""
    DATASET_ROOT.mkdir(parents=True, exist_ok=True)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
