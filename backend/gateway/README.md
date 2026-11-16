# Gateway boundaries

`application.py` constructs the Gateway FastAPI application, mounts the northbound and A2A routers, and manages the process-local thread manager, startup recovery and shutdown. These responsibilities belong to Gateway because this application serves the northbound process on port 5013.

`api/northbound.py` owns all northbound HTTP handlers, including knowledge-base and A2A handlers. Existing `/nb/v1`, `/nb/v1/knowledge` and `/nb/a2a` paths are preserved.

`authentication/auth.py` owns shared bearer syntax, session, internal-runtime and OAuth credential validation, and the normal authentication dependency. `authentication/northbound_auth.py` owns API-key and AK/SK validation, identity lookup and the northbound request context. Explicit credential policies prevent session, pending-OAuth and internal-runtime tokens from being substituted for one another.

The root `backend/northbound_service.py` is the executable Gateway launcher. `backend/config_service.py` launches Management on port 5010 using `management/api/application.py`. Docker Compose and Helm invoke these root filenames directly, so they remain stable launchers. Business routes live in the corresponding service's API modules.

`contracts/constants/environment.py` centralizes environment settings and derived configuration. `contracts/constants/constants.py` contains pure constants in comment groups. Each declaration occupies one physical line. Enum/value types belong to business contract files; `contracts/configuration.py` owns pure configuration helpers. OAuth provider definitions and lookup helpers live in `management/utils/oauth_providers.py`, and `management/services/model/catalog.py` builds the shared typed catalog lazily from the consolidated data.
