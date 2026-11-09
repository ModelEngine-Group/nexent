#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
# Kubernetes API operations stay on the host; the Job only connects to PostgreSQL.
job_name="account-migration-$(date +%s)-$$-$RANDOM"
secret_created=false job_created=false credential_dir=""
finish_kubernetes() {
  if [ "$job_created" = true ]; then platform delete job "$job_name" --ignore-not-found --timeout=30s >/dev/null 2>&1 || printf 'Migration Job cleanup incomplete: %s\n' "$job_name" >&2; fi
  if [ "$secret_created" = true ]; then platform delete secret "$job_name" --ignore-not-found >/dev/null 2>&1 || printf 'Migration Secret cleanup incomplete: %s\n' "$job_name" >&2; fi
  if [ -n "$credential_dir" ] && [ -d "$credential_dir" ]; then
    # Only remove files created by this invocation, never recursively delete paths.
    for key in "${connection_keys[@]}" job.yaml; do rm -f "$credential_dir/$key"; done
    rmdir "$credential_dir" 2>/dev/null || true
  fi
}
trap finish_kubernetes EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
quote_yaml() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/''/g")"; }
host_file() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
kube_address() {
  local selected="$1" value
  local service_name="${selected##*/}"
  value="$(platform get service "$service_name" --ignore-not-found -o 'jsonpath={.spec.clusterIP}')"
  if [ -n "$value" ] && [ "$value" != None ]; then printf '%s' "$selected"; return; fi
  inside "$selected" hostname -i | awk '{print $1}'
}
preserve_source_storage() {
  local claims claim volume backup_dir
  claims="$(platform get deployment "$source_name" -o 'jsonpath={range .spec.template.spec.volumes[*]}{.persistentVolumeClaim.claimName}{"\n"}{end}')"
  [ -n "$(printf '%s' "$claims" | tr -d '[:space:]')" ] || fail "Original source has no persistent claim; verify source storage"
  backup_dir="$(dirname "$env_file")/backups"; mkdir -p "$backup_dir"; chmod 700 "$backup_dir"
  platform get deployment "$source_name" -o yaml > "$backup_dir/$job_name-source.yaml"
  while IFS= read -r claim; do
    [ -n "$claim" ] || continue
    volume="$(platform get pvc "$claim" -o 'jsonpath={.spec.volumeName}')"
    [ -n "$volume" ] || fail "Source PVC is not bound; original application was retained"
    platform get pvc "$claim" -o yaml > "$backup_dir/$job_name-$claim.yaml"
    platform get pv "$volume" -o yaml > "$backup_dir/$job_name-$volume.yaml"
    platform patch pv "$volume" --type=merge -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}' >/dev/null
  done <<< "$claims"
}
job_diagnostics() {
  # Only names and lifecycle reasons; never print pod env or Secret contents.
  platform get pods -l "job-name=$job_name" -o 'jsonpath={range .items[*]}{.metadata.name}{" "}{range .status.initContainerStatuses[*]}{.state.waiting.reason}{.state.terminated.reason}{" "}{end}{range .status.containerStatuses[*]}{.state.waiting.reason}{.state.terminated.reason}{" "}{end}{"\n"}{end}' >&2 || true
}
connection_keys=(POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_DB NEXENT_POSTGRES_PASSWORD
  SUPABASE_POSTGRES_HOST SUPABASE_POSTGRES_PORT SUPABASE_POSTGRES_USER SUPABASE_POSTGRES_DB SUPABASE_POSTGRES_PASSWORD)
run_migration() {
  local host="${SUPABASE_POSTGRES_HOST:-}" present replicas key phase output pull_secrets pull_secret
  case "$host" in ''|supabase_db|supabase-db-mini|nexent-supabase-db) host="" ;; esac
  source_name="${source_name:-${SUPABASE_MIGRATION_DB_CONTAINER:-}}"
  if [ -z "$host" ] || [ -n "$source_name" ]; then
    source_name="${source_name:-nexent-supabase-db}"
    [ "$source_name" != "${database##*/}" ] || fail "Source cleanup must not select the target database"
    present="$(platform get deployment "$source_name" --ignore-not-found -o name)"
    [ -n "$present" ] || fail "The original Supabase database is required; restore its original data before retrying"
    log_stage storage "Preserving original Kubernetes storage definitions and PV retention policy."
    preserve_source_storage
    replicas="$(platform get deployment "$source_name" -o 'jsonpath={.spec.replicas}')"
    if [ "$replicas" = 0 ]; then
      [ "$allow_start" = true ] || fail "Original Supabase source is stopped"
      platform scale "deployment/$source_name" --replicas=1 >/dev/null
    fi
    platform rollout status "deployment/$source_name" --timeout="${timeout}s" >/dev/null
    source_host="$(kube_address "$source_name")"
  else
    source_host="$host"
    case "$host" in localhost|127.0.0.1) fail "A Kubernetes Job needs a source host reachable from the cluster" ;; esac
  fi
  log_stage source "Original source selected: ${source_name:-remote}; resolving credentials without logging them."
  get_source
  target_host="$(kube_address "$database")"
  local service_port
  service_port="$(platform get service "${database##*/}" --ignore-not-found -o 'jsonpath={.spec.ports[0].port}')"
  target_port="${service_port:-$target_port}"
  if [ -n "$source_name" ]; then
    service_port="$(platform get service "$source_name" --ignore-not-found -o 'jsonpath={.spec.ports[0].port}')"
    source_port="${service_port:-$source_port}"
  fi
  export_connections
  credential_dir="$(mktemp -d "${TMPDIR:-/tmp}/nexent-account.XXXXXXXX")"
  local secret_args=()
  for key in "${connection_keys[@]}"; do
    printf '%s' "${!key}" > "$credential_dir/$key"
    secret_args+=("--from-file=$key=$(host_file "$credential_dir/$key")")
  done
  # Create fails on a name collision; never modify an existing resource.
  platform create secret generic "$job_name" "${secret_args[@]}" >/dev/null
  secret_created=true
  pull_secrets="$(platform get deployment "${config_target:-nexent-config}" --ignore-not-found -o 'jsonpath={range .spec.template.spec.imagePullSecrets[*]}{.name}{"\n"}{end}')"
  {
    cat <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: $job_name
spec:
  backoffLimit: 0
  activeDeadlineSeconds: $((timeout + 60))
  template:
    metadata:
      labels:
        app.kubernetes.io/name: nexent-account-migration
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      containers:
        - name: migration
          image: $(quote_yaml "$NEXENT_IMAGE")
          imagePullPolicy: IfNotPresent
          envFrom:
            - secretRef:
                name: $job_name
          command:
YAML
    for key in "${worker_command[@]}"; do printf '            - %s\n' "$(quote_yaml "$key")"; done
    if [ -n "$pull_secrets" ]; then
      printf '      imagePullSecrets:\n'
      while IFS= read -r pull_secret; do [ -z "$pull_secret" ] || printf '        - name: %s\n' "$(quote_yaml "$pull_secret")"; done <<< "$pull_secrets"
    fi
  } > "$credential_dir/job.yaml"
  log_stage worker "Starting isolated migration Job (apply=$apply); source snapshot, import and coverage validation run before commit."
  platform create -f "$(host_file "$credential_dir/job.yaml")" >/dev/null
  job_created=true
  # Secret content is already in Kubernetes; remove host credential files now.
  for key in "${connection_keys[@]}"; do rm -f "$credential_dir/$key"; done
  local deadline=$((SECONDS + timeout + 60))
  while [ "$SECONDS" -lt "$deadline" ]; do
    phase="$(platform get job "$job_name" -o 'jsonpath={.status.succeeded}:{.status.failed}')"
    case "$phase" in
      1:*) break ;;
      *:[1-9]*) platform logs "job/$job_name" -c migration >&2 || true; job_diagnostics; fail "Container account migration failed; original source was retained" ;;
    esac
    sleep 1
  done
  case "$phase" in 1:*) ;; *) job_diagnostics; fail "Migration Job timed out; inspect image access and database connectivity" ;; esac
  log_stage result "Migration Job succeeded; checking committed result."
  output="$(platform logs "job/$job_name" -c migration)"
  printf '%s\n' "$output"
  log_stage result "Worker result: $output"
  if worker_flag skipped "$output"; then log_stage skipped "Concurrent inspection found complete data; source cleanup was not attempted."; return; fi
  if [ "$apply" = true ]; then
    worker_flag committed "$output" || fail "Worker did not confirm a committed migration; original source was retained"
    log_stage committed "Account schema, business profiles and credential coverage committed."
  fi
  if [ "$apply" = true ] && [ -n "$source_name" ]; then
    for key in nexent-supabase-kong nexent-supabase-auth "$source_name"; do
      log_stage cleanup "Committed migration; removing source workload $key and retaining storage."
      platform delete deployment,service "$key" --ignore-not-found >/dev/null || cleanup_warning
    done
  elif [ "$apply" = true ]; then
    log_stage cleanup "Remote source has no managed workloads; manual source cleanup is required."
  else
    log_stage preview "Preview rolled back; source workloads were retained."
  fi
}
