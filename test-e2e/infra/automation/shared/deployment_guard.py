"""Scoped D5 fault injection with write-ahead recovery and deployment locking.

No compose up/down, image replacement, volume deletion or schema rollback is
performed here. Recovery starts only the exact containers recorded before an
injection; a replaced container requires manual review.
"""
from __future__ import annotations

import argparse
import asyncio
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import sys
import time

import httpx

from shared.asset_registry import AssetDependencyError, AutomationInfrastructureError
from shared.config import service_url, test_root

ACTIVE = ContextVar('deployment_guard', default=None)
SCOPES = {
    'REL-01': (['nexent-runtime'], ['nexent-postgresql', 'redis']),
    'REL-03': (['nexent-data-process'], ['nexent-config', 'nexent-elasticsearch']),
    'REL-04': (['redis'], ['nexent-runtime']),
    'REL-05': (['nexent-runtime'], ['nexent-config']),
    'REL-06': (['nexent-elasticsearch'], ['nexent-data-process', 'nexent-config']),
    'DEP-02': (['nexent-postgresql', 'nexent-runtime'], ['redis']),
}
HTTP_SERVICES = {'nexent-runtime': 'runtime', 'nexent-config': 'config',
                 'nexent-data-process': 'data_process'}


def blocked(detail):
    return AssetDependencyError('deployment', 'recovery', dependency_case_id='D5-ENVIRONMENT', detail=detail)


def assert_service_available(service):
    """Block shared HTTP consumers while a relevant deployment is unrecovered."""
    pending = test_root() / 'state/deployment-guard/pending.json'
    if ACTIVE.get() is not None or not pending.exists():
        return
    affected = {
        'redis': {'runtime', 'config', 'data_process', 'northbound'},
        'nexent-postgresql': {'runtime', 'config', 'data_process', 'northbound'},
        'nexent-elasticsearch': {'runtime', 'config', 'data_process', 'northbound'},
        'nexent-runtime': {'runtime', 'northbound'},
        'nexent-data-process': {'data_process', 'config'},
    }
    try:
        record = json.loads(pending.read_text())['record']
        impacted = set().union(*(affected.get(s, {service}) for s in record['pending']))
    except (OSError, ValueError, KeyError):
        raise blocked('unreadable pending recovery journal; manual review required')
    if service in impacted:
        raise blocked(f'{service} depends on an unresolved deployment recovery')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


class DeploymentGuard:
    def __init__(self, case_id, targets, dependencies=(), probe=None):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', case_id):
            raise ValueError('invalid case ID')
        self.case_id, self.targets, self.dependencies = case_id, list(targets), list(dependencies)
        self.probe = probe
        self.state_dir = test_root() / 'state' / 'deployment-guard'
        self.pending = self.state_dir / 'pending.json'
        self.evidence = Path(os.environ['RESULT_DIR']) / 'd5' / case_id / 'environment.json'
        self.record = {'case_id': case_id, 'preflight': 'PENDING', 'recovery': 'NOT_REQUIRED',
                       'targets': {}, 'events': [], 'pending': []}
        self.lock = None
        self.token = None
        self.containers = {}

    async def command(self, *args, timeout=60):
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, _ = await asyncio.wait_for(process.communicate(), timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            # Compose may echo interpolated credentials; do not persist raw output.
            raise AutomationInfrastructureError(f'deployment command failed: {args[0]} exit={process.returncode}')
        return out.decode()

    def acquire(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.lock = (self.state_dir / 'exclusive.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.lock.seek(0)
                self.lock.write(b'0')
                self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            self.lock = None
            raise blocked('another deployment fault/recovery operation holds the lock') from exc

    def release(self):
        if self.lock:
            self.lock.close()
            self.lock = None

    def save(self):
        write_json(self.evidence, self.record)
        if self.record['pending']:
            write_json(self.pending, {'evidence': str(self.evidence), 'record': self.record})

    async def discover(self):
        reference = os.environ.get('D5_REFERENCE_CONTAINER', 'nexent-runtime')
        reference_info = json.loads(await self.command('docker', 'inspect', reference))[0]
        labels = reference_info['Config'].get('Labels') or {}
        project = labels.get('com.docker.compose.project')
        if not project:
            raise blocked('reference container has no Compose project identity')
        files = os.environ.get('D5_COMPOSE_FILES') or labels.get('com.docker.compose.project.config_files', '')
        env_file = os.environ.get('D5_COMPOSE_ENV_FILE') or labels.get('com.docker.compose.project.environment_file', '')
        workdir = labels.get('com.docker.compose.project.working_dir', '')
        paths = [Path(p) for p in files.split(',') if p]
        if not paths or not env_file or not all(p.is_file() for p in [*paths, Path(env_file)]):
            raise blocked('actual Compose files/environment file unavailable; set machine-local D5_COMPOSE_FILES and D5_COMPOSE_ENV_FILE')
        command = ['docker', 'compose', '-p', project, '--env-file', env_file]
        if workdir:
            command += ['--project-directory', workdir]
        for path in paths:
            command += ['-f', str(path)]
        # Deployment scripts export image variables only in their own process.
        # Validate Compose structure without inventing those values. Stop/start
        # below use exact existing container IDs, never render/recreate services.
        await self.command(*command, 'config', '--no-interpolate', '--quiet')
        ids = (await self.command('docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={project}')).split()
        if not ids:
            raise blocked('no deployment containers found')
        for item in json.loads(await self.command('docker', 'inspect', *ids)):
            metadata = item['Config'].get('Labels') or {}
            service = metadata.get('com.docker.compose.service', '')
            if metadata.get('com.docker.compose.oneoff', '').lower() == 'true':
                continue
            if service in self.containers:
                raise blocked(f'multiple replicas for {service}; single-container recovery is not applicable')
            self.containers[service] = item
            self.containers[item['Name'].lstrip('/')] = item
        self.record['project'] = project
        self.record['compose_files'] = [str(p) for p in paths]
        self.record['compose_env_file'] = env_file  # path only, never values
        self.record['operation_mode'] = 'existing-container-id; compose structure validated without interpolation'

    async def healthy(self, service, container_id):
        item = json.loads(await self.command('docker', 'inspect', container_id))[0]
        state = item['State']
        if not state.get('Running') or state.get('Paused') or state.get('Restarting'):
            return False
        if 'Health' in state and state['Health']['Status'] != 'healthy':
            return False
        if service in HTTP_SERVICES:
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    # Data-process has its own app and no /health/ready route.
                    endpoint = '/tasks' if service == 'nexent-data-process' else '/health/ready'
                    response = await client.get(service_url(HTTP_SERVICES[service]) + endpoint)
                    if service == 'nexent-data-process':
                        return response.status_code == 200 and isinstance(response.json().get('tasks'), list)
                    return response.status_code == 200 and response.json().get('status') == 'ready'
            except (httpx.HTTPError, ValueError):
                return False
        if service == 'nexent-postgresql':
            try:
                await self.command('docker', 'exec', container_id, 'pg_isready', timeout=10)
            except AutomationInfrastructureError:
                return False
            return True
        # Non-HTTP targets must supply an actual Docker health check.
        return 'Health' in state

    def required_services(self):
        """Expand actual deployed dependencies, including transitive ones.

        Compose labels encode service:condition:restart, so trailing false is
        NOT permission to ignore a dependency. Unknown/missing services fail
        closed instead of silently shrinking the dependency graph.
        """
        pending = list(dict.fromkeys(self.targets + self.dependencies))
        resolved = []
        seen_ids = set()
        edges = {}
        while pending:
            service = pending.pop(0)
            item = self.containers.get(service)
            if not item:
                raise blocked(f'deployed dependency container missing: {service}')
            if item['Id'] in seen_ids:
                continue
            seen_ids.add(item['Id'])
            resolved.append(service)
            labels = item.get('Config', {}).get('Labels') or {}
            dependencies = []
            for raw in labels.get('com.docker.compose.depends_on', '').split(','):
                if not raw.strip():
                    continue
                fields = raw.strip().split(':')
                if len(fields) < 2 or fields[1] not in {'service_healthy', 'service_started', 'service_completed_successfully'}:
                    raise blocked(f'unsupported dependency declaration for {service}')
                dependencies.append(fields[0])
                pending.append(fields[0])
            edges[service] = dependencies
        self.record['dependency_graph'] = edges
        self.record['required_services'] = resolved
        return resolved

    async def __aenter__(self):
        from d5.assets import destructive_deployment_enabled
        destructive_deployment_enabled()
        self.acquire()
        try:
            if self.pending.exists():
                raise blocked('unresolved previous deployment recovery; run deployment_guard --recover first')
            await self.discover()
            for service in self.required_services():
                item = self.containers.get(service)
                if not item or not await self.healthy(service, item['Id']):
                    raise blocked(f'preflight failed for {service}; no fault was injected')
                self.record['targets'][service] = {'id': item['Id'], 'running': True,
                                                   'image': item['Image']}
            try:
                await self.business_probe()
            except Exception as exc:
                raise blocked('preflight business probe failed; no fault was injected') from exc
            self.record['preflight'] = 'PASS'
            self.save()
            self.token = ACTIVE.set(self)
            return self
        except BaseException:
            self.record['preflight'] = 'FAILED'
            try:
                self.save()
            except Exception as evidence_error:
                print(f'preflight evidence write failed: {type(evidence_error).__name__}', file=sys.stderr)
            finally:
                self.release()
            raise

    async def action(self, action, service, timeout=600):
        if service not in self.targets or action not in {'stop', 'start', 'restart'}:
            raise AutomationInfrastructureError('unapproved deployment action/target')
        if action == 'start':
            await self.restore([service])
            return ''
        if service not in self.record['pending']:
            self.record['pending'].append(service)
        self.record['events'].append({'action': action, 'service': service, 'state': 'INTENT', 'at': time.time()})
        self.save()  # Durable intent MUST precede the destructive command.
        await self.command('docker', action, self.record['targets'][service]['id'], timeout=timeout)
        self.record['events'].append({'action': action, 'service': service, 'state': 'COMMAND_SUCCEEDED', 'at': time.time()})
        self.save()
        if action == 'restart':
            # Wait for readiness, without treating a later rescue as a test pass.
            await self.wait_ready(service)
        return ''

    async def wait_ready(self, service):
        deadline = time.monotonic() + float(os.environ.get('D5_RECOVERY_TIMEOUT_SECONDS', '180'))
        while True:
            if await self.healthy(service, self.record['targets'][service]['id']):
                return
            if time.monotonic() >= deadline:
                raise AssertionError(f'{service} did not become ready before recovery deadline')
            await asyncio.sleep(2)

    async def business_probe(self):
        if self.probe:
            await self.probe()
            return
        from shared.auth import sign_in
        for name, role, endpoint in (
            ('nexent-runtime', 'tenant_a_user', '/conversation/list?today_start_ms=0&week_start_ms=0&limit=1'),
            ('nexent-config', 'tenant_a_admin', '/config/load_config'),
        ):
            if name not in self.record['targets']:
                continue
            identity = await sign_in(role)
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(service_url(HTTP_SERVICES[name]) + endpoint,
                                            headers={'Authorization': f'Bearer {identity.access_token}'})
                if response.status_code != 200:
                    raise AssertionError(f'business probe failed for {name}: HTTP {response.status_code}')

    async def restore(self, services=None):
        selected = list(services if services is not None else self.record['pending'])
        errors = []
        for service in selected:
            if service not in self.record['pending']:
                continue
            try:
                target = self.record['targets'][service]
                item = json.loads(await self.command('docker', 'inspect', target['id']))[0]
                if item['Image'] != target['image']:
                    raise AutomationInfrastructureError('container image changed; refusing automatic recovery')
                await self.command('docker', 'start', target['id'])
                await self.wait_ready(service)
                self.record['events'].append({'action': 'restore', 'service': service, 'state': 'READY', 'at': time.time()})
            except Exception:
                errors.append(service)
        # Keep all pending entries until dependencies and probe also pass.
        if not errors:
            try:
                for service, target in self.record['targets'].items():
                    if service in self.record['pending'] and service not in selected:
                        continue
                    await self.wait_ready(service)
                if not (set(self.record['pending']) - set(selected)):
                    await self.business_probe()
            except Exception:
                errors.append('dependency-or-business-probe')
        if errors:
            self.record['recovery'] = 'FAILED'
            self.record['recovery_errors'] = errors
            self.save()
            raise AutomationInfrastructureError('deployment recovery failed; pending journal retained')
        self.record['pending'] = [s for s in self.record['pending'] if s not in selected]
        self.record['recovery'] = 'PARTIAL' if self.record['pending'] else 'RESTORED'
        self.save()
        if not self.record['pending']:
            self.pending.unlink(missing_ok=True)

    async def __aexit__(self, exc_type, exc, tb):
        self.record['test_body'] = 'FAILED' if exc_type else 'COMPLETED'
        try:
            if self.record['pending']:
                await self.restore()
        except Exception:
            if exc_type is None:
                raise
            # Preserve the original product assertion; recovery failure remains
            # separately recorded and the Runner must fail on pending recovery.
        finally:
            try:
                try:
                    self.save()
                except Exception as evidence_error:
                    if exc_type is None:
                        raise
                    print(f'recovery evidence write failed: {type(evidence_error).__name__}', file=sys.stderr)
            finally:
                try:
                    if self.token is not None:
                        ACTIVE.reset(self.token)
                        self.token = None
                finally:
                    self.release()
        return False


async def recover_pending():
    pending = test_root() / 'state/deployment-guard/pending.json'
    if not pending.exists():
        return
    guard = DeploymentGuard('RECOVERY', [])
    guard.acquire()
    try:
        if not pending.exists():
            return
        from d5.assets import destructive_deployment_enabled
        destructive_deployment_enabled()
        payload = json.loads(pending.read_text())
        guard.record = payload['record']
        guard.evidence = Path(payload['evidence'])
        # Do not accept journals pointing outside this suite's evidence storage.
        guard.evidence.resolve().relative_to(test_root().resolve())
        # Credentials are reloaded from local configuration, never persisted.
        await guard.restore()
    finally:
        guard.release()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--recover', action='store_true', required=True)
    parser.parse_args()
    asyncio.run(recover_pending())
