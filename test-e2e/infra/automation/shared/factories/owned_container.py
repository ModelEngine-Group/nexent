"""Journal and stop only the exact labelled D5 disposable PostgreSQL container."""
from __future__ import annotations

import json
import re
import subprocess

from shared.asset_registry import register_asset

OWNER = 'DEP-AUTO-E89502155049473D'


def _valid_name(name):
    if not re.fullmatch(r'nexent-utm-d5-[a-z0-9]{8}', str(name)):
        raise ValueError('unowned D5 container name')


def register_container(name, container_id, docker_bin='docker'):
    _valid_name(name)
    if not re.fullmatch(r'[a-f0-9]{64}', str(container_id)):
        raise ValueError('Docker did not return one exact container ID')
    register_asset('owned_containers', name, container_id,
        owner_case_id=OWNER,
        cleanup={'kind': 'stop_owned_container', 'name': name,
                 'container_id': container_id, 'docker_bin': docker_bin})


def stop_owned_container(name, container_id, docker_bin='docker'):
    _valid_name(name)
    if not re.fullmatch(r'[a-f0-9]{64}', str(container_id)):
        raise ValueError('unowned D5 container ID')
    checked = subprocess.run([docker_bin, 'inspect', container_id], capture_output=True,
                             text=True, timeout=15, check=False)
    if checked.returncode:
        # The fixture uses --rm: an already stopped container is absent.
        return
    rows = json.loads(checked.stdout)
    if len(rows) != 1 or rows[0].get('Id') != container_id:
        raise RuntimeError('Docker inspect returned a different container')
    row = rows[0]
    if (row.get('Name') != '/' + name or
            row.get('Config', {}).get('Labels', {}).get('nexent.test.owner') != OWNER):
        raise RuntimeError('Docker container ownership mismatch; refusing stop')
    stopped = subprocess.run([docker_bin, 'stop', container_id], capture_output=True,
                             text=True, timeout=45, check=False)
    if stopped.returncode:
        raise RuntimeError('owned Docker container could not be stopped')
