"""D1 unit contracts for sandboxed skill-script execution (UT-SDK-018).

The Docker execution target is a recording stub: no container is started and
no network is touched.  The trust boundary under test (resolve_skill_script)
and the staging/execution/return protocol of SandboxSkillScriptRunner are the
real SDK implementations.
"""

from __future__ import annotations

import io
import json
import logging
import tarfile

import pytest


STAGE = pytest.mark.stage("D1")


class _ExecResult:
    def __init__(self, exit_code: int, output) -> None:
        self.exit_code = exit_code
        self.output = output


class _StubContainer:
    """Records every control-plane and execution call made against Docker."""

    def __init__(self, results: list[_ExecResult] | None = None) -> None:
        self.exec_calls: list[tuple[list, dict]] = []
        self.archives: list[tuple[str, bytes]] = []
        self._results = list(results or [])

    def exec_run(self, command, **kwargs):
        self.exec_calls.append((list(command), kwargs))
        if kwargs.get("demux") is True:
            if not self._results:
                raise AssertionError("Missing scripted execution result")
            return self._results.pop(0)
        return _ExecResult(0, b"")

    def put_archive(self, path, data):
        self.archives.append((path, data))
        return True

    def success_commands(self) -> list[list]:
        # exec_run calls issued through _run_container_command (mkdir/chmod/rm)
        # always return exit code 0; the script exec passes demux=True.
        return [command for command, kwargs in self.exec_calls if "demux" in kwargs]


class _StubExecutor:
    def __init__(self, container, backend: str = "docker") -> None:
        self.container = container
        self._nexent_backend = backend


def _skill_manager(tmp_path):
    from nexent.skills.skill_manager import SkillManager

    SkillManager._instance = None
    root = tmp_path / "skills"
    tenant = root / "tenant-a"
    skill = tenant / "report-maker"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: report-maker\ndescription: sandbox runner fixture\n"
        "script_outputs:\n  scripts/report.py:\n    kind: file\n    mime_types:\n    - text/plain\n---\n"
        "run scripts/report.py\n",
        encoding="utf-8",
    )
    (skill / "scripts" / "report.py").write_text("print('sandbox-report')\n", encoding="utf-8")
    (skill / "scripts" / "echo.sh").write_text("echo shell-ok\n", encoding="utf-8")
    (skill / "scripts" / "notes.txt").write_text("not executable", encoding="utf-8")
    (skill / "outside.py").write_text("print('outside')\n", encoding="utf-8")
    return SkillManager(str(root))


def _runner(container, *, timeout_seconds: int = 300, workspace: str = "/ws"):
    from nexent.core.agents.sandbox import SandboxSkillScriptRunner

    return SandboxSkillScriptRunner(
        _StubExecutor(container), timeout_seconds=timeout_seconds, workspace_path=workspace,
    )


@STAGE
@pytest.mark.case_id("UT-SDK-018")
def test_sandbox_skill_runner_stage_execute_return_and_trust_boundary(tmp_path, caplog) -> None:
    from nexent.core.tools.run_skill_script_tool import RunSkillScriptTool
    from nexent.core.utils.observer import ProcessType
    from nexent.skills.skill_manager import SkillNotFoundError, SkillScriptNotFoundError

    manager = _skill_manager(tmp_path)
    try:
        # --- staging + mapped timeout + interpreter selection -----------------
        container = _StubContainer(results=[
            _ExecResult(0, (b"sandbox-report\n", b"")),
            _ExecResult(0, (b"sandbox-report\n", b"")),
            _ExecResult(0, (b"shell-ok\n", b"")),
        ])
        runner = _runner(container, timeout_seconds=300)
        assert runner.available is True

        resolve_calls: list[tuple] = []
        real_resolve = manager.resolve_skill_script

        def spy_resolve(*args, **kwargs):
            resolve_calls.append((args, kwargs))
            return real_resolve(*args, **kwargs)

        manager.resolve_skill_script = spy_resolve

        result = runner(
            manager=manager, skill_name="report-maker", script_path="scripts/report.py",
            params="--flag 7", tenant_id="tenant-a", working_directory="/ws",
        )
        assert result == "sandbox-report\n"
        # Trust boundary is delegated to resolve_skill_script, not re-implemented.
        assert resolve_calls and resolve_calls[0][1] == {"tenant_id": "tenant-a"}
        assert resolve_calls[0][0] == ("report-maker", "scripts/report.py")

        # One-time staging of the validated skill directory under <ws>/skills.
        assert len(container.archives) == 1
        archive_root, archive_bytes = container.archives[0]
        assert archive_root == "/ws/skills"
        with tarfile.open(fileobj=io.BytesIO(archive_bytes)) as tar:
            archive_names = tar.getnames()
        members = [name.split("/", 1)[1] for name in archive_names if "/" in name]
        assert "SKILL.md" in members and "scripts/report.py" in members
        assert not any(name.startswith("/") for name in archive_names)
        staged_dir = archive_names[0].split("/", 1)[0]
        assert staged_dir.startswith("report-maker-")

        prep = [command for command, kwargs in container.exec_calls if "demux" not in kwargs]
        assert prep[0][:2] == ["mkdir", "-p"] and prep[0][2] == "/ws/skills"
        assert any(command[:3] == ["chmod", "-R", "a+rX"] for command in prep)
        assert any(command[:3] == ["chmod", "-R", "a-w"] for command in prep)

        script_exec = container.success_commands()
        assert len(script_exec) == 1
        command = script_exec[0]
        assert command[:4] == ["timeout", "--signal=KILL", "300", "python"]
        assert command[4] == f"/ws/skills/{staged_dir}/scripts/report.py"
        assert command[5:] == ["--flag", "7"]
        _, kwargs = container.exec_calls[-1]
        assert kwargs["user"] == "sandbox" and kwargs["workdir"] == "/ws/outputs"
        assert kwargs["environment"]["NEXENT_WORKSPACE"] == "/ws"
        assert kwargs["environment"]["NEXENT_OUTPUT_DIR"] == "/ws/outputs"

        # Repeating the same unchanged script reuses its validated staging.
        container.exec_calls.clear()
        repeated = runner(
            manager=manager, skill_name="report-maker", script_path="scripts/report.py",
            params="--flag 7", tenant_id="tenant-a", working_directory="/ws",
        )
        assert repeated == "sandbox-report\n"
        assert len(container.archives) == 1

        # A different script is validated separately before interpreter selection.
        container.exec_calls.clear()
        result_sh = runner(
            manager=manager, skill_name="report-maker", script_path="scripts/echo.sh",
            params=None, tenant_id="tenant-a", working_directory="/ws",
        )
        assert result_sh == "shell-ok\n"
        bash_exec = container.success_commands()
        assert bash_exec and bash_exec[0][3] == "bash"

        # Default mapped timeout is 300 seconds.
        from nexent.core.agents.sandbox import SandboxSkillScriptRunner

        default_runner = SandboxSkillScriptRunner(_StubExecutor(_StubContainer()))
        assert default_runner._timeout_seconds == 300

        # --- negative inputs: rejected at resolve_skill_script, zero container --
        rejected = [
            ("../escape.py", SkillScriptNotFoundError),
            ("/etc/passwd.py", SkillScriptNotFoundError),
            ("nowhere/deep.py", SkillScriptNotFoundError),
            ("scripts/notes.txt", ValueError),
        ]
        for script_path, error in rejected:
            before_exec = len(container.exec_calls)
            before_archives = len(container.archives)
            with pytest.raises(error):
                runner(
                    manager=manager, skill_name="report-maker", script_path=script_path,
                    params=None, tenant_id="tenant-a", working_directory="/ws",
                )
            assert len(container.exec_calls) == before_exec
            assert len(container.archives) == before_archives
        with pytest.raises(SkillNotFoundError):
            runner(
                manager=manager, skill_name="ghost-skill", script_path="scripts/report.py",
                params=None, tenant_id="tenant-a", working_directory="/ws",
            )

        # --- failure mapping: stderr first, stdout fallback; timeout -------------
        fail_runner = _runner(
            _StubContainer(results=[_ExecResult(1, (b"noisy stdout", b"boom stderr"))]),
        )
        payload = json.loads(fail_runner(
            manager=manager, skill_name="report-maker", script_path="scripts/report.py",
            params=None, tenant_id="tenant-a", working_directory="/ws",
        ))
        assert payload["error"] == "boom stderr" and payload["output"] == "noisy stdout"

        fallback_runner = _runner(
            _StubContainer(results=[_ExecResult(1, (b"stdout only failure", b""))]),
        )
        payload = json.loads(fallback_runner(
            manager=manager, skill_name="report-maker", script_path="scripts/report.py",
            params=None, tenant_id="tenant-a", working_directory="/ws",
        ))
        assert payload["error"] == "stdout only failure" and payload["output"] == ""

        timeout_runner = _runner(_StubContainer(results=[_ExecResult(137, (b"", b""))]))
        with pytest.raises(TimeoutError):
            timeout_runner(
                manager=manager, skill_name="report-maker", script_path="scripts/report.py",
                params=None, tenant_id="tenant-a", working_directory="/ws",
            )

        # --- unavailable executor: runner rejects, tool falls back in-process --
        unavailable = _runner(_StubContainer())
        unavailable._container = None
        assert unavailable.available is False
        with pytest.raises(RuntimeError, match="Docker sandbox"):
            unavailable(
                manager=manager, skill_name="report-maker", script_path="scripts/report.py",
                params=None, tenant_id="tenant-a", working_directory="/ws",
            )
        assert unavailable._staged_skills == {}
        unavailable.cleanup()  # no-op when unavailable, must not raise

        root = str(tmp_path / "skills")
        tool = RunSkillScriptTool(local_skills_dir=root, tenant_id="tenant-a")
        assert tool.execution_backend is None
        fallback_result = tool.execute("report-maker", "scripts/report.py")
        assert fallback_result.strip() == "sandbox-report"

        bound = RunSkillScriptTool(local_skills_dir=root, tenant_id="tenant-a")
        bound.bind_execution_backend(unavailable)
        rejected_result = bound.execute("report-maker", "scripts/report.py")
        assert rejected_result.startswith("[UnexpectedError]") and "Docker sandbox" in rejected_result

        # --- bind_execution_backend + on_complete + artifact return path --------
        artifact = tmp_path / "ws-out" / "report.txt"
        artifact.parent.mkdir()
        artifact.write_text("created-by-script", encoding="utf-8")
        backend_payload = json.dumps({
            "status": "success",
            "artifacts": [{
                "kind": "file", "absolute_path": str(artifact), "file_name": "report.txt",
                "mime_type": "text/plain", "file_size_bytes": artifact.stat().st_size,
            }],
        })

        class _Observer:
            def __init__(self):
                self.events = []

            def add_message(self, agent_name, process_type, content, **kwargs):
                self.events.append((process_type, content))

        observer = _Observer()
        completed: list[str] = []
        wired = RunSkillScriptTool(local_skills_dir=root, tenant_id="tenant-a", observer=observer)
        wired.bind_execution_backend(
            lambda **kwargs: backend_payload, on_complete=completed.append,
        )
        assert wired.execute("report-maker", "scripts/report.py") == backend_payload
        assert completed == [backend_payload]
        artifacts = [
            event for event in observer.events if event[0] is ProcessType.SKILL_ARTIFACT
        ]
        assert len(artifacts) == 1
        published = artifacts[0][1]
        assert published["skill_name"] == "report-maker"
        assert published["artifacts"][0]["file_name"] == "report.txt"

        # --- cleanup unloads staging and a fresh runner can re-execute ---------
        cleanup_container = _StubContainer(results=[_ExecResult(0, (b"sandbox-report\n", b""))])
        cleanup_runner = _runner(cleanup_container)
        cleanup_runner(
            manager=manager, skill_name="report-maker", script_path="scripts/report.py",
            params=None, tenant_id="tenant-a", working_directory="/ws",
        )
        cleanup_runner.cleanup()
        assert any(
            command[:3] == ["rm", "-rf", "--"] and command[3] == "/ws/skills"
            for command, kwargs in cleanup_container.exec_calls
        )
        # A re-created runner stages the validated directory again on demand.
        second_container = _StubContainer(results=[_ExecResult(0, (b"sandbox-report\n", b""))])
        second_runner = _runner(second_container)
        assert second_runner(
            manager=manager, skill_name="report-maker", script_path="scripts/report.py",
            params=None, tenant_id="tenant-a", working_directory="/ws",
        ) == "sandbox-report\n"
        assert len(second_container.archives) == 1

        # Step 5: framework logs must not carry secret material.
        caplog.set_level(logging.WARNING)
        leaky = _runner(_StubContainer(results=[_ExecResult(2, (b"", b"script blew up"))]))
        with caplog.at_level(logging.WARNING):
            leaky(
                manager=manager, skill_name="report-maker", script_path="scripts/report.py",
                params=None, tenant_id="tenant-a", working_directory="/ws",
            )
        logged = caplog.text
        assert "script blew up" in logged
        assert "sk-" not in logged and "Bearer " not in logged and "api_key" not in logged.lower()
    finally:
        from nexent.skills.skill_manager import SkillManager

        SkillManager._instance = None
