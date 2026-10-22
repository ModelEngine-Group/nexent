# Gateway boundaries

`application.py` constructs the Gateway FastAPI application, mounts the northbound and A2A routers, and manages the process-local thread manager, startup recovery and shutdown. These responsibilities belong to Gateway because this application serves the northbound process on port 5013.

`api/northbound.py` owns all northbound HTTP handlers, including knowledge-base and A2A handlers. Existing `/nb/v1`, `/nb/v1/knowledge` and `/nb/a2a` paths are preserved.

`authentication/normal.py` owns shared bearer syntax, session, internal-runtime and OAuth credential validation, and the normal authentication dependency. `authentication/northbound.py` owns API-key and AK/SK validation, identity lookup and the northbound request context. Explicit credential policies prevent session, pending-OAuth and internal-runtime tokens from being substituted for one another.

The root `backend/northbound_service.py` is the executable Gateway launcher. `backend/config_service.py` launches Management on port 5010 using `management/api/application.py`. Docker Compose and Helm invoke these root filenames directly, so they remain stable launchers. Business routes live in the corresponding service's API modules.

`consts/const.py` remains the centralized reader for environment configuration and application version resolution. OAuth provider definitions and lookup helpers live in `management/utils/oauth_providers.py`; pure business constants live under `contracts/constants`.
