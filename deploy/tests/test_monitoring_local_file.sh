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
assert_eq "local_file otlp phoenix langfuse langsmith" "$deployment_monitoring_provider_list" "supported providers"
for provider in grafana zipkin both; do
  if (deployment_prepare_config --components application,monitoring --monitoring-provider "$provider") >"$TEST_DIR/rejected.log" 2>&1; then
    fail "removed provider accepted: $provider"
  fi
done

deployment_prepare_config --components application,monitoring --monitoring-provider local_file
deployment_prepare_monitoring_env docker
assert_eq "local_file" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" MONITORING_PROVIDER)" "provider"
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" TRAJECTORY_READ_ENABLED)" "local reads"
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" OTEL_EXPORTER_OTLP_METRICS_ENABLED)" "preserve metrics setting for a later remote deployment"
assert_eq "" "$(deployment_monitoring_collector_config_file docker local_file)" "no collector config"
deployment_prepare_config --components application --monitoring-provider local_file
deployment_prepare_monitoring_env docker
assert_eq "true" "$(deployment_get_env_var_file "$DEPLOYMENT_MONITORING_ENV" TRAJECTORY_READ_ENABLED)" "historical reads after capture stops"
deployment_prepare_config --components application,monitoring --monitoring-provider local_file
DEPLOYMENT_COMPONENTS=monitoring
assert_eq "" "$(deployment_compute_docker_ports)" "no monitoring ports"

# Load only function definitions; never execute a deployment or touch Docker.
eval "$(awk '/^docker_monitoring_active_services\(\)/,/^}/' "$SCRIPT_DIR/../docker/deploy.sh")"
eval "$(awk '/^deploy_monitoring\(\)/,/^}/' "$SCRIPT_DIR/../docker/deploy.sh")"
assert_eq "" "$(docker_monitoring_active_services)" "no remote services"
stop_monitoring_services() { printf stopped > "$TEST_DIR/stopped"; }
deploy_monitoring
[ -f "$TEST_DIR/stopped" ] || fail "local mode must stop prior remote services"
eval "$(awk '/^get_third_party_images\(\)/,/^}/' "$SCRIPT_DIR/../offline/build_offline_package.sh")"
assert_eq "" "$(get_third_party_images)" "local mode has no monitoring images"
DEPLOYMENT_MONITORING_PROVIDER=otlp
case "$(get_third_party_images)" in *opentelemetry-collector-contrib*) ;; *) fail "OTLP collector image missing" ;; esac

# Render actual Helm templates without contacting a cluster.
CHART="$SCRIPT_DIR/../k8s/helm/nexent"
for provider in local_file otlp phoenix langfuse langsmith; do
  helm template test "$CHART" --set nexent-common.secrets.jwtSecret=synthetic-test-only \
    --set global.monitoring.enabled=true --set global.monitoring.provider="$provider" \
    --set nexent-monitoring.enabled=true --set nexent-monitoring.phoenix.enabled=true \
    --set nexent-monitoring.langfuse.enabled=true > "$TEST_DIR/$provider.yaml"
done
for provider in grafana zipkin both; do
  if helm template test "$CHART" --set nexent-common.secrets.jwtSecret=synthetic-test-only \
    --set global.monitoring.provider="$provider" --set nexent-monitoring.enabled=true > "$TEST_DIR/rejected.log" 2>&1; then
    fail "Helm accepted removed provider: $provider"
  fi
done
helm template test "$CHART" --set nexent-common.secrets.jwtSecret=synthetic-test-only \
  --set global.monitoring.enabled=true --set global.monitoring.provider=local_file \
  --set global.monitoring.trajectoryRootDir=/custom/trajectory > "$TEST_DIR/custom.yaml"
"$PROJECT_ROOT/backend/.venv/bin/python" - "$TEST_DIR" "$PROJECT_ROOT" <<'PY'
import sys
from pathlib import Path
import yaml

root = Path(sys.argv[1])
for provider in ('local_file', 'otlp', 'phoenix', 'langfuse', 'langsmith', 'custom'):
    docs = [d for d in yaml.safe_load_all((root / f'{provider}.yaml').read_text()) if d]
    deployments = {d['metadata']['name']: d for d in docs if d.get('kind') == 'Deployment'}
    assert not {'nexent-grafana', 'nexent-tempo', 'nexent-zipkin'} & deployments.keys()
    local = provider in ('local_file', 'custom')
    assert ('nexent-otel-collector' in deployments) == (not local)
    assert ('nexent-phoenix' in deployments) == (provider == 'phoenix')
    assert ('nexent-langfuse-web' in deployments) == (provider == 'langfuse')
    config = next(d['data'] for d in docs if d.get('kind') == 'ConfigMap' and d['metadata']['name'] == 'nexent-config')
    expected = '/custom/trajectory' if provider == 'custom' else '/mnt/nexent-data/trajectory'
    assert config['TRAJECTORY_ROOT_DIR'] == expected
    if local:
        assert config['OTEL_EXPORTER_OTLP_METRICS_ENABLED'] == 'false'
        assert config['TRAJECTORY_READ_ENABLED'] == 'true'
    for name in ('nexent-runtime', 'nexent-config'):
        pod = deployments[name]['spec']['template']['spec']
        volume = next(v for v in pod['volumes'] if v['name'] == 'nexent-trajectory')
        assert volume['persistentVolumeClaim']['claimName'] == 'nexent-trajectory'
        mount = next(v for v in pod['containers'][0]['volumeMounts'] if v['name'] == 'nexent-trajectory')
        assert mount['mountPath'] == expected
for file in ('docker-compose.yml', 'docker-compose.prod.yml'):
    compose = yaml.safe_load((Path(sys.argv[2]) / 'deploy/docker/compose' / file).read_text())
    for name in ('nexent-runtime', 'nexent-config'):
        assert '${ROOT_DIR}/trajectory:${TRAJECTORY_ROOT_DIR:-/mnt/nexent-data/trajectory}' in compose['services'][name]['volumes']
PY
printf 'All local_file deployment option tests passed.\n'
