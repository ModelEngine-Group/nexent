# Independent Gateway, batches 1–2

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

Business authentication is still enforced downstream. Gateway preserves external Authorization/Cookie credentials and strips untrusted internal identity and forwarding headers. It does not yet issue internal user identities, query API-key state or enforce distributed rate limits. Keep downstream services on a trusted network; this batch is not the completed security boundary.

HTTP and SSE are streamed without retries or redirects. Internal API paths are denied. WebSockets relay text/binary frames and subprotocols, with a 16 MiB per-message upstream limit. Original HTTP Host is preserved for callback and A2A URL compatibility.

The compatibility Northbound launcher on 5013 now starts the proxy. Management serves the original Northbound and A2A routes, owns recovery, and cleans both Management and historical Northbound upload records. Deploy Management and the proxy from the same revision, or roll both back together. Frontend target and independent-image switching remain later batches. Never point the Northbound upstream at this Gateway itself.

Drain and stop the old Northbound business process before starting new Management recovery, then start the proxy. Do not overlap the two business owners: recovery deliberately marks previous-owner tasks as interrupted. Management retains its single-replica/Recreate requirement. Rollback must also stop the new owner before restoring both old revisions.
