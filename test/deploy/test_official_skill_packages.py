"""Contracts for bundled official skill archives."""

import stat
from pathlib import Path
from zipfile import ZipFile


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ANTHROPIC_SKILLS = {
    "docx",
    "pdf",
    "pptx",
    "xlsx",
    "canvas-design",
    "frontend-design",
    "slack-gif-creator",
    "mcp-builder",
    "web-artifacts-builder",
    "skill-creator",
}
WORKBENCH_OFFICIAL_SKILLS = {
    "docx",
    "pdf",
    "pptx",
    "xlsx",
    "canvas-design",
    "analyze-image",
}


def test_workbench_official_skill_packages_exist():
    """UT-BE-WMA-015."""
    archive_dir = (
        REPOSITORY_ROOT
        / "deploy"
        / "docker"
        / "assets"
        / "official-skills-zip"
    )

    assert {
        path.stem
        for path in archive_dir.glob("*.zip")
        if path.stem in WORKBENCH_OFFICIAL_SKILLS
    } == WORKBENCH_OFFICIAL_SKILLS


def test_analyze_image_skill_declares_standard_tool_dependency():
    """UT-BE-WMA-020: analyze-image resolves through normal Skill metadata."""
    archive_path = (
        REPOSITORY_ROOT
        / "deploy"
        / "docker"
        / "assets"
        / "official-skills-zip"
        / "analyze-image.zip"
    )

    with ZipFile(archive_path) as archive:
        skill_path = next(
            name
            for name in archive.namelist()
            if name.replace("\\", "/") == "analyze-image/SKILL.md"
        )
        skill_guide = archive.read(skill_path).decode("utf-8")

    assert "allowed-tools:" in skill_guide
    assert "  - analyze_image" in skill_guide


def test_anthropic_official_skill_packages_are_clean_and_installable():
    archive_dir = (
        REPOSITORY_ROOT
        / "deploy"
        / "docker"
        / "assets"
        / "official-skills-zip"
    )

    for skill_name in ANTHROPIC_SKILLS:
        archive_path = archive_dir / f"{skill_name}.zip"
        assert archive_path.is_file(), skill_name

        with ZipFile(archive_path) as archive:
            names = archive.namelist()
            entries = archive.infolist()
            skill_guide = archive.read(f"{skill_name}/SKILL.md").decode("utf-8")

        assert f"{skill_name}/LICENSE.txt" in names
        assert f"name: {skill_name}" in skill_guide
        assert all(name.startswith(f"{skill_name}/") for name in names)
        assert all("\\" not in name for name in names)
        assert all(".." not in Path(name).parts for name in names)
        assert all("/__pycache__/" not in f"/{name}" for name in names)
        assert all("/outputs/" not in f"/{name}" for name in names)
        assert all(not stat.S_ISLNK(entry.external_attr >> 16) for entry in entries)


def test_web_artifacts_builder_contains_nexent_compatibility_fixes():
    archive_path = (
        REPOSITORY_ROOT
        / "deploy"
        / "docker"
        / "assets"
        / "official-skills-zip"
        / "web-artifacts-builder.zip"
    )
    with ZipFile(archive_path) as archive:
        skill_guide = archive.read("web-artifacts-builder/SKILL.md").decode("utf-8")
        init_script = archive.read(
            "web-artifacts-builder/scripts/init-artifact.sh"
        ).decode("utf-8")
        bundle_script = archive.read(
            "web-artifacts-builder/scripts/bundle-artifact.sh"
        ).decode("utf-8")

    assert 'run_skill_script("web-artifacts-builder"' in skill_guide
    assert "favicon\\.svg" in init_script
    assert 'PROJECT_DIR="${1:-.}"' in bundle_script
    assert 'OUTPUT_NAME="${2:-bundle.html}"' in bundle_script


def test_create_docx_uses_command_line_params():
    archive_path = (
        REPOSITORY_ROOT
        / "deploy"
        / "docker"
        / "assets"
        / "official-skills-zip"
        / "create-docx.zip"
    )
    with ZipFile(archive_path) as archive:
        skill_guide = archive.read("create-docx/SKILL.md").decode("utf-8")
        generate_script = archive.read(
            "create-docx/scripts/generate_docx.py"
        ).decode("utf-8")

    assert "params=f" in skill_guide
    assert "--spec" in skill_guide
    assert "ArgumentParser" in generate_script
    assert 'add_argument("--spec"' in generate_script


def test_create_excel_uses_command_line_params():
    archive_path = (
        REPOSITORY_ROOT
        / "deploy"
        / "docker"
        / "assets"
        / "official-skills-zip"
        / "create-excel.zip"
    )
    with ZipFile(archive_path) as archive:
        skill_guide = archive.read("create-excel/SKILL.md").decode("utf-8")
        scripts = {
            name: archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("create-excel/scripts/")
            and name.endswith(".py")
        }

    assert "params=f" in skill_guide
    assert "--spec" in skill_guide
    assert scripts
    for name, script in scripts.items():
        assert "ArgumentParser" in script, name


def test_other_official_skills_do_not_bundle_run_skill_scripts():
    archive_dir = (
        REPOSITORY_ROOT
        / "deploy"
        / "docker"
        / "assets"
        / "official-skills-zip"
    )
    script_skill_archives = {
        "create-docx.zip",
        "create-excel.zip",
        "docx.zip",
        "pdf.zip",
        "pptx.zip",
        "xlsx.zip",
        "mcp-builder.zip",
        "skill-creator.zip",
    }

    for archive_path in archive_dir.glob("*.zip"):
        if archive_path.name in script_skill_archives:
            continue
        with ZipFile(archive_path) as archive:
            python_scripts = [
                name
                for name in archive.namelist()
                if "/scripts/" in name.replace("\\", "/") and name.endswith(".py")
            ]
        assert python_scripts == [], archive_path.name
