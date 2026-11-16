# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Build selection assigns parsing and CLIP dependencies to their owning roles."""

import pytest
import tomllib

from test.backend.deploy.test_gateway_image import bash_run
from test.backend.deploy.test_service_image_sources import ROOT


@pytest.mark.parametrize("role", ["management", "runtime"])
@pytest.mark.parametrize("variant", ["cpu", "gpu"])
def test_role_build_variant_is_explicit(role, variant):
    result = bash_run(
        f"bash deploy/images/build.sh --{role} --dependency-variant {variant} --version latest --load --dry-run"
    )
    suffix = "-gpu" if variant == "gpu" else ""
    assert f"-t nexent/nexent-{role}{suffix}:latest" in result
    assert f"--target {role}" in result
    assert f"MODEL_DEPENDENCY_VARIANT={variant}" in result


def test_role_dependency_extras_exclude_flower_and_runtime_ocr():
    extras = tomllib.loads(
        (ROOT / "backend/pyproject.toml").read_text(encoding="utf-8")
    )["project"]["optional-dependencies"]
    assert "nexent[data_process,performance]" in extras["management-cleanse"]
    assert any(value.startswith("celery") for value in extras["management-cleanse"])
    assert not any(value.startswith("flower") for value in extras["management-cleanse"])
    assert "unstructured==0.18.14" in extras["runtime-knowledge"]
    assert any(value.startswith("torch") for value in extras["runtime-images"])
    assert any(value.startswith("transformers") for value in extras["runtime-images"])
    assert all(
        "data_process" not in value and "inference" not in value
        for name in ("runtime-knowledge", "runtime-images")
        for value in extras[name]
    )


def test_management_packages_all_immutable_migrations():
    dockerfile = (ROOT / "deploy/images/dockerfiles/main/Dockerfile").read_text(
        encoding="utf-8"
    )
    management = dockerfile.split("FROM backend-common AS management\n", 1)[1].split(
        "\nFROM ", 1
    )[0]
    assert "COPY deploy/sql/migrations /opt/deploy/sql/migrations" in management


@pytest.mark.parametrize(
    "role,weights",
    [
        ("management", "pytorch_model.bin"),
        ("management", "model.safetensors"),
        ("runtime", "pytorch_model.bin"),
    ],
)
def test_model_asset_check_requires_only_the_selected_role(tmp_path, role, weights):
    # Source only function definitions, leaving the real CLI path to the build-selection tests.
    script = (ROOT / "deploy/images/build.sh").read_text(encoding="utf-8")
    helpers = script[
        script.index("model_asset_file() {") : script.index("prepare_model_assets() {")
    ]
    assets = tmp_path / "assets"
    required = ["nltk_data/tokenizers/punkt_tab/english/collocations.tab"]
    if role == "management":
        required += [
            f"table-transformer-structure-recognition/{weights}",
            "yolox/yolox_l0.05.onnx",
            "yolox/config.json",
        ]
    else:
        required += [
            "clip-vit-base-patch32/config.json",
            "clip-vit-base-patch32/pytorch_model.bin",
        ]
    for name in required:
        target = assets / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"synthetic-asset")
    if weights == "model.safetensors":
        (
            assets / "table-transformer-structure-recognition/pytorch_model.bin"
        ).write_text("version https://git-lfs.github.com/spec/v1\n", encoding="utf-8")
    path = assets.as_posix()
    assert (
        bash_run(
            helpers + f'\nmodel_assets_complete "{path}" {role} && echo accepted'
        ).strip()
        == "accepted"
    )
    # A weight pointer must not be mistaken for a usable model.
    (assets / required[-2]).write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:fixture\nsize 100\n",
        encoding="utf-8",
    )
    assert (
        bash_run(
            helpers
            + f'\nif model_assets_complete "{path}" {role}; then echo wrong; else echo rejected; fi'
        ).strip()
        == "rejected"
    )
