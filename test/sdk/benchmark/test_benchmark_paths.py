from pathlib import Path

from sdk.benchmark.generic.common import benchmark_paths


def test_default_benchmark_data_is_outside_repository():
    expected = (
        benchmark_paths.REPO_ROOT.parent
        / "nexent-data"
        / "benchmark"
    ).resolve()

    assert benchmark_paths.DEFAULT_BENCHMARK_DATA_ROOT == expected
    assert benchmark_paths.DATASET_ROOT == (
        benchmark_paths.BENCHMARK_DATA_ROOT / "datasets"
    )
    assert benchmark_paths.ARTIFACT_ROOT == (
        benchmark_paths.BENCHMARK_DATA_ROOT / "artifacts"
    )
    assert not benchmark_paths.DEFAULT_BENCHMARK_DATA_ROOT.is_relative_to(
        benchmark_paths.REPO_ROOT
    )


def test_repository_dataset_directory_keeps_only_tracked_code():
    repository_dataset_dir = (
        Path(__file__).resolve().parents[3]
        / "sdk"
        / "benchmark"
        / "generic"
        / "datasets"
    )

    assert not list(repository_dataset_dir.glob("*.jsonl"))
