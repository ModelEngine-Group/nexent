# Independent Gateway, batches 1–3

Build from the repository root:

```sh
docker build -f deploy/images/dockerfiles/gateway/Dockerfile -t nexent/nexent-gateway:dev .
```

The image contains only the edge proxy and shared configuration. It does not contain Management, Runtime or the Nexent SDK. It runs as UID 65532 and listens on 5016. `/health/live` and `/health/ready` report local process readiness, not upstream availability.

Opt in alongside the existing deployment:

```sh
docker compose --env-file deploy/env/.env -f deploy/docker/compose/docker-compose.yml -f deploy/docker/compose/docker-compose.gateway.yml up -d --build nexent-gateway
```

The optional overlay adds a service; it does not switch the frontend or replace the old Northbound service. Configure `GATEWAY_MANAGEMENT_URL`, `GATEWAY_RUNTIME_URL` and `GATEWAY_NORTHBOUND_URL` with internal HTTP origins. Northbound now targets Management as well; set its URL explicitly only when a separate internal Management address is required.

Gateway verifies session JWTs and queries Management's private identity interface for active account, token version, CAS session, tenant/role and API-key revocation state. It signs a 30-second audience/method/path/query-bound identity envelope. Management and Runtime enforce that boundary and retain business resource authorization. The private lookup also verifies a body-bound service signature. No identity cache is used; revocation is checked on each new HTTP request or WS handshake.

External Authorization/Cookie credentials are retained for existing logout, CAS and provider delegation flows. Existing business identity helpers consume the verified request context first. Public login/refresh/logout, OAuth/CAS callbacks, Agent Card and shared-conversation reads use explicit method/path policies; signed anonymous envelopes cannot access protected routes. AK/SK remains unconfigured as before. Distributed rate limiting is outside batch 3.

The independent image and shipped Compose/Helm enable GATEWAY_AUTH_ENABLED=true. The source flag defaults false for old local/test invocations only. Set JWT_SECRET consistently on all three services. Optionally set the same GATEWAY_SIGNING_SECRET on each; otherwise a domain-separated key is derived from JWT_SECRET. Missing signing configuration prevents an enabled Gateway/service from starting. Never commit deployment secrets. The optional Compose overlay requires JWT_SECRET from the deployment environment. For local source execution with authentication enabled, point the frontend HTTP, Runtime HTTP and WS backend variables to Gateway as the shipped deployment does.

Shipped Web and data-processing business API targets now pass through the compatibility Gateway on 5013. Runtime's private execution endpoints still use separately verified Management service JWTs. Coordinate the three service revisions, shared keys and client targets; roll them back together. The optional 5016 image does not automatically replace the default image selection.

HTTP and SSE are streamed without retries or redirects. Internal API paths are denied. WebSockets relay text/binary frames and subprotocols, with a 16 MiB per-message upstream limit. Original HTTP Host is preserved for callback and A2A URL compatibility.

The compatibility Northbound launcher on 5013 now starts the proxy. Management serves the original Northbound and A2A routes, owns recovery, and cleans both Management and historical Northbound upload records. Deploy Management and the proxy from the same revision, or roll both back together. Default independent-image selection and build publication remain later work. Never point the Northbound upstream at this Gateway itself.

Drain and stop the old Northbound business process before starting new Management recovery, then start the proxy. Do not overlap the two business owners: recovery deliberately marks previous-owner tasks as interrupted. Management retains its single-replica/Recreate requirement. Rollback must also stop the new owner before restoring both old revisions.

Use `--build-arg MIRROR=<trusted-package-index>` when the default Python index is unavailable. Batch 3 verification used the configured public mirror after the default index failed.
