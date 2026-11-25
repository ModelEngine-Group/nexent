#!/usr/bin/env bash
# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$SCRIPT_DIR/../common/common.sh"
TEST_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nexent-local-monitoring.XXXXXX")"
trap 'rm -rf "$TEST_DIR"' EXIT
export DEPLOYMENT_LANG=en
DEPLOYMENT_ROOT_ENV="$TEST_DIR/root.env"
DEPLOYMENT_MONITORING_ENV="$TEST_DIR/monitoring.env"
: > "$DEPLOYMENT_ROOT_ENV"
cp "$SCRIPT_DIR/../env/monitoring.env.example" "$TEST_DIR/monitoring.env.example"

fail() { echo "FAIL: $*"; exit 1; }
assert_eq() { [ "$1" = "$2" ] || fail "$3: expected '$1', got '$2'"; }
assert_eq "otlp phoenix langfuse langsmith" "$deployment_monitoring_provider_list" "supported remote providers"
for provider in local_file grafana zipkin both; do
  if (deployment_prepare_config --components application,monitoring --monitoring-provider "$provider") >"$TEST_DIR/rejected.log" 2>&1; then
    fail "removed provider accepted: $provider"
  fi
done

deployment_prepare_config --components application
deployment_prepare_monitoring_env docker
assert_eq "otlp" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" MONITORING_PROVIDER)" "default remote provider"
assert_eq "false" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" ENABLE_TELEMETRY)" "remote export is off without the monitoring component"
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" LOCAL_FILE_MONITORING_ENABLED)" "local capture without monitoring component"
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" TRAJECTORY_READ_ENABLED)" "local reads"
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" OTEL_EXPORTER_OTLP_METRICS_ENABLED)" "preserve metrics setting for a later remote deployment"
export LOCAL_FILE_MONITORING_ENABLED=false
deployment_prepare_monitoring_env k8s
assert_eq "false" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" ENABLE_TELEMETRY)" "local capture disabled by environment"
assert_eq "false" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" LOCAL_FILE_MONITORING_ENABLED)" "local disabled reaches the backend env"
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" TRAJECTORY_READ_ENABLED)" "historical reads after capture stops"
assert_eq "false" "$(deployment_render_helm_monitoring_global_values | awk '$1 == "enabled:" { print $2 }')" "Helm respects disabled local capture"
deployment_prepare_config --components application,monitoring --monitoring-provider phoenix
deployment_prepare_monitoring_env docker
assert_eq "phoenix" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" MONITORING_PROVIDER)" "explicit third-party provider"
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" ENABLE_TELEMETRY)" "local switch does not disable remote capture"
assert_eq "false" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" LOCAL_FILE_MONITORING_ENABLED)" "third-party capture only"
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" TRAJECTORY_READ_ENABLED)" "remote provider preserves access to past local traces"
unset LOCAL_FILE_MONITORING_ENABLED
deployment_prepare_monitoring_env k8s
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" LOCAL_FILE_MONITORING_ENABLED)" "local capture defaults on with a third-party provider"
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" ENABLE_TELEMETRY)" "third-party export stays on with local capture"
assert_eq "true" "$(deployment_render_helm_monitoring_global_values | awk '$1 == "localFileEnabled:" { print $2 }')" "Helm retains the local switch in dual mode"
deployment_prepare_config --components application --monitoring-provider phoenix
deployment_prepare_monitoring_env docker
assert_eq "otlp" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" MONITORING_PROVIDER)" "ignore remote choice when the monitoring component is off"
assert_eq "false" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" ENABLE_TELEMETRY)" "remote provider selection alone does not enable export"
deployment_prepare_config --components application,monitoring
deployment_prepare_monitoring_env docker
assert_eq "otlp" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" MONITORING_PROVIDER)" "monitoring component keeps the default OTLP provider"

cat > "$TEST_DIR/legacy.yaml" <<'YAML'
schemaVersion: "1"
components:
  - infrastructure
  - monitoring
  - application
monitoringProvider: "local_file"
YAML
deployment_prepare_config --use-local-config --local-config "$TEST_DIR/legacy.yaml"
assert_eq "infrastructure,application" "$DEPLOYMENT_COMPONENTS" "legacy local profile does not enable remote export"
deployment_prepare_monitoring_env docker
assert_eq "false" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" ENABLE_TELEMETRY)" "legacy profile sends no remote traces"
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" LOCAL_FILE_MONITORING_ENABLED)" "legacy profile uses the local environment default"
deployment_prepare_config --use-local-config --local-config "$TEST_DIR/legacy.yaml" \
  --components application,monitoring --monitoring-provider phoenix
assert_eq "true" "$(deployment_monitoring_enabled)" "explicit remote component overrides a legacy profile"
assert_eq "phoenix" "$DEPLOYMENT_MONITORING_PROVIDER" "explicit remote provider overrides a legacy profile"

# Load only function definitions; never execute a deployment or touch Docker.
eval "$(awk '/^docker_monitoring_active_services\(\)/,/^}/' "$SCRIPT_DIR/../docker/deploy.sh")"
eval "$(awk '/^deploy_monitoring\(\)/,/^}/' "$SCRIPT_DIR/../docker/deploy.sh")"
assert_eq $'otel-collector\nphoenix' "$(docker_monitoring_active_services)" "selected remote services"
DEPLOYMENT_COMPONENTS=""
assert_eq "" "$(deployment_compute_docker_ports)" "no monitoring ports"
stop_monitoring_services() { printf stopped > "$TEST_DIR/stopped"; }
deploy_monitoring
[ -f "$TEST_DIR/stopped" ] || fail "omitting monitoring must stop prior remote services"
eval "$(awk '/^get_third_party_images\(\)/,/^}/' "$SCRIPT_DIR/../offline/build_offline_package.sh")"
assert_eq "" "$(get_third_party_images)" "no monitoring images without the component"
DEPLOYMENT_COMPONENTS=monitoring
DEPLOYMENT_MONITORING_PROVIDER=otlp
case "$(get_third_party_images)" in *opentelemetry-collector-contrib*) ;; *) fail "OTLP collector image missing" ;; esac

# Render actual Helm templates without contacting a cluster.
CHART="$SCRIPT_DIR/../k8s/helm/nexent"
helm template test "$CHART" --set nexent-common.secrets.jwtSecret=synthetic-test-only > "$TEST_DIR/default.yaml"
helm template test "$CHART" --set nexent-common.secrets.jwtSecret=synthetic-test-only \
  --set global.monitoring.localFileEnabled=false --set global.monitoring.enabled=false > "$TEST_DIR/disabled.yaml"
helm template test "$CHART" --set nexent-common.secrets.jwtSecret=synthetic-test-only \
  --set global.monitoring.localFileEnabled=false --set global.monitoring.provider=otlp \
  --set global.monitoring.enabled=true --set nexent-monitoring.enabled=true > "$TEST_DIR/remote_only.yaml"
for provider in otlp phoenix langfuse langsmith; do
  helm template test "$CHART" --set nexent-common.secrets.jwtSecret=synthetic-test-only \
    --set global.monitoring.enabled=true --set global.monitoring.provider="$provider" \
    --set nexent-monitoring.enabled=true --set nexent-monitoring.phoenix.enabled=true \
    --set nexent-monitoring.langfuse.enabled=true > "$TEST_DIR/$provider.yaml"
done
for provider in local_file grafana zipkin both; do
  if helm template test "$CHART" --set nexent-common.secrets.jwtSecret=synthetic-test-only \
    --set global.monitoring.provider="$provider" --set nexent-monitoring.enabled=true > "$TEST_DIR/rejected.log" 2>&1; then
    fail "Helm accepted removed provider: $provider"
  fi
done
if helm template test "$CHART" --set nexent-common.secrets.jwtSecret=synthetic-test-only \
  --set global.monitoring.provider=local_file > "$TEST_DIR/rejected.log" 2>&1; then
  fail "Helm accepted the removed provider without the monitoring chart"
fi
helm template test "$CHART" --set nexent-common.secrets.jwtSecret=synthetic-test-only \
  --set global.monitoring.trajectoryRootDir=/custom/trajectory > "$TEST_DIR/custom.yaml"
"$PROJECT_ROOT/backend/.venv/bin/python" - "$TEST_DIR" "$PROJECT_ROOT" <<'PY'
import sys
from pathlib import Path
import yaml

root = Path(sys.argv[1])
for provider in ('default', 'disabled', 'otlp', 'phoenix', 'langfuse', 'langsmith', 'custom', 'remote_only'):
    docs = [d for d in yaml.safe_load_all((root / f'{provider}.yaml').read_text()) if d]
    deployments = {d['metadata']['name']: d for d in docs if d.get('kind') == 'Deployment'}
    assert not {'nexent-grafana', 'nexent-tempo', 'nexent-zipkin'} & deployments.keys()
    remote_enabled = provider not in ('default', 'disabled', 'custom')
    local_enabled = provider not in ('disabled', 'remote_only')
    selected_provider = provider if provider in ('phoenix', 'langfuse', 'langsmith') else 'otlp'
    assert ('nexent-otel-collector' in deployments) == remote_enabled
    assert ('nexent-phoenix' in deployments) == (provider == 'phoenix')
    assert ('nexent-langfuse-web' in deployments) == (provider == 'langfuse')
    config = next(d['data'] for d in docs if d.get('kind') == 'ConfigMap' and d['metadata']['name'] == 'nexent-config')
    expected = '/custom/trajectory' if provider == 'custom' else '/mnt/nexent-data/trajectory'
    assert config['TRAJECTORY_ROOT_DIR'] == expected
    assert config['ENABLE_TELEMETRY'] == str(remote_enabled).lower()
    assert config['MONITORING_PROVIDER'] == selected_provider
    assert config['LOCAL_FILE_MONITORING_ENABLED'] == str(local_enabled).lower()
    assert config['TRAJECTORY_READ_ENABLED'] == str(local_enabled).lower()
    volume_names = {'nexent-runtime': 'nexent-trajectory', 'nexent-config': 'nexent-trajectory'}
    if local_enabled:
        volume_names['nexent-ops'] = 'ops-trajectory'
    else:
        ops = deployments['nexent-ops']['spec']['template']['spec']
        assert 'ops-trajectory' not in {v['name'] for v in ops['volumes']}
        env = {entry['name']: entry for entry in ops['containers'][0]['env']}
        for key in ('MONITORING_PROVIDER', 'LOCAL_FILE_MONITORING_ENABLED', 'TRAJECTORY_READ_ENABLED'):
            assert env[key]['valueFrom']['configMapKeyRef'] == {'name': 'nexent-config', 'key': key}
    for name, volume_name in volume_names.items():
        pod = deployments[name]['spec']['template']['spec']
        volume = next(v for v in pod['volumes'] if v['name'] == volume_name)
        assert volume['persistentVolumeClaim']['claimName'] == 'nexent-trajectory'
        mount = next(v for v in pod['containers'][0]['volumeMounts'] if v['name'] == volume_name)
        assert mount['mountPath'] == expected
for file in ('docker-compose.yml', 'docker-compose.prod.yml'):
    compose = yaml.safe_load((Path(sys.argv[2]) / 'deploy/docker/compose' / file).read_text())
    for name in ('nexent-runtime', 'nexent-config'):
        assert '${ROOT_DIR}/trajectory:${TRAJECTORY_ROOT_DIR:-/mnt/nexent-data/trajectory}' in compose['services'][name]['volumes']
ops = yaml.safe_load((Path(sys.argv[2]) / 'deploy/docker/compose/docker-compose-ops.yml').read_text())
assert '${ROOT_DIR}/trajectory:${TRAJECTORY_ROOT_DIR:-/mnt/nexent-data/trajectory}' in ops['services']['nexent-ops']['volumes']
PY
printf 'All monitoring deployment option tests passed.\n'
