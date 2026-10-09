"""Explicit host/container workspace mapping for bind-mounted executors."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


def validate_container_root(value: str) -> PurePosixPath:
    """Reject host paths and traversal before constructing a container path."""
    path = PurePosixPath(value)
    if not path.is_absolute() or path == PurePosixPath('/') or '\\' in value or ':' in value or '..' in path.parts:
        raise ValueError('container workspace must be a non-root POSIX absolute path')
    return path


@dataclass(frozen=True)
class SandboxWorkspace:
    host_root: Path
    container_root: PurePosixPath

    def __post_init__(self):
        object.__setattr__(self, 'host_root', Path(self.host_root).resolve())
        object.__setattr__(self, 'container_root', validate_container_root(str(self.container_root)))

    def to_container(self, path: str | Path) -> PurePosixPath:
        relative = Path(path).resolve().relative_to(self.host_root)
        return self.container_root.joinpath(*relative.parts)

    def to_host(self, value: str) -> Path:
        """Translate an absolute kernel path and enforce the resolved host boundary."""
        path = validate_container_root(value)
        relative = path.relative_to(self.container_root)
        # Reject Windows-special components, including alternate data streams.
        if any(PureWindowsPath(part).is_reserved() for part in relative.parts):
            raise ValueError('Reserved host filename')
        target = self.host_root.joinpath(*relative.parts).resolve()
        target.relative_to(self.host_root)
        return target

    def resolve_file(self, value: str, base: str | Path) -> Path:
        """Resolve a tool path without changing that tool's relative-path convention."""
        base_path = Path(base).resolve()
        base_path.relative_to(self.host_root)
        if value.startswith('/'):
            target = self.to_host(value)
        else:
            if '..' in PureWindowsPath(value).parts:
                raise ValueError('Workspace traversal is not allowed')
            target = (base_path / value).resolve()
        target.relative_to(base_path)
        return target

    def for_run(self, host_run: str | Path) -> 'SandboxWorkspace':
        return SandboxWorkspace(Path(host_run), self.to_container(host_run))

    @property
    def mount_id(self) -> str:
        payload = json.dumps([os.path.normcase(str(self.host_root)), str(self.container_root)])
        return hashlib.sha256(payload.encode()).hexdigest()

    def matches_mount(self, mount: dict) -> bool:
        """Compare Desktop's Linux view of drive paths with the configured source."""
        source = str(mount.get('Source', '')).replace('\\', '/')
        expected = str(self.host_root).replace('\\', '/')
        if self.host_root.drive:
            for prefix in ('/run/desktop/mnt/host/', '/host_mnt/'):
                if source.startswith(prefix):
                    tail = source[len(prefix):]
                    if len(tail) >= 2 and tail[1] == '/':
                        source = tail[0] + ':' + tail[1:]
                    break
            source, expected = source.casefold(), expected.casefold()
        return (
            mount.get('Type') == 'bind' and mount.get('RW') is True
            and mount.get('Destination') == str(self.container_root)
            and source.rstrip('/') == expected.rstrip('/')
        )


def probe_workspace(container, workspace: PurePosixPath) -> None:
    """Verify traversal and real read/write access as the container's configured user."""
    code = (
        'import os,tempfile; from pathlib import Path; '
        f'p=Path({str(workspace)!r}); '
        'os.chdir(p.parent); os.chdir(p.name); '
        '[(f.open("rb").read(1)) for f in (p/"inputs").rglob("*") if f.is_file()]; '
        't=tempfile.TemporaryDirectory(prefix=".nexent-probe-",dir=p/"outputs"); '
        'f=Path(t.name)/"nested"/"file.txt"; f.parent.mkdir(); '
        'f.write_text("probe",encoding="utf-8"); '
        'assert f.read_text(encoding="utf-8")=="probe"; t.cleanup()'
    )
    result = container.exec_run(['python', '-c', code])
    if result.exit_code != 0:
        raise RuntimeError(f'Sandbox workspace access failed: {result.output!r}')
