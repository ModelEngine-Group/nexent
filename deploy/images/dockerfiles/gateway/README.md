# Independent Gateway, batch 1

Build from the repository root:

```sh
docker build -f deploy/images/dockerfiles/gateway/Dockerfile -t nexent/nexent-gateway:dev .
```

The image contains only the edge proxy and shared configuration. It does not contain Management, Runtime or the Nexent SDK. It runs as UID 65532 and listens on 5016. `/health/live` and `/health/ready` report local process readiness, not upstream availability.

Opt in alongside the existing deployment:

```sh
docker compose --env-file deploy/env/.env -f deploy/docker/compose/docker-compose.yml -f deploy/docker/compose/docker-compose.gateway.yml up -d --build nexent-gateway
```

The optional overlay adds a service; it does not switch the frontend or replace the old Northbound service. Configure `GATEWAY_MANAGEMENT_URL`, `GATEWAY_RUNTIME_URL` and `GATEWAY_NORTHBOUND_URL` with internal HTTP origins. The third upstream is transitional until Northbound business moves into Management.

Business authentication is still enforced downstream. Gateway preserves external Authorization/Cookie credentials and strips untrusted internal identity and forwarding headers. It does not yet issue internal user identities, query API-key state or enforce distributed rate limits. Keep downstream services on a trusted network; this batch is not the completed security boundary.

HTTP and SSE are streamed without retries or redirects. Internal API paths are denied. WebSockets relay text/binary frames and subprotocols, with a 16 MiB per-message upstream limit. Original HTTP Host is preserved for callback and A2A URL compatibility.

Existing default deployment and launchers remain unchanged. Stop the optional Gateway service to roll back this batch. Do not point the transitional Northbound upstream at this Gateway itself.
