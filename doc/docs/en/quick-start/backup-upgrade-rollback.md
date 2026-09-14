# Nexent Backup, Upgrade, and Rollback Guide

This guide covers version changes and disaster recovery for existing Nexent environments, including online Docker Compose deployments, offline deployment packages, and Kubernetes. The recommended workflow is: **prepare the target version → stop writes → complete and verify backups → upgrade → validate → restore traffic**. If validation fails, choose either an application rollback or a full data restore based on whether the database and storage have changed.

The Docker commands use Linux, Bash 4+, GNU tar, and Docker Compose v2 as examples. They require permission to operate Docker and sudo access to read the data directories. Docker Engine 18.09 environments should still use a compatible Compose CLI; the commands in this guide do not depend on newer daemon features such as GPU device requests, cgroup namespace modes, or healthcheck `start_interval`. Data paths on macOS, Windows, or remote Docker daemons cannot use Linux host paths directly.

## 1. Pre-upgrade Checks

Complete the following checks before entering the maintenance window:

- **Confirm versions**: Record the current code commit, deployment package version, running image IDs, and image digests. Select a specific target release; do not use `git pull` or `latest` as the version record. The current scripts first read `VERSION` from the repository root and fall back to `APP_VERSION` in `backend/consts/const.py`; deployment options can still affect the images that actually run.
- **Review changes**: Check the target release notes, new migrations under `deploy/sql/`, environment-variable changes, and middleware image changes. Validate data-format compatibility separately when upgrading PostgreSQL, Elasticsearch, or other middleware across versions.
- **Prepare recovery assets**: Keep the old source tree or complete deployment package, old images, old configuration, and a usable backup. Download new images and backup helper images in advance, and verify their architecture. Reserve enough disk space for the backup, images, and a copy of the failed environment based on actual data size and recovery-drill results.
- **Define the maintenance window**: Record the owner, start time, allowed downtime, latest rollback time, RPO (the acceptable amount of data loss), and RTO (the recovery deadline). Restoring the pre-upgrade backup discards writes made after that restore point. If traffic has already reopened, decide how those writes will be handled before rolling back.
- **Run a recovery drill first**: Verify the backup in an isolated environment and measure the recovery time. Disable scheduled jobs, external notifications, and production tool calls in the drill environment, and make sure it cannot connect to production databases or storage.
- **Save a validation baseline**: Record counts and sample IDs for important users, agents, knowledge bases, and other records. Save Elasticsearch index and document counts plus checksums for important objects and workspace files so they can be compared after upgrade or rollback.

Reuse the existing environment's components, port policy, image source, and data locations. The existing `.env` retains its values and receives new variables from `.env.example`; do not overwrite it with the new example file or include `--rotate-secrets` in a routine upgrade.

## 2. What Must Be Backed Up

The Docker paths below come from the current Compose configuration. **Treat the actual container Mounts as authoritative.** Backing up only `ROOT_DIR` is insufficient, and `docker export` is not a volume backup.

| Content | Default Docker location or source | Recovery purpose |
| --- | --- | --- |
| Deployment code and configuration | Original deployment directory, especially `deploy/env/`, `deploy/docker/deploy.options`, `deploy/docker/.env.generated`, Compose files, `deploy/sql/`, and `VERSION` | Restore scripts, version, components, secrets, and the SQL set |
| Application PostgreSQL | `${ROOT_DIR}/postgresql/data` | Agents, tenant business data, configuration, sessions, and migration records |
| Supabase PostgreSQL, when enabled | `${ROOT_DIR}/volumes/db/data`, plus the actual volume name behind the `db-config` named volume | Users, authentication data, and database configuration; the application PostgreSQL backup cannot replace it |
| Elasticsearch | Cluster corresponding to `${ROOT_DIR}/elasticsearch` | Knowledge-base indices, mappings, and vectors; back up with the Elasticsearch Snapshot API |
| MinIO | `${ROOT_DIR}/minio/data` | Source documents, attachments, and object-storage metadata |
| Redis | `${ROOT_DIR}/redis` | Persistent queues and runtime state; drain jobs before backup and check for duplicate execution after recovery |
| User directories, skills, and terminal files | The host directory actually mounted at `/mnt/nexent`, `${ROOT_DIR}/skills`, SSH key directories, and `TERMINAL_MOUNT_DIR` | Skill packages, user files, SSH access, and terminal work products |
| Agent workspaces | `NEXENT_SANDBOX_WORKSPACE_VOLUME`, default `nexent-agent-workspace`, mounted at `/mnt/nexent/workdir` | Independent workspace data hidden by the parent mount; back it up separately |
| Monitoring, when enabled | Actual mounts and named volumes of the `monitor` Compose project | Phoenix, Grafana, Tempo, or Langfuse history; Langfuse has separate PostgreSQL, ClickHouse, MinIO, and other storage |
| External dependencies and custom mounts | External databases, object storage, MCP or sandbox volumes, reverse-proxy configuration, certificates, and symlink targets | Back them up on their respective platforms and record matching restore points |

`.env`, Helm values, Secret exports, database dumps, and container inspection output may contain passwords or tokens. Restrict backup directories to maintenance personnel, encrypt off-host copies, and never commit them to Git or attach them to public tickets. Keep at least one copy away from the original host, and retain old images and backups until the rollback observation period ends.

## 3. Docker: Create a Pre-upgrade Backup

### 3.1 Set Paths and Capture the Environment

Run the following commands in the same Bash session. Replace the paths with the actual deployment locations. `BACKUP_BASE` must be outside both the deployment and data directories. If any command fails, stop and investigate; creating a file does not by itself mean the backup succeeded.

```bash
set -euo pipefail
umask 077

CODE_DIR=/opt/nexent
BACKUP_BASE=/backup/nexent
STAMP=$(date -u +%Y%m%d-%H%M%S)
BAK="$BACKUP_BASE/$STAMP"
mkdir -p "$BAK"
cd "$CODE_DIR"

docker version > "$BAK/docker-version.txt"
docker compose version > "$BAK/compose-version.txt"
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' > "$BAK/containers-all.txt"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git rev-parse HEAD > "$BAK/git-commit.txt"
  git status --short > "$BAK/git-status.txt"
fi

{
  docker ps -a --filter label=com.docker.compose.project=nexent --format '{{.Names}}'
  docker ps -a --filter label=com.docker.compose.project=monitor --format '{{.Names}}'
} | sort -u > "$BAK/containers.txt"
```

Review `containers.txt` manually. Remove containers outside this maintenance scope, and add dynamic MCP services, sandboxes, custom project names, and any other containers that write to the storage being backed up. Do not use a command that stops every container on the host. Then capture mounts, images, and the original running state:

```bash
mapfile -t TARGETS < "$BAK/containers.txt"
test "${#TARGETS[@]}" -gt 0
docker inspect "${TARGETS[@]}" > "$BAK/containers.inspect.json"
docker inspect --format '{{.Name}}{{range .Mounts}}{{printf "\n  %s %s -> %s" .Type .Source .Destination}}{{end}}' \
  "${TARGETS[@]}" > "$BAK/mounts.txt"
docker inspect --format '{{.Name}} {{.Config.Image}} {{.Image}}' \
  "${TARGETS[@]}" > "$BAK/images.txt"
docker inspect --format '{{if .State.Running}}{{.Name}}{{end}}' \
  "${TARGETS[@]}" | sed '/^$/d' > "$BAK/running-before.txt"
docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}' \
  "${TARGETS[@]}" | sed '/^$/d' | sort -u > "$BAK/volumes.txt"

mapfile -t IMAGE_IDS < <(docker inspect --format '{{.Image}}' "${TARGETS[@]}" | sort -u)
docker image inspect "${IMAGE_IDS[@]}" > "$BAK/images.inspect.json"
docker image save "${IMAGE_IDS[@]}" > "$BAK/images.tar"
```

This saves the image IDs actually used by the containers. Save any stopped MCP, sandbox, or other images that are still required for rollback separately. Images exported by ID may have no original tag after loading, so use `images.txt` to restore tags. If one tag maps to multiple running image IDs, assign a distinct tag to each version first and record the service mapping.

Set and record the following variables based on `mounts.txt`. The user directory is not necessarily under `ROOT_DIR`; the current Docker deployment script uses `$HOME/nexent` for the user who runs deployment. Run upgrades with the same account and verify the actual mount.

```bash
DATA_DIR=/srv/nexent-data
USER_DATA_DIR=/home/deploy/nexent
test -d "$DATA_DIR"
test -d "$USER_DATA_DIR"
printf 'CODE_DIR=%s\nDATA_DIR=%s\nUSER_DATA_DIR=%s\n' \
  "$CODE_DIR" "$DATA_DIR" "$USER_DATA_DIR" > "$BAK/paths.txt"
```

These are examples and must match the actual Mounts. If the user directory is already inside the data directory, do not overwrite it twice during recovery. List other external bind mounts and symlink targets separately. Do not copy runtime interfaces such as `/var/run/docker.sock`.

### 3.2 Stop Entry Points and Writes

1. Put the gateway or load balancer into maintenance mode and restrict direct API access.
2. Pause scheduled jobs, uploads, and external calls. Wait for agent runs, Celery queues, and document-processing jobs to finish, and record unfinished work.
3. Stop applications and every other writer, but leave PostgreSQL, Elasticsearch, MinIO, and Redis running for the next backup steps. If Supabase is enabled, stop authentication entry points and services as well so no new users or sessions are created.

Example for stopping the default application containers:

```bash
APP_WRITERS=(nexent-web nexent-config nexent-runtime nexent-mcp nexent-northbound nexent-data-process)
for container in "${APP_WRITERS[@]}"; do
  if docker container inspect "$container" >/dev/null 2>&1; then
    docker stop --time 120 "$container"
  fi
done
```

Continue with any enabled Supabase auth or Kong services, terminals, dynamic sandboxes, and monitoring writers from the actual inventory. `docker stop` forcibly terminates a process after the timeout, so check the logs and confirm databases can shut down cleanly. The backups from different stores form a consistent recovery point only after every business writer has stopped.

### 3.3 Export Both PostgreSQL Databases

Use the container environment variables for the application database instead of assembling passwords manually:

```bash
docker exec nexent-postgresql sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$BAK/nexent.dump"
docker exec nexent-postgresql sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dumpall -U "$POSTGRES_USER" --globals-only' \
  > "$BAK/nexent-globals.sql"
docker exec -i nexent-postgresql pg_restore --list \
  < "$BAK/nexent.dump" > "$BAK/nexent-dump-toc.txt"
```

When built-in Supabase is enabled, export its database and roles separately:

```bash
docker exec supabase-db-mini sh -c \
  'pg_dump -U postgres -d "$POSTGRES_DB" -Fc' > "$BAK/supabase.dump"
docker exec supabase-db-mini sh -c \
  'pg_dumpall -U postgres --globals-only' > "$BAK/supabase-globals.sql"
docker exec -i supabase-db-mini pg_restore --list \
  < "$BAK/supabase.dump" > "$BAK/supabase-dump-toc.txt"
```

The Supabase container already defines `PGPORT` and `PGPASSWORD`. Adjust the container name, database name, or deployment method to match the environment, and export any additional application databases separately. `pg_restore --list` only proves that the archive can be read; full validation still requires a restore in an isolated environment.

### 3.4 Create an Elasticsearch Snapshot

**Do not treat a file copy of the Elasticsearch data directory as a supported recovery method, even while Elasticsearch is stopped.** A working Snapshot repository must exist before the upgrade, and its storage must not depend on the production data directory that will be replaced. Preserve the repository storage, registration settings, and credentials.

Configure and test the repository in advance. For an `fs` repository, configure `path.repo` on the Elasticsearch nodes, mount a dedicated backup directory with the correct permissions, restart Elasticsearch, and then register the repository. For S3, configure the actual endpoint and keystore credentials. The default Compose setup does not configure a Snapshot repository. Save these settings as deployment customizations and remount them during upgrade and recovery; calling the API without preparing repository storage is insufficient. See [Register a snapshot repository](https://www.elastic.co/guide/en/elasticsearch/reference/8.17/snapshots-register-repository.html).

The following example assumes the repository is registered. Replace `ES_INDICES` with the actual list of business indices or data streams. Verify the list against the index inventory and application configuration so no knowledge base is omitted, and exclude system indices such as `.security*`.

```bash
ES_REPO=nexent-backup
ES_SNAPSHOT="pre-upgrade-$STAMP"
ES_INDICES='knowledge_index_a,knowledge_index_b'

es_request() {
  docker exec nexent-elasticsearch sh -c \
    'curl -fsS -u "elastic:$ELASTIC_PASSWORD" -H "Content-Type: application/json" "$@"' \
    sh "$@"
}

es_request 'http://localhost:9200/_cat/indices?format=json&expand_wildcards=all' \
  > "$BAK/es-indices.json"
es_request "http://localhost:9200/_snapshot/$ES_REPO" > "$BAK/es-repository.json"
es_request -X POST "http://localhost:9200/_snapshot/$ES_REPO/_verify" \
  > "$BAK/es-repository-verify.json"
es_request 'http://localhost:9200/_index_template' > "$BAK/es-index-templates.json"
es_request 'http://localhost:9200/_component_template' > "$BAK/es-component-templates.json"
es_request 'http://localhost:9200/_template' > "$BAK/es-legacy-templates.json"
es_request -X PUT \
  "http://localhost:9200/_snapshot/$ES_REPO/$ES_SNAPSHOT?wait_for_completion=true" \
  -d "{\"indices\":\"$ES_INDICES\",\"ignore_unavailable\":false,\"include_global_state\":false,\"feature_states\":[\"none\"]}" \
  > "$BAK/es-snapshot-result.json"
es_request "http://localhost:9200/_snapshot/$ES_REPO/$ES_SNAPSHOT" \
  > "$BAK/es-snapshot-status.json"
printf 'repository=%s\nsnapshot=%s\nindices=%s\n' \
  "$ES_REPO" "$ES_SNAPSHOT" "$ES_INDICES" > "$BAK/es-restore-point.txt"
```

The result must be `SUCCESS` with zero failed shards, and the index list must match expectations. A successful HTTP request or the existence of a JSON file does not replace this check. If a request times out, query the snapshot status first; do not copy or clean the repository while a snapshot is in progress.

This backs up business indices but not Elasticsearch system security state. Export and rehearse rebuilding custom ILM policies, ingest pipelines, cluster settings, users, and roles separately. Generate a new Nexent Elasticsearch API key after restoring business indices. Index data, mappings, and aliases are restored with the snapshot; recreate templates individually from the exported definitions.

### 3.5 Stop Storage and Archive Data Directories and Named Volumes

After the logical database backups and Elasticsearch snapshot finish, stop all remaining containers in the inventory. Every writer to the backup data must stay stopped, including monitoring components and external clients. Do not run deployment scripts or allow automation to restart services during the archive.

```bash
for container in "${TARGETS[@]}"; do
  docker stop --time 120 "$container"
done
docker inspect --format '{{.Name}} {{.State.Running}} {{.State.ExitCode}} {{.State.OOMKilled}}' \
  "${TARGETS[@]}" > "$BAK/stopped-state.txt"
```

Confirm that every container stopped, the storage logs show clean shutdowns, and no process was forcibly terminated or OOM-killed. Then create the archives. The example user and data directories are independent; the raw Elasticsearch data directory is explicitly excluded.

```bash
sudo tar --numeric-owner --acls --xattrs --exclude='./elasticsearch' \
  -cpf - -C "$DATA_DIR" . > "$BAK/data-root.tar"
sudo tar --numeric-owner --acls --xattrs \
  -cpf - -C "$USER_DATA_DIR" . > "$BAK/user-data.tar"

tar --exclude='./.git' --exclude='node_modules' --exclude='.venv' \
  -cpf "$BAK/release.tar" -C "$CODE_DIR" .
```

Archive external terminal directories, proxy configuration, certificates, and custom bind mounts separately in the same way, and record their original paths. `release.tar` preserves the environment, including untracked deployment configuration. If it contains root-only files, archive it with an account that can read them; do not ignore tar errors.

Archive named volumes through a helper container on the Docker daemon host. Prepare a trusted helper image containing GNU tar in advance. Production environments can replace this reference with a verified digest, and offline environments must load it before maintenance.

```bash
BACKUP_HELPER_IMAGE=ubuntu:24.04
docker image inspect "$BACKUP_HELPER_IMAGE" >/dev/null
mkdir -p "$BAK/volumes"
while IFS= read -r volume; do
  docker volume inspect "$volume" > "$BAK/volumes/$volume.inspect.json"
  docker run --rm --network none --user 0 \
    -v "$volume:/source:ro" "$BACKUP_HELPER_IMAGE" \
    tar --numeric-owner --acls --xattrs -cpf - -C /source . \
    > "$BAK/volumes/$volume.tar"
done < "$BAK/volumes.txt"
```

Verify that the inventory includes the actual agent workspace, the Supabase configuration volume, and all enabled monitoring volumes. The storage platform defines permissions and consistency requirements for remote volume drivers. This archive procedure is only for volumes that have stopped receiving writes and support file-level archives.

### 3.6 Verify and Store Off-host

```bash
test -s "$BAK/nexent.dump"
tar -tf "$BAK/data-root.tar" > "$BAK/data-root-files.txt"
tar -tf "$BAK/user-data.tar" > "$BAK/user-data-files.txt"
tar -tf "$BAK/release.tar" > "$BAK/release-files.txt"
for archive in "$BAK"/volumes/*.tar; do
  test -f "$archive" || continue
  tar -tf "$archive" >/dev/null
done
(
  cd "$BAK"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)
```

Copy the directory and the Elasticsearch snapshot repository to another host or independent backup storage, then verify them at the destination. Before copying an Elasticsearch repository, make sure no snapshot, deletion, or other repository write is in progress. Preserve the entire repository layout; copying only files that appear to belong to one snapshot is unsupported. The Elasticsearch JSON result files do not contain index data.

Record the backup completion time, each storage restore point, checksum results, and recovery-drill results. Do not begin the upgrade if the backup fails. If maintenance is canceled, restore only the services listed in `running-before.txt`, in dependency order, and validate them so originally disabled services are not started by mistake.

## 4. Docker: Perform the Upgrade

### 4.1 Online Source Tree or Release Package

Prepare the target version in a separate directory in advance and retain the old deployment directory. When retrieving a release with Git, use a tag that you have confirmed exists, for example:

```bash
TARGET_REF=vX.Y.Z
NEW_CODE_DIR=/opt/nexent-release-X.Y.Z
git clone --branch "$TARGET_REF" --depth 1 \
  https://github.com/ModelEngine-Group/nexent.git "$NEW_CODE_DIR"
```

Reuse the old environment configuration in the new directory without overwriting new templates or SQL:

```bash
cp -p "$CODE_DIR/deploy/env/.env" "$NEW_CODE_DIR/deploy/env/.env"
if test -f "$CODE_DIR/deploy/env/monitoring.env"; then
  cp -p "$CODE_DIR/deploy/env/monitoring.env" "$NEW_CODE_DIR/deploy/env/monitoring.env"
fi
cp -p "$CODE_DIR/deploy/docker/deploy.options" "$NEW_CODE_DIR/deploy/docker/deploy.options"
```

If no old `deploy.options` exists, reproduce the recorded deployment choices instead of accepting unchecked defaults. Merge custom Compose files, reverse-proxy configuration, and snapshot-repository settings individually; do not copy the entire old `deploy/` directory over the new version.

Verify `ROOT_DIR`, secrets, components, ports, user directory, image source, and target version in the new directory, then run the following from the **new directory**:

```bash
cd "$NEW_CODE_DIR"
set -o pipefail
bash deploy.sh docker --defaults --version X.Y.Z 2>&1 | tee "$BAK/upgrade.log"
```

`X.Y.Z` is the application version used for images and might not exactly match the Git tag prefix. Verify it against the release package and registry. A saved `local-latest` selection uses local `latest` images, so `--version` alone does not prove an upgrade occurred. Verify the new local image IDs or explicitly select an image source for the release version. Stop immediately if the deployment summary or actual images do not match expectations.

### 4.2 Offline Deployment Package

Verify and extract the complete target offline package before maintenance, and keep the old package and images. Run the following from the new offline package root:

```bash
bash deploy.sh --load-images --reuse-from /opt/nexent-old-package --defaults docker
```

Only the offline package entrypoint supports `--reuse-from`. It reuses `.env`, `monitoring.env`, and Docker deployment options from the old package. The source-repository entrypoint does not support this option. If the original deployment does not use this directory structure, migrate the configuration manually as described above. Validate the offline image loader, architecture, and all dependency images before maintenance; do not wait until downtime to download missing images.

### 4.3 Understand Automatic Database Migrations

- In both Docker and Kubernetes, only `nexent-config` runs automatic migrations; the other related backend services wait for migrations to reach the target state.
- `deploy/sql/init.sql` runs as part of the migration process, and `deploy/sql/migrations/*.sql` files are processed in version-filename order. Records are stored in `nexent.schema_migrations`.
- A migration with the same checksum is skipped. A checksum change reruns that file and may also rerun later files. Therefore, **no merged SQL file may be modified, renamed, or deleted**, including init and Supabase SQL. Database changes must add a new versioned migration.
- Automatic migrations do not provide generic down migrations. A failed run may have already applied part of the SQL, so inspect the logs and actual database state instead of assuming that an error means nothing changed.

`deploy/docker/upgrade.sh` is deprecated and only forwards to the deployment script. Always use `bash deploy.sh docker` for upgrades. Do not prepare an upgrade with the uninstall script, `down -v`, volume prune, or forced image cleanup.

## 5. Validate the Upgrade and Restore Traffic

Keep maintenance mode enabled while checking the following items. A visible Web page or containers in the `Up` state is not sufficient validation.

```bash
docker ps -a --filter label=com.docker.compose.project=nexent
docker logs --tail 200 nexent-config
docker logs --tail 200 nexent-runtime
docker exec nexent-postgresql sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT migration_id, status, app_version, executed_at FROM nexent.schema_migrations ORDER BY migration_id;"'
docker exec nexent-redis redis-cli ping
```

Inspect `[sql-migrations]` messages from `nexent-config` and compare the migration records with the target version's SQL files. If Data Process, Supabase, MCP, or monitoring is enabled, check those container states and logs as well.

| Validation area | Pass criteria |
| --- | --- |
| Version and startup | Actual images match the target IDs or digests; services remain stable with no repeated restarts, OOM events, migration failures, or wait timeouts |
| Login and permissions | Existing users can log in; tenants, roles, and permissions work; existing accounts work when Supabase is enabled |
| Agents | Existing configuration is readable; a test agent completes a model request, streaming response, and tool call |
| Knowledge bases | Existing knowledge bases are searchable and cited sources open; index and document counts match the baseline; no primary shard is unassigned |
| File processing | A test file can be uploaded, parsed, indexed, retrieved, and downloaded; the test artifact is traceable and removed afterward |
| Persistent data | Samples of important records, MinIO objects, and workspace files match; approximate total counts do not replace checking critical records |
| Optional components | Validate enabled MCP, sandbox, terminal, and monitoring traces; queues have no abnormal backlog or duplicate tasks |

A single-node Elasticsearch cluster may be `yellow` because replicas are unassigned; confirm that all primary shards are healthy. A `red` cluster or missing business indices cannot pass. After validation, restore entry points, scheduled jobs, and external calls gradually. Monitor error rates, latency, and queues throughout the agreed observation period. Keep the upgrade log, old images, and backups.

## 6. Docker: Roll Back

### 6.1 Choose the Recovery Scope

| Situation | Response |
| --- | --- |
| The new version never started, with no migration or new writes | Restore the old code, configuration, and images, then start against the existing data |
| The new version started, and the old application is verified compatible with the current schema and storage formats | Roll back only the application; still use the old configuration and SQL set, then perform full validation |
| A migration failed, data was transformed, middleware formats changed, or compatibility is uncertain | Restore the matching database, objects, indices, workspaces, and other backups from the same maintenance window before starting the old version |
| Traffic reopened after upgrade and new data exists | Preserve the failed environment and decide how to handle the new data before recovery; do not overwrite it with an old backup and claim there was no data loss |

**Changing an image tag, Git commit, or Helm revision does not roll back PostgreSQL, MinIO, Elasticsearch, or persistent volumes.** Before rollback, close entry points again, stop writes, and preserve failure logs, current image details, migration records, and any necessary copy of the failed data.

### 6.2 Restore the Old Deployment Assets

The following procedure performs a full data restore. Skip the data-restoration steps only when an application-only rollback has been verified safe. In a new shell, set `BAK`, `CODE_DIR`, `DATA_DIR`, and `USER_DATA_DIR` from the backup record; do not reuse unchecked example values.

1. Verify `SHA256SUMS` and the Elasticsearch snapshot status. Stop all current writers and storage services.
2. Preserve the failed environment in a separate directory or storage snapshot. Extract `release.tar` into an empty directory at the original absolute deployment path, or use the fully preserved old deployment directory. Do not mix in new SQL, configuration, or scripts.
3. Load the old images and restore their tags according to the backup mapping. **Run this only on the target deployment host**, because it changes where identical local tags point.

```bash
docker image load < "$BAK/images.tar"
while read -r container image_ref image_id; do
  docker image inspect "$image_id" >/dev/null
  case "$image_ref" in
    *@sha256:*)
      printf 'Verify digest reference separately: %s\n' "$image_ref"
      continue
      ;;
  esac
  docker image tag "$image_id" "$image_ref"
done < "$BAK/images.txt"
```

The script skips `repository@sha256:...` references. Verify separately that each digest is available and matches the saved ID, or assign a dedicated rollback tag to the saved ID and reference it explicitly from the old configuration; `docker image tag` cannot use a digest as its destination. Resolve any same-tag, multiple-ID cases described earlier before restoring images. Do not let the last line in the loop arbitrarily determine the version for multiple services.

### 6.3 Restore Data into Empty Directories or Volumes

Use physical archives only with the same database and storage image versions on compatible platforms. Never pass old PostgreSQL physical data to a different major version, and never extract a backup over existing database files. The example assumes independent data and user directories with no mount still in use by another service:

```bash
FAILED_STAMP=$(date -u +%Y%m%d-%H%M%S)
sudo mv "$DATA_DIR" "${DATA_DIR}.failed-$FAILED_STAMP"
sudo mkdir -p "$DATA_DIR"
sudo tar --numeric-owner --same-owner --acls --xattrs \
  -xpf "$BAK/data-root.tar" -C "$DATA_DIR"
sudo mkdir -p "$DATA_DIR/elasticsearch"
sudo chown --reference="${DATA_DIR}.failed-$FAILED_STAMP/elasticsearch" "$DATA_DIR/elasticsearch"
sudo chmod --reference="${DATA_DIR}.failed-$FAILED_STAMP/elasticsearch" "$DATA_DIR/elasticsearch"

sudo mv "$USER_DATA_DIR" "${USER_DATA_DIR}.failed-$FAILED_STAMP"
sudo mkdir -p "$USER_DATA_DIR"
sudo tar --numeric-owner --same-owner --acls --xattrs \
  -xpf "$BAK/user-data.tar" -C "$USER_DATA_DIR"
```

The example creates an empty Elasticsearch directory and copies ownership and permissions from the failed environment so Docker does not create a root-owned directory that Elasticsearch cannot use. If the actual Elasticsearch path differs or the failed environment is damaged, use the pre-upgrade record and old image requirements to set permissions. If the data directory itself is a separate disk mount, do not use the `mv` example. Preserve the failed environment with a storage snapshot, restore into a new empty directory or disk, and update the mount. Restore other bind mounts from the inventory while preserving UID/GID, ACLs, and required SELinux labels.

Restore named volumes into **new empty volumes** so the old volumes remain available for failure analysis. For example, restore the agent workspace:

```bash
SOURCE_VOLUME=nexent-agent-workspace
RESTORED_VOLUME="nexent-agent-workspace-restored-$FAILED_STAMP"
BACKUP_HELPER_IMAGE=ubuntu:24.04
docker volume create "$RESTORED_VOLUME"
docker run --rm -i --network none --user 0 \
  -v "$RESTORED_VOLUME:/restore" "$BACKUP_HELPER_IMAGE" \
  tar --numeric-owner --same-owner --acls --xattrs -xpf - -C /restore \
  < "$BAK/volumes/$SOURCE_VOLUME.tar"
```

Point `NEXENT_SANDBOX_WORKSPACE_VOLUME` in the old `.env` to the new volume. Restore other volumes the same way, bind them explicitly with Compose override `name` or `external` settings, and verify the actual Mounts. `docker volume create` without a driver applies only to local volumes; recreate custom drivers according to the original record. Do not omit monitoring or Supabase named volumes.

At this point, the stopped physical archives have already restored the application and Supabase PostgreSQL data; do not import the `.dump` files into them again. If you choose logical recovery, use a separate empty PostgreSQL instance of the matching version. Verify roles and extensions first, then restore into a new empty database with `pg_restore --exit-on-error`. Supabase also requires its dedicated roles, extensions, and initialization order. Rehearse logical recovery before production, and never run `--clean` or unchecked globals SQL directly against production.

### 6.4 Restore Storage Before Starting the Old Application

**Do not run the full deployment script before Elasticsearch recovery.** It starts applications and automatic migrations. First use the old Compose configuration to start storage only. The following function targets the default project. If recovery volumes or Elasticsearch repository overrides are required, add the corresponding `-f` arguments and inspect the final configuration first.

```bash
cd "$CODE_DIR"
set -a
source "$CODE_DIR/deploy/docker/.env.generated"
set +a
export NEXENT_USER_DIR="$USER_DATA_DIR"
COMPOSE_MAIN="$CODE_DIR/deploy/docker/compose/docker-compose.yml"
COMPOSE_AUTH="$CODE_DIR/deploy/docker/compose/docker-compose-supabase.yml"

dc() {
  docker compose --env-file "$CODE_DIR/deploy/env/.env" -p nexent \
    -f "$COMPOSE_MAIN" "$@"
}
dc config --quiet
dc up -d --no-build --force-recreate nexent-postgresql redis nexent-minio nexent-elasticsearch
```

For production port policies, add `docker-compose.prod.yml` and `docker-compose-supabase.prod.yml`. Only source the saved and verified `.env.generated`; it contains image variables required by Compose. Do not assume that specifying `.env` alone resolves every image. If `.env.generated` is absent, reconstruct the image variables from the old deployment record rather than starting applications to generate it. Check that every reference points to the loaded old image before startup so an overwritten tag is not pulled from the registry.

When Supabase is enabled, start only its database and wait for readiness:

```bash
docker compose --env-file "$CODE_DIR/deploy/env/.env" -p nexent \
  -f "$COMPOSE_AUTH" up -d --no-build --force-recreate db
```

Because the raw Elasticsearch directory was excluded from the backup, Elasticsearch should now be an empty cluster running the old image version. Redefine the `es_request` function from section 3.4, and restore `ES_REPO`, `ES_SNAPSHOT`, and `ES_INDICES` from `es-restore-point.txt`. Mount and register the pre-upgrade snapshot repository. Register it read-only on the recovery target so multiple clusters cannot write to the same repository. This `fs` registration example works only after `path.repo` and the backup-directory mount are prepared:

```bash
es_request -X PUT "http://localhost:9200/_snapshot/$ES_REPO" \
  -d '{"type":"fs","settings":{"location":"/mnt/es-backup","readonly":true}}'
```

Confirm that the snapshot is compatible with the running Elasticsearch version and that no business index conflicts exist. Recreate required templates first; data streams especially require their templates. Then restore the business snapshot:

```bash
es_request -X POST \
  "http://localhost:9200/_snapshot/$ES_REPO/$ES_SNAPSHOT/_restore?wait_for_completion=true" \
  -d "{\"indices\":\"$ES_INDICES\",\"include_global_state\":false,\"feature_states\":[\"none\"]}"
es_request 'http://localhost:9200/_cluster/health?wait_for_status=yellow&timeout=120s'
es_request 'http://localhost:9200/_cat/indices?format=json&expand_wildcards=all'
```

Verify zero failed shards in the restore response, no health-check timeout, every business primary shard available, and index and document baselines intact. Start the old applications only after MinIO objects, both PostgreSQL databases, and workspaces have also been verified.

Elasticsearch system security state is not restored with the business snapshot, so generate a new `ELASTICSEARCH_API_KEY`. For the default deployment, run `bash deploy.sh docker --defaults --version OLD_VERSION --refresh-es-key` from the **old directory with the old application version**, then validate as described in section 5. This entrypoint may also pull MCP and sandbox images, so first ensure every old-version reference points to the correct archived image. The current deployment entrypoint does not automatically include manually added Compose overrides. If recovery uses new named volumes or snapshot-repository overrides, integrate those customizations into the recovery deployment configuration or use the rehearsed Compose startup procedure so a full deployment cannot switch mounts back to the old volumes.

Keep maintenance mode enabled after recovery. Confirm that the old version will not reprocess unfinished jobs, then restore authentication, application entry points, and scheduled jobs. End the rollback only after validation passes.

## 7. Kubernetes: Backup, Upgrade, and Rollback

Kubernetes follows the same consistency and versioning principles, but data is managed through PVCs, PVs, and the storage platform. **A Helm release export is not a data backup, and `helm rollback` does not restore PVC contents or database schemas.**

### 7.1 Save the Release, Configuration, and Storage Inventory

The default namespace and release are both `nexent`; change them to match the environment. Store the backup directory on reliable administrative storage and use a restricted Bash session.

```bash
set -euo pipefail
umask 077
NS=nexent
RELEASE=nexent
K8S_BAK="/backup/nexent/k8s-$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$K8S_BAK"

helm history "$RELEASE" -n "$NS" > "$K8S_BAK/helm-history.txt"
helm get values "$RELEASE" -n "$NS" --all > "$K8S_BAK/helm-values.yaml"
helm get manifest "$RELEASE" -n "$NS" > "$K8S_BAK/helm-manifest.yaml"
kubectl get deployment,statefulset,cronjob,hpa -n "$NS" -o yaml > "$K8S_BAK/workloads.yaml"
kubectl get pods -n "$NS" -o json > "$K8S_BAK/pods.json"
kubectl get pvc -n "$NS" -o yaml > "$K8S_BAK/pvc.yaml"
kubectl get pv -o yaml > "$K8S_BAK/pv.yaml"
kubectl get configmap,secret -n "$NS" -o yaml > "$K8S_BAK/config-and-secrets.yaml"
```

PV listing is cluster-wide and requires the corresponding permission; retain only records needed for this recovery. Base64 encoding in a Secret is not encryption. These inventories are for recovery comparison. Do not treat exports containing server-managed fields such as `uid`, `resourceVersion`, or `status` as directly reusable deployment templates.

Separately preserve `.env`, `monitoring.env`, `deploy/k8s/deploy.options`, Charts, and `generated-*.yaml` from the original deployment directory. Record the actual Pod `imageID` values and archive old images. Generated values may contain secrets and must not be committed.

### 7.2 Stop Writes and Back Up Persistent Data

Put the Ingress or gateway into maintenance mode first. Pause CronJobs, external calls, GitOps reconciliation, and HPAs that could restore replicas, while recording the original replica counts. Drain jobs, then scale application writers to zero while leaving storage services running for logical backups. For example:

```bash
kubectl scale deployment/nexent-web deployment/nexent-config \
  deployment/nexent-runtime deployment/nexent-mcp deployment/nexent-northbound \
  -n "$NS" --replicas=0
```

Add Data Process, Supabase auth, terminals, dynamic workloads, and monitoring writers as enabled. Wait until their Pods have fully exited; a successful scale command alone is insufficient. Example logical backup for the application database:

```bash
kubectl exec -n "$NS" deployment/nexent-postgresql -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$K8S_BAK/nexent.dump"
kubectl exec -n "$NS" deployment/nexent-postgresql -- sh -c \
  'PGPASSWORD="$POSTGRES_PASSWORD" pg_dumpall -U "$POSTGRES_USER" --globals-only' \
  > "$K8S_BAK/nexent-globals.sql"
```

When Supabase is enabled, export its database and roles separately from `deployment/nexent-supabase-db` as described in section 3.3. Create the Elasticsearch business snapshot as described in section 3.4 through in-cluster access or a controlled port-forward. Do not use a file copy of the Elasticsearch data directory as a recovery method.

Handle the remaining PVCs according to their storage type, including PostgreSQL, Supabase, MinIO, Redis, `nexent-workspace`, `nexent-skills`, and monitoring PVCs:

| Persistence type | Backup and recovery requirements |
| --- | --- |
| `local` | Save PV paths, nodes, and affinity. After stopping the corresponding storage Pods cleanly, archive the directories on their actual nodes. Default data is under `/var/lib/nexent-data`, while the shared workspace defaults to `/var/lib/nexent`; verify them separately |
| `dynamic`, with CSI snapshot support | Create VolumeSnapshots with the actual driver. Verify `readyToUse`, retention policy, and off-site protection. Stop application and database writes according to the backup policy; one volume snapshot does not automatically provide consistency across volumes |
| `existing` or external storage | Back up on the actual storage platform. Record the claim, driver, snapshot ID, capacity, access mode, and recovery binding procedure |

Kubernetes does not guarantee that VolumeSnapshot CRDs or a VolumeSnapshotClass are installed. Do not copy snapshot YAML from another cluster without checking. Verify the backup, run an isolated recovery drill, and record the corresponding release revision.

### 7.3 Upgrade

Prepare the target directory as described in section 4. Reuse `.env`, `monitoring.env`, and `deploy/k8s/deploy.options`, then merge persistence and other customizations individually. Run the following from the target directory:

```bash
set -o pipefail
bash deploy.sh k8s --defaults --version X.Y.Z 2>&1 | tee "$K8S_BAK/upgrade.log"
kubectl get pods,pvc -n "$NS"
kubectl rollout status deployment/nexent-config -n "$NS" --timeout=600s
kubectl rollout status deployment/nexent-runtime -n "$NS" --timeout=600s
kubectl logs -n "$NS" deployment/nexent-config --tail=200
```

The current script uses `helm upgrade --install`; this does not give the database automatic rollback. Check every enabled rollout and business function, complete the validation in section 5, and only then restore traffic. `generated-*.yaml` files are regenerated during deployment, so make persistent changes in source values or deployment parameters.

### 7.4 Roll Back

For an **application-only rollback with verified schema and storage compatibility**, use the recorded revision while maintenance mode remains enabled:

```bash
ROLLBACK_REVISION=3
helm rollback "$RELEASE" "$ROLLBACK_REVISION" -n "$NS" --wait --timeout 10m
kubectl get pods,pvc -n "$NS"
```

`3` is only an example; do not assume the immediately preceding revision is usable. Helm rollback restores old resource configuration and may start applications immediately, so it is not the first step in a full data recovery. Old images must remain pullable or be prepared on the nodes.

For full data recovery, proceed in this order:

1. Close entry points, pause controllers that restore replicas automatically, and stop every writer. Preserve the failed environment and snapshots of current PVCs.
2. Restore new empty PVCs or local directories from the same backup window while retaining the failed PVCs. Check PV reclaim policies so deleting a claim cannot delete the underlying data. Restore both databases, MinIO, Redis, workspaces, skills, and any monitoring data that must be retained.
3. Build recovery values from the old Chart and configuration: set every application writer replica to zero and bind every persistent volume explicitly to the restored claim. Use `helm template` to verify replica counts and volume bindings before starting old-version storage through the recovery Helm configuration. Do not run the full deployment entrypoint, which regenerates values and starts applications.
4. Restore the business Elasticsearch snapshot and templates, verify every store, and recreate required credentials. Do not restore a snapshot made by a newer Elasticsearch version into an incompatible older version; use the pre-upgrade snapshot with its original Elasticsearch version.
5. Save the recovered credentials and volume bindings in the persistent configuration source, then restore the old applications gradually to their original replica counts. Check migration logs, validate as described in section 5, and only then restore traffic, scheduled jobs, HPA, and GitOps reconciliation.

## 8. Maintenance Record Template

Keep one record for each maintenance event so restore points can be identified and handed over:

| Item | Information to record |
| --- | --- |
| Environment and owners | Deployment host or cluster, namespace, operator, and reviewer |
| Versions | Old and new Git commits or package versions, image IDs or digests, and Helm revision |
| Configuration | Deployment path, components, ports, image source, data directories, or PVC inventory |
| Backups | Backup directory, off-host location, completion time, checksums, and Elasticsearch snapshot name |
| Recovery validation | Drill date, recovery duration, and critical data sample results |
| Schedule | Maintenance window, latest rollback time, RPO/RTO, observation period, and retention deadline |
| Execution result | Upgrade log, migration status, validation result, and time traffic reopened |
| Rollback | Trigger, restore point, treatment of new data, and post-recovery validation result |

Related entry points: [Docker Installation](./installation.md) and [Kubernetes Installation](./kubernetes-installation.md).
