# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Start a fresh executor while the supervisor retains the actual Daily leases."""
from contextlib import contextmanager
import json
import os
import signal
import stat
import subprocess
import sys

from suite_runtime import BatchLock, _DEPLOYMENT_LEASE

LEASE_ENV = "_NEXENT_DAILY_LOCK_HANDLES"


@contextmanager
def worker_options(locks):
    """Export exactly these file handles; retain the configured runtime environment."""
    descriptors = [lock.handle.fileno() for lock in locks]
    if os.name == "nt":
        import msvcrt
        handles = [msvcrt.get_osfhandle(fd) for fd in descriptors]
        prior = [os.get_handle_inheritable(handle) for handle in handles]
        try:
            for handle in handles:
                os.set_handle_inheritable(handle, True)
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {"handle_list": handles}
            yield {"parent": os.getpid(), "kind": "windows", "handles": handles}, {
                "startupinfo": startup, "close_fds": True,
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        finally:
            for handle, inherited in zip(handles, prior):
                os.set_handle_inheritable(handle, inherited)
    else:
        yield {"parent": os.getpid(), "kind": "posix", "handles": descriptors}, {"pass_fds": descriptors}


@contextmanager
def inherited_locks(repo, home):
    """Accept OS handles, never a boolean that bypasses the deployment lock."""
    try:
        lease = json.loads(os.environ.pop(LEASE_ENV))
        if not isinstance(lease, dict):
            raise ValueError("invalid lease")
        expected_kind = "windows" if os.name == "nt" else "posix"
        parent = lease.get("parent")
        if type(parent) is not int or parent <= 0 or lease.get("kind") != expected_kind:
            raise ValueError("invalid supervisor")
        if os.name == "nt":
            # Windows venv launchers may insert an intermediate parent process.
            from daily_recovery import owner_alive
            if not owner_alive(parent):
                raise ValueError("supervisor exited")
        elif parent != os.getppid():
            raise ValueError("invalid supervisor")
        handles = lease["handles"]
        if len(handles) != 2 or any(type(fd) is not int or fd < 0 for fd in handles) or handles[0] == handles[1]:
            raise ValueError("invalid handles")
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Daily execution requires inherited supervisor locks") from None
    paths = [home / "state/daily.lock", repo / ".git/nexent-e2e-deployment.lock"]
    streams = []
    token = None
    try:
        for handle, path in zip(handles, paths):
            if path.is_symlink() or path.absolute() != path.resolve():
                raise RuntimeError("Daily lease path must not contain symbolic links")
            if os.name == "nt":
                import msvcrt
                handle = msvcrt.open_osfhandle(handle, os.O_RDWR)
            stream = os.fdopen(handle, "r+b", buffering=0)
            streams.append(stream)
            os.set_inheritable(handle, False)
            actual = os.fstat(handle)
            if not stat.S_ISREG(actual.st_mode) or not os.path.samestat(actual, path.stat()):
                raise RuntimeError("Inherited Daily lock does not match the expected path")
            if os.name != "nt":
                import fcntl
                # The inherited open-file description already owns this flock.
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with BatchLock(path):
                    raise ValueError("Inherited Daily lease is not locked")
            except RuntimeError as exc:
                if str(exc) != "another daily run is active":
                    raise
        token = _DEPLOYMENT_LEASE.set((str(paths[1].resolve()), os.getpid()))
        yield
    finally:
        if token is not None:
            _DEPLOYMENT_LEASE.reset(token)
        for stream in reversed(streams):
            stream.close()


def fresh_command(repo, home, directory):
    # A unique, unwritten cache prefix also prevents timestamp-valid old .pyc reads.
    cache = home / "runtime/daily-python-cache" / directory.name
    return [sys.executable, "-B", "-X", f"pycache_prefix={cache}",
            str(repo / "test-e2e/infra/scripts/daily-worker.py"),
            "--test-home", str(home), "--launch", str(directory)]


def run_worker(repo, home, directory, head, publish_latest, locks):
    """Keep both supervisor locks until the executor exits, including during recovery."""
    command = [*fresh_command(repo, home, directory), "--head", head]
    if publish_latest:
        command.append("--publish-latest")
    with worker_options(locks) as (lease, options):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env[LEASE_ENV] = json.dumps(lease)
        process = subprocess.Popen(command, cwd=repo, env=env, **options)
    try:
        return process.wait()
    except KeyboardInterrupt:
        # Send a catchable interruption only to the coordinator, which owns cleanup.
        previous = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            if process.poll() is None:
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
                except OSError:
                    print("Could not signal Daily; retaining locks until the executor exits", flush=True)
            while True:
                try:
                    process.wait()
                    break
                except KeyboardInterrupt:
                    print("Waiting for Daily execution and environment recovery to finish", flush=True)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        raise


def notify_terminal(repo, home, directory):
    """Notification also loads the synchronized code in a separate interpreter."""
    command = [*fresh_command(repo, home, directory), "--notify-only"]
    try:
        result = subprocess.run(command, cwd=repo, timeout=150, check=False)
        if result.returncode:
            print("Terminal notification helper failed; inspect the launch receipt", flush=True)
    except (OSError, subprocess.TimeoutExpired):
        print("Terminal notification helper unavailable; original result retained", flush=True)
