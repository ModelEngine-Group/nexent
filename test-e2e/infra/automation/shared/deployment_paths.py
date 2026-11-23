"""Resolve host-visible deployment data without inventing local directories."""
import json
import os
from pathlib import Path
import subprocess

from shared.asset_registry import AssetDependencyError
from shared.config import test_root


def project_config_dir() -> Path:
    configured = os.environ.get('PROJECT_CONFIG_DIR', '').strip()
    if configured:
        path = Path(configured)
        path = path if path.is_absolute() else test_root() / path
        if path.is_dir():
            return path.resolve()
    else:
        container = os.environ.get('NEXENT_TEST_WEB_CONTAINER', 'nexent-web')
        try:
            result = subprocess.run(
                ['docker', 'inspect', '--format', '{{json .Mounts}}', container],
                capture_output=True, text=True, timeout=15, check=True,
            )
            mounts = json.loads(result.stdout)
            matches = [Path(m['Source']) for m in mounts
                       if m.get('Destination') == '/mnt/nexent-data/project-config'
                       and m.get('RW')]
            if len(matches) == 1 and matches[0].is_dir():
                return matches[0].resolve()
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            pass
    raise AssetDependencyError(
        'paths', 'project_config', dependency_case_id='D0-PROJECT-CONFIG',
        detail='Set PROJECT_CONFIG_DIR to the actual host-visible deployment directory; '
               'automatic Docker mount discovery did not resolve an accessible directory.',
    )


def mutate_project_config(path: Path, content: bytes | None) -> None:
    """Only mutate this deployment's config; use container ownership if needed."""
    root = project_config_dir()
    relative = path.resolve().relative_to(root).as_posix()
    allowed = {'modelengine-logo.png', 'modelengine-logo2.png',
               'locales/zh/custom.json', 'locales/en/custom.json'}
    if relative not in allowed:
        raise ValueError('Not an allowed project-config test asset')
    try:
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return
    except PermissionError:
        pass
    container = os.environ.get('NEXENT_TEST_WEB_CONTAINER', 'nexent-web')
    inspected = subprocess.run(
        ['docker', 'inspect', '--format', '{{json .Mounts}}', container],
        capture_output=True, text=True, timeout=15, check=True,
    )
    if not any(Path(m['Source']).resolve() == root and m.get('RW')
               and m.get('Destination') == '/mnt/nexent-data/project-config'
               for m in json.loads(inspected.stdout)):
        raise PermissionError('Cannot prove container mount belongs to configured test directory')
    script = ('const fs=require("fs"); const p=process.argv[1]; '
              'if(process.argv[2]==="delete") fs.rmSync(p,{force:true}); '
              'else {fs.mkdirSync(require("path").dirname(p),{recursive:true}); '
              'fs.writeFileSync(p,fs.readFileSync(0));}')
    subprocess.run(
        ['docker', 'exec', '-i', container, 'node', '-e', script,
         '/mnt/nexent-data/project-config/' + relative,
         'delete' if content is None else 'write'],
        input=content or b'', capture_output=True, timeout=15, check=True,
    )
