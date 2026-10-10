# Frontend image replacement, 2026-10-10

At the user's request, the frontend image was rebuilt from branch `feat_hzw_260929` at `39f11154a`, including the preserved local working-tree frontend changes, and deployed to the existing local port 3000.

- Image tags: `nexent/nexent-web:branch-sync-20261010` and `nexent/nexent-web:latest`.
- Image ID: `sha256:56201d195c126451999cb6542417c0ad1da8dac2050144ff44f3460216419a47`.
- New container: `7241174bb344`, named `nexent-web`; running with zero restarts at verification.
- Previous image retained as `nexent/nexent-web:before-branch-sync-20261010` (`sha256:0ff9034d7d050ca57d4953e967ff940e576b1118b8a4216458d27db1601f82a9`).

The official `deploy/images/dockerfiles/web/Dockerfile` was used for a Linux amd64 production build with the deployment script's mainland npm and Alpine mirrors and the existing `/` base path. The Docker Engine version was checked before execution (29.7.2, API 1.55). The Next.js production build passed. Separate type checking had passed during the immediately preceding branch synchronization.

Only `nexent-web` was recreated with the existing Compose project, Compose file and two environment files, using `up -d --no-deps --force-recreate --pull never nexent-web`. The running container's complete environment, mounts, network membership and port bindings were compared with the pre-replacement snapshot and preserved. All 15 other running containers retained their original IDs. No backend or database deployment occurred.

Verification against the deployed production container at `http://localhost:3000`:

- `/zh/agents`, `/zh/workbench` and `/zh/newchat`: HTTP 200.
- `agent-debug.playwright.config.mjs`: PASS, including measured layout, send/stop, comparison, fullscreen and ordinary chat controls (6.4 seconds test duration).
- `agent-creation-guide.playwright.config.mjs`: PASS, including creation, four-step navigation, remembered finish/skip, permission checks and responsive boundaries (17.9 seconds test duration).

Both browser journeys used their existing Mock profiles, selected by `NEXENT_E2E_BASE_URL=http://localhost:3000`; this does not claim real model-provider acceptance. Local recovery and sanitized container verification records are under `.git/codex-backups/20261010-frontend-image-replacement/`. The original configuration snapshot is retained locally for recovery and must not be published because it contains environment configuration.
