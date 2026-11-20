# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from test.common.contract_stubs import install_business_constant_stubs, install_business_contract_stubs
from test.backend.management.import_patching import set_import_attribute
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def stub_project_modules(monkeypatch, tmp_path):
    # contracts.constants.environment
    const_mod = types.ModuleType("contracts.constants.environment")
    setattr(const_mod, "LIBREOFFICE_PROFILE_DIR", str(tmp_path / "lo-profile"))
    sys.modules["contracts.constants.environment"] = const_mod
    install_business_constant_stubs(const_mod)

    # contracts.agent
    model_mod = types.ModuleType("contracts.agent")
    install_business_contract_stubs(model_mod)

    # management.db.file.attachment
    attach_mod = types.ModuleType("management.db.file.attachment")
    sys.modules["management.db.file.attachment"] = attach_mod

    file_reads = types.ModuleType("infrastructure.file_reads")
    file_reads.read_attachment_size = lambda object_name: 777
    monkeypatch.setitem(sys.modules, file_reads.__name__, file_reads)

    # management.db.knowledge_base.repository
    knowledge_mod = types.ModuleType("management.db.knowledge_base.repository")
    setattr(
        knowledge_mod,
        "get_knowledge_record",
        lambda query=None: {"embedding_model_id": 42, "index_name": (query or {}).get("index_name")},
    )
    sys.modules["management.db.knowledge_base.repository"] = knowledge_mod

    # Ensure parent package exists
    if "database" not in sys.modules:
        pkg = types.ModuleType("database")
        setattr(pkg, "__path__", [])
        sys.modules["database"] = pkg
    setattr(sys.modules["database"], "attachment_db", attach_mod)
    setattr(sys.modules["database"], "knowledge_db", knowledge_mod)

    # management.services.permission.identity.session
    auth_mod = types.ModuleType("management.services.permission.identity.session")
    setattr(auth_mod, "get_current_user_id", lambda authorization: ("user-1", "tenant-1"))
    sys.modules["management.services.permission.identity.session"] = auth_mod

    # management.services.configuration.tenant.settings
    cfg_mod = types.ModuleType("management.services.configuration.tenant.settings")
    cfg_mgr = types.SimpleNamespace(load_config=lambda tenant_id: {"EMBEDDING_ID": "42"})
    setattr(cfg_mod, "tenant_config_manager", cfg_mgr)
    sys.modules["management.services.configuration.tenant.settings"] = cfg_mod

    # Yield to tests
    yield


@pytest.fixture()
def fmu(monkeypatch, request):
    # Import after stubbing collaborators
    from management.services.file import upload as fmu
    return fmu


# -------------------- get_file_size --------------------


def test_get_file_size_minio_ok_and_request_error(fmu, monkeypatch):
    # ok
    assert fmu.get_file_size("minio", "obj") == 777

    # request exception path
    class _ReqExc(Exception):
        pass

    fake_requests = types.SimpleNamespace(exceptions=types.SimpleNamespace(RequestException=_ReqExc))
    set_import_attribute(monkeypatch, fmu, "requests", fake_requests)

    def raise_req(*a, **k):
        raise _ReqExc("x")

    set_import_attribute(monkeypatch, fmu, "read_attachment_size", raise_req)
    assert fmu.get_file_size("minio", "obj") == 0


def test_get_file_size_local_exists_missing_and_error(fmu, monkeypatch):
    set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)
    set_import_attribute(monkeypatch, fmu.os.path, "getsize", lambda p: 1234)
    assert fmu.get_file_size("local", "/tmp/x") == 1234

    set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: False)
    assert fmu.get_file_size("local", "/tmp/x") == 0

    def boom(p):
        raise RuntimeError("e")

    set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)
    set_import_attribute(monkeypatch, fmu.os.path, "getsize", boom)
    assert fmu.get_file_size("local", "/tmp/x") == 0


def test_get_file_size_invalid_source_type(fmu):
    # Function catches NotImplementedError and returns 0
    assert fmu.get_file_size("http", "http://x") == 0


class TestConvertOfficeToPdf:
    """Test cases for convert_office_to_pdf function"""

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_uses_reused_profile_directory(self, fmu, monkeypatch, tmp_path):
        """Ensure command includes LO profile URI and uses a reusable profile directory."""
        mock_result = types.SimpleNamespace(returncode=0, stderr="", stdout="")
        captured_cmd = {}
        chmod_calls = []
        profile_dir = tmp_path / "lo-profile-test"
        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"

        def fake_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return mock_result

        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)
        set_import_attribute(monkeypatch, fmu.os.path, "basename", lambda p: "document.docx")
        set_import_attribute(monkeypatch, fmu, "LIBREOFFICE_PROFILE_DIR", str(profile_dir))
        set_import_attribute(monkeypatch, fmu.os, "chmod", lambda path, mode: chmod_calls.append((Path(path), mode)))
        monkeypatch.setattr("infrastructure.file_processing.conversion.run_conversion_process", fake_run)

        result = await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert result == str(output_dir / "document.pdf")
        cmd = captured_cmd.get("cmd", [])
        assert "--nolockcheck" in cmd
        assert f"-env:UserInstallation={profile_dir.resolve().as_uri()}" in cmd
        assert profile_dir.is_dir()
        assert chmod_calls == [(profile_dir.resolve(), 0o700)]

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_success(self, fmu, monkeypatch, tmp_path):
        """Test successful Office to PDF conversion"""
        import subprocess

        mock_result = types.SimpleNamespace(returncode=0, stderr="", stdout="")
        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"

        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)
        set_import_attribute(monkeypatch, fmu.os.path, "basename", lambda p: "document.docx")
        monkeypatch.setattr("infrastructure.file_processing.conversion.run_conversion_process", lambda *a, **k: mock_result)

        result = await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert result == str(output_dir / "document.pdf")

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_input_not_found(self, fmu, monkeypatch, tmp_path):
        """Test conversion failure when input file does not exist"""
        input_path = tmp_path / "nonexistent.docx"
        output_dir = tmp_path / "output"
        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: False)

        with pytest.raises(FileNotFoundError) as exc_info:
            await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert "Input file not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_libreoffice_error(self, fmu, monkeypatch, tmp_path):
        """Test conversion failure when LibreOffice returns error"""
        mock_result = types.SimpleNamespace(returncode=1, stderr="Error: LibreOffice crashed", stdout="")
        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"

        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)
        monkeypatch.setattr("infrastructure.file_processing.conversion.run_conversion_process", lambda *a, **k: mock_result)

        with pytest.raises(RuntimeError) as exc_info:
            await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert "Office to PDF conversion failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_timeout(self, fmu, monkeypatch, tmp_path):
        """Test conversion failure due to timeout"""
        import subprocess

        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"
        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)

        def raise_timeout(*a, **k):
            raise subprocess.TimeoutExpired(cmd='libreoffice', timeout=30)

        monkeypatch.setattr("infrastructure.file_processing.conversion.run_conversion_process", raise_timeout)

        with pytest.raises(TimeoutError) as exc_info:
            await fmu.convert_office_to_pdf(str(input_path), str(output_dir), timeout=30)

        assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_libreoffice_not_installed(self, fmu, monkeypatch, tmp_path):
        """Test conversion failure when LibreOffice is not installed"""
        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"
        set_import_attribute(monkeypatch, fmu.os.path, "exists", lambda p: True)

        def raise_file_not_found(*a, **k):
            raise FileNotFoundError("[Errno 2] No such file or directory: 'libreoffice'")

        monkeypatch.setattr("infrastructure.file_processing.conversion.run_conversion_process", raise_file_not_found)

        with pytest.raises(FileNotFoundError) as exc_info:
            await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert "LibreOffice is not installed" in str(exc_info.value)
        assert "not available in PATH" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_convert_office_to_pdf_output_not_found(self, fmu, monkeypatch, tmp_path):
        """Test conversion failure when output PDF is not generated"""
        mock_result = types.SimpleNamespace(returncode=0, stderr="", stdout="")
        input_path = tmp_path / "document.docx"
        output_dir = tmp_path / "output"

        def exists_side_effect(path):
            # Input file exists, output PDF does not
            if 'document.docx' in path:
                return True
            return False

        set_import_attribute(monkeypatch, fmu.os.path, "exists", exists_side_effect)
        set_import_attribute(monkeypatch, fmu.os.path, "basename", lambda p: "document.docx")
        monkeypatch.setattr("infrastructure.file_processing.conversion.run_conversion_process", lambda *a, **k: mock_result)

        with pytest.raises(RuntimeError) as exc_info:
            await fmu.convert_office_to_pdf(str(input_path), str(output_dir))

        assert "Converted PDF not found" in str(exc_info.value)
