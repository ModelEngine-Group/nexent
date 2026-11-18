# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Execute the real host migration scripts with controlled platform commands."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "deploy/sql/tools/supabase_to_postgres/migrate.sh"

PLATFORM = r"""
fake_record() { printf '%s\037' "$@" >> "$FAKE_LOG"; printf '\n' >> "$FAKE_LOG"; }
fake_inside() {
  if [[ "$*" == *psql* ]]; then cat >/dev/null; printf '%s' "$FAKE_STATE"; return; fi
  case "${@: -1}" in
    PGPORT) printf '%s' "${FAKE_INSIDE_PORT:-5432}" ;;
    POSTGRES_PASSWORD|PGPASSWORD) printf '%s' "${FAKE_INSIDE_PASSWORD:-}" ;;
    POSTGRES_USER) printf 'postgres' ;;
    POSTGRES_DB) printf 'original' ;;
  esac
}
fake_snapshot() {
  printf '%s\n' "$POSTGRES_HOST" "$POSTGRES_PORT" "$POSTGRES_USER" "$POSTGRES_DB" \
    "$SUPABASE_POSTGRES_HOST" "$SUPABASE_POSTGRES_PORT" "$SUPABASE_POSTGRES_USER" "$SUPABASE_POSTGRES_DB" > "$FAKE_CONNECTIONS"
  if [ "$SUPABASE_POSTGRES_PASSWORD" = "$FAKE_EXPECT_SOURCE_SECRET" ]; then printf 'source-secret-matched\n' >> "$FAKE_CONNECTIONS"; fi
}
docker() {
  fake_record docker "$@"
  if [ "$1" = inspect ]; then
    local name="${@: -1}" format="${3:-}"
    if [ "${2:-}" != --format ]; then
      [[ "$name" == account-migration-* ]] || grep -Fxq -- "$name" <<< "$FAKE_NAMES"
      return
    fi
    case "$format" in
      *State.Running*) printf '%s' "$FAKE_RUNNING" ;;
      *State.ExitCode*) printf '%s' "$FAKE_EXIT_CODE" ;;
      *nexent.account-migration*) printf '%s' "$name" ;;
      *com.docker.compose.project*) printf '%s' "$FAKE_PROJECT" ;;
      *IPAddress*) if [ "$name" = nexent-postgresql ]; then printf '10.0.0.2'; else printf '10.0.0.3'; fi ;;
      *NetworkSettings.Networks*) printf 'fixture-network' ;;
    esac
  elif [ "$1" = ps ]; then printf '%s\n' "$FAKE_NAMES"
  elif [ "$1" = exec ]; then fake_inside "$@"
  elif [ "$1" = create ]; then fake_snapshot
  elif [ "$1" = start ] && [ "${2:-}" = -a ]; then
    printf '%s\n' "$FAKE_RESULT"; return "$FAKE_WORKER_STATUS"
  elif [ "$1" = network ] && [ "$2" = inspect ]; then
    if [[ "$*" == *com.docker.compose.project* ]]; then printf '%s' "$FAKE_PROJECT"; else printf '10.0.0.1'; fi
  elif [ "$1" = stop ] && [ "$FAKE_CLEANUP_STATUS" != 0 ]; then return "$FAKE_CLEANUP_STATUS"
  fi
}
kubectl() {
  fake_record kubectl "$@"
  [ "${1:-}" != --namespace ] || shift 2
  case "$1" in
    exec) fake_inside "$@" ;;
    get)
      case "$2" in
        deployment)
          if [ "$3" = nexent-config ]; then return; fi
          case "$*" in
            *persistentVolumeClaim*) printf '%s' "$FAKE_CLAIM" ;;
            *replicas*) printf '%s' "$FAKE_REPLICAS" ;;
            *'-o yaml'*) printf 'kind: Deployment\nmetadata:\n  name: original-source\n' ;;
            *) [ "$FAKE_SOURCE_PRESENT" != true ] || printf 'deployment/%s' "$3" ;;
          esac ;;
        pvc) if [[ "$*" == *volumeName* ]]; then printf '%s' "$FAKE_VOLUME"; else printf 'kind: PersistentVolumeClaim\n'; fi ;;
        pv) printf 'kind: PersistentVolume\n' ;;
        service) if [[ "$*" == *port* ]]; then printf '5432'; else printf '10.0.0.4'; fi ;;
        job) if [ "$FAKE_WORKER_STATUS" = 0 ]; then printf '1:0'; else printf '0:1'; fi ;;
      esac ;;
    create)
      if [ "$2" = secret ]; then fake_snapshot; fi
      if [ "$2" = -f ]; then cp "$3" "$FAKE_JOB"; fi ;;
    logs) printf '%s\n' "$FAKE_RESULT" ;;
  esac
}
export -f fake_record fake_inside fake_snapshot docker kubectl
bash "$FIXTURE_SCRIPT" "$@"
"""


def run_migration(tmp_path, arguments=(), values=None, *, env_text="", data=True):
    """Run the shipped Shell entry; never execute a real Docker/kubectl command."""
    env_file = tmp_path / "deployment.env"
    env_file.write_text(env_text, encoding="utf-8")
    data_dir = tmp_path / "original-data"
    if data:
        (data_dir / "global").mkdir(parents=True, exist_ok=True)
        (data_dir / "PG_VERSION").write_text("15", encoding="utf-8")
        (data_dir / "global/pg_control").write_text("original", encoding="utf-8")
    log, connections, job = (tmp_path / name for name in ("commands.log", "connections.txt", "job.yaml"))
    defaults = dict(NEXENT_IMAGE="fixture/backend:current", NEXENT_POSTGRES_PASSWORD="private-target",
        POSTGRES_USER="root", POSTGRES_DB="nexent", SUPABASE_POSTGRES_PASSWORD="private-source",
        SUPABASE_DATA_DIR=data_dir.as_posix(), FAKE_LOG=log.as_posix(), FAKE_CONNECTIONS=connections.as_posix(),
        FAKE_JOB=job.as_posix(), FIXTURE_SCRIPT=SCRIPT.as_posix(), FAKE_EXPECT_SOURCE_SECRET="private-source",
        FAKE_STATE=json.dumps({"complete": False, "legacy": True}),
        FAKE_NAMES="supabase-db-mini\nsupabase-auth-mini\nsupabase-kong-mini", FAKE_RUNNING="true",
        FAKE_EXIT_CODE="0", FAKE_WORKER_STATUS="0", FAKE_CLEANUP_STATUS="0",
        FAKE_RESULT=json.dumps({"committed": "--apply" in arguments}), FAKE_PROJECT="nexent-supabase-migration",
        FAKE_CLAIM="custom-data", FAKE_VOLUME="custom-pv", FAKE_SOURCE_PRESENT="true", FAKE_REPLICAS="0",
        TMPDIR=tmp_path.as_posix())
    # Local machine configuration must never enter this disposable fixture.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("POSTGRES_", "SUPABASE_", "NEXENT_", "FAKE_"))}
    env.update(defaults)
    for key, value in (values or {}).items():
        if value is None: env.pop(key, None)
        else: env[key] = str(value)
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert bash, "Bash is required for host migration tests"
    result = subprocess.run([bash, "-c", PLATFORM, "fixture", "--env-file", env_file.as_posix(), *arguments],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=20, cwd=ROOT)
    commands = [line.rstrip("\x1f").split("\x1f") for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    fields = ("target_host", "target_port", "target_user", "target_db", "source_host", "source_port", "source_user", "source_db", "secret_match")
    selected = dict(zip(fields, connections.read_text(encoding="utf-8").splitlines())) if connections.exists() else {}
    return SimpleNamespace(code=result.returncode, stdout=result.stdout, stderr=result.stderr,
        commands=commands, connections=selected, job=job.read_text(encoding="utf-8") if job.exists() else "", path=tmp_path)
