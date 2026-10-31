# Independent Gateway deployment

The default Compose and Helm service `nexent-northbound:5013` now runs `nexent/nexent-gateway`. Gateway handles external session/API-key authentication, authoritative identity lookup, signed downstream identity, fixed HTTP/SSE routing and WebSocket relay. Management owns Northbound/A2A business, recovery and resource authorization. Runtime owns execution. Management and Runtime still use the shared `nexent/nexent` backend image.

The standalone image listens on 5016. Default deployments override its command and healthcheck/probes to 5013. It runs as UID 65532 and contains no Management/Runtime source, Nexent SDK or ORM. It needs no SQL files, storage mounts or Docker socket. Health endpoints report local process readiness; upstream availability needs separate acceptance checks.

## 1. Build matching revisions

Run from the repository root using Bash on Linux, WSL or Git Bash. Docker Engine 18.09/API 1.39 remains the deployment baseline. Building uses a current Docker Buildx CLI; build on a supported host and transfer images when deploying to older engines.

```sh
release_tag="$(cat VERSION)-gateway.$(git rev-parse --short HEAD)"
bash deploy/images/build.sh --images gateway --version "$release_tag" --load
bash deploy/images/build.sh --images main,web,mcp,data-process --version "$release_tag" --load
```

Rebuild the backend from this revision because it contains the Management migration and downstream signature checks. Keep the same release tag across artifacts and record their digests before deployment. Use `--dry-run` to inspect selection. For a Python index mirror use `--registry mainland` or build Gateway directly.

```sh
docker build -f deploy/images/dockerfiles/gateway/Dockerfile \
  --build-arg MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple \
  -t "nexent/nexent-gateway:$release_tag" .
```

For remote deployment, authenticate to the approved registry and publish matching artifacts. `--push --platform linux/amd64,linux/arm64` replaces `--load` for multi-platform publication. Existing overseas/mainland release workflows include Gateway. This change does not dispatch workflows or push images. Dev-only backend workflows do not publish Gateway; build it explicitly for dev branches.

Offline selection includes Gateway.

```sh
bash deploy/offline/build_offline_package.sh --defaults --target docker \
  --version "$release_tag" --components infrastructure,application,data-process \
  --include-sandbox false --dry-run
```

Actual packaging pulls selected images. Publish or mirror them before removing `--dry-run`; then follow the package's existing image-load instructions on the offline host.

## 2. Prepare configuration and rollback inputs

For a new installation, complete `deploy/env/.env` from `.env.example`, including data paths and infrastructure credentials. Keep it outside Git. For upgrades, preserve the environment, volumes, database backup, previous Compose/Helm configuration, image digests and Helm revision. Retain the existing JWT key to preserve active sessions.

- Set the same nonempty `JWT_SECRET` on Gateway, Management and Runtime. Set `JWT_ISSUER` consistently, defaulting to `nexent`.
- Optionally set the same `GATEWAY_SIGNING_SECRET` on all three services. Otherwise they derive a domain-separated key from `JWT_SECRET`. Rotate keys together.
- Keep `GATEWAY_AUTH_ENABLED=true`. Set `DEPLOYMENT_VERSION=full` for authenticated deployment. `speed` intentionally uses the existing speed identity behavior.
- Gateway targets `http://nexent-config:5010` and `http://nexent-runtime:5014`. Northbound also targets Management. Never point an upstream at Gateway itself.
- Web HTTP, Runtime HTTP and WS targets use `nexent-northbound:5013`. Data Process business API uses `http://nexent-northbound:5013/api`. Management-to-Runtime execution retains its private scoped service credential.

Restrict Management/Runtime and infrastructure ports to the trusted service network. Development Compose publishes diagnostic ports; configure host/network ingress before public deployment. TLS termination must support streaming and WebSocket upgrade, preserve external Host for callbacks, and disable SSE response buffering. Keep service clocks synchronized for short-lived signatures.

## 3. Compose cutover

Use the existing deployment initializer for a fresh host to create directories, infrastructure credentials, skills and other required assets. These commands show application cutover after those prerequisites are ready.

```sh
cat > deploy/env/gateway-release.env <<EOF
NEXENT_GATEWAY_IMAGE=nexent/nexent-gateway:$release_tag
NEXENT_IMAGE=nexent/nexent:$release_tag
NEXENT_WEB_IMAGE=nexent/nexent-web:$release_tag
NEXENT_MCP_DOCKER_IMAGE=nexent/nexent-mcp:$release_tag
NEXENT_DATA_PROCESS_IMAGE=nexent/nexent-data-process:$release_tag
EOF

compose=(docker compose --env-file deploy/env/.env \
  --env-file deploy/env/gateway-release.env -p nexent \
  -f deploy/docker/compose/docker-compose.prod.yml)
"${compose[@]}" config --quiet
# Pull when deploying registry images, skip for locally built images.
# "${compose[@]}" pull
```

Drain external traffic and finish or explicitly interrupt active runs. Stop the old Northbound business owner before new Management recovery starts. Recreate backend services from the same revision in a maintenance window.

```sh
"${compose[@]}" stop nexent-web nexent-data-process nexent-northbound nexent-config nexent-runtime nexent-mcp
"${compose[@]}" up -d nexent-postgresql redis nexent-elasticsearch nexent-minio
# Confirm infrastructure readiness before starting Management.
"${compose[@]}" up -d --no-deps nexent-config
# Wait for startup migrations/recovery and Management /health/ready on 5010.
"${compose[@]}" up -d --no-deps nexent-runtime nexent-mcp
# Wait for Runtime /health/ready on 5014 and MCP startup.
"${compose[@]}" up -d --no-deps nexent-northbound
"${compose[@]}" ps
```

Management retains single-replica/Recreate ownership. Recovery marks previous-owner tasks interrupted and cleans current and historical Northbound upload records. Do not overlap old Northbound and new Management owners. Gateway `depends_on` controls startup order; health and business checks establish readiness.

After Gateway health and authenticated checks pass, start consumers and resume traffic.

```sh
"${compose[@]}" up -d --no-deps nexent-web nexent-data-process
```

The optional `docker-compose.gateway.yml` overlay adds a second Gateway on 5016 for diagnostics. Default deployment already uses the independent image. Configure the same issuer, keys and deployment mode if using the overlay.

## 4. Helm cutover

Use `deploy/k8s/deploy.sh` to generate infrastructure, storage, environment and image overrides for the target cluster. Image-source resolution now maps Gateway separately, including local-latest and registry-prefix modes. For manual values set `nexent-northbound.images.backend.repository=nexent/nexent-gateway` and a matching release tag. The `images.backend` key remains compatible with existing values files.

Set backend image tags under `nexent-config`, `nexent-runtime` and `nexent-mcp`. Configure `nexent-common.secrets.jwtSecret`, optional `gatewaySigningSecret` and `nexent-common.config.auth.jwtIssuer` consistently. Supply actual keys through a protected values file or the deployment secret workflow, avoiding command-line secrets and source control.

```sh
# deployment-values.yaml is the generated, environment-specific protected file.
helm dependency build deploy/k8s/helm/nexent
helm template nexent deploy/k8s/helm/nexent -f deployment-values.yaml > rendered.yaml
# Review privately; rendered.yaml contains Kubernetes Secrets.
```

Drain ingress and scale old `nexent-northbound` business Deployment to zero before applying the new release. Preserve the old replica settings and release revision. Apply the coordinated release after that owner stops.

```sh
helm upgrade --install nexent deploy/k8s/helm/nexent \
  --namespace nexent --create-namespace -f deployment-values.yaml --wait --timeout 10m
kubectl -n nexent rollout status deployment/nexent-config
kubectl -n nexent rollout status deployment/nexent-runtime
kubectl -n nexent rollout status deployment/nexent-northbound
```

Gateway supports multiple replicas and RollingUpdate without shared volumes. Management's recovery constraints remain. Verify storage classes/PVCs, infrastructure and migration backups with the installation procedure. Helm readiness does not prove login or Agent execution. For a failed first migration, use coordinated rollback to avoid overlapping business owners through automatic rollback.

## 5. Acceptance and rollback

Check Gateway `/health/live` and `/health/ready`, then verify the deployed path.

1. Missing/invalid credentials return 401 on protected routes. Public login and callbacks remain available. `/api/internal/identity/resolve` returns 404 through Gateway.
2. Login in the browser, read current user/tenant, and call a protected Management API. Revoke a test key or session version and verify the next request/handshake is rejected. Direct unsigned business calls to Management/Runtime return 401.
3. Run an Agent through UI and API-key Northbound paths. Verify incremental SSE and binary/text voice WS. Verify disconnected clients and upstreams release transports. Check Runtime receives execution while Management owns Northbound state and recovery.
4. Restart Management in a controlled environment to inspect interrupted tasks and historical upload cleanup. Check signature/audience/issuer/clock errors without printing credentials. Exercise actual database/model/provider and browser flows before production acceptance.

Image and loopback proof do not certify a production environment. Full browser/deployed-provider and load acceptance remain pending until executed on the target deployment.

For rollback, drain traffic and stop Gateway, new Management and Runtime plus affected consumers before restoring saved images/configuration as one release. Stop the new recovery owner before restarting an old Northbound business process. With Helm stop affected Deployments first, then restore the reviewed previous release/configuration and replica counts. Keep keys consistent. Preserve volumes; do not run `down -v`. Assess migration reversibility and use the verified backup procedure if required. Re-run login, protected HTTP, Northbound, SSE and WS checks before reopening ingress.
