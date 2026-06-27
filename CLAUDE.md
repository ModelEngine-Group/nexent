# Claude Code Rules

## Code Quality Standards

### English-Only Comments and Documentation
- All comments and docstrings must be written in clear, concise English
- Do not use non-English characters in comments (string literals may contain any language)
- Use proper grammar and spelling; avoid ambiguous abbreviations
- Apply to: docstrings, inline comments, TODO/FIXME/NOTE, header comments, configuration comments

**Good:**
```python
# Initialize cache for 60 seconds
self.cache_ttl = 60
```

**Bad:**
```python
# 初始化缓存 60 秒 - FORBIDDEN
# データキャッシュ60秒 - FORBIDDEN
```

### Environment Variable Management
- All environment variable access must go through `backend/consts/const.py`
- No direct `os.getenv()` or `os.environ.get()` calls outside of `const.py`
- SDK modules (`sdk/`) should never read environment variables directly - accept configuration via parameters
- Services (`backend/services/`) read from `consts.const` and pass config to SDK
- Apps (`backend/apps/`) read from `consts.const` and pass through to services/SDK

**Good:**
```python
# backend/consts/const.py
APPID = os.getenv("APPID", "")
TOKEN = os.getenv("TOKEN", "")

# other modules
from consts.const import APPID, TOKEN
```

**Bad:**
```python
# direct calls in other modules
import os
appid = os.getenv("APPID")
token = os.environ.get("TOKEN")
```

## Backend Architecture Rules

### App Layer Rules (`backend/apps/**/*.py`)
**Purpose:** HTTP boundary for the backend - parse/validate input, call services, map domain errors to HTTP

**Responsibilities:**
- Parse and validate HTTP inputs using Pydantic models
- Call underlying services; do not implement core business logic
- Translate domain/service exceptions into `HTTPException` with proper status codes
- Return `JSONResponse(status_code=HTTPStatus.OK, content=payload)` on success

**Routing and URL Design:**
- Keep existing top-level prefixes for compatibility (e.g., `"/agent"`, `"/memory"`)
- Use plural nouns for collection-style resources (e.g., `"/agents"`, `"/memories"`)
- Use snake_case for all path segments
- Path parameters must be singular, semantic nouns: `"/agents/{agent_id}"`

**HTTP Methods:**
- GET: Read and list operations only
- POST: Create resources, perform searches, or trigger actions with side effects
- DELETE: Delete resources or clear collections (ensure idempotency)
- PUT/PATCH: Update resources

**Authorization:**
- Retrieve bearer token via header injection: `authorization: Optional[str] = Header(None)`
- Use utility helpers from `utils.auth_utils` (e.g., `get_current_user_id`)

**Exception Mapping:**
- `UnauthorizedError` → 401 UNAUTHORIZED
- `LimitExceededError` → 429 TOO_MANY_REQUESTS
- Parameter/validation errors → 400 BAD_REQUEST or 406 NOT_ACCEPTABLE
- Unexpected errors → 500 INTERNAL_SERVER_ERROR

**Correct Example:**
```python
from http import HTTPStatus
import logging
from fastapi import APIRouter, HTTPException
from starlette.responses import JSONResponse

from consts.exceptions import LimitExceededError, AgentRunException
from services.agent_service import run_agent

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/agent/run")
def run_agent_endpoint(payload: dict):
    try:
        result = run_agent(payload)
        return JSONResponse(status_code=HTTPStatus.OK, content=result)
    except LimitExceededError as exc:
        raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail=str(exc))
    except AgentRunException as exc:
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=str(exc))
```

### Service Layer Rules (`backend/services/**/*.py`)
**Purpose:** Implement core business logic orchestration; coordinate repositories/SDKs

**Requirements:**
- Implement core business logic and orchestrate complex workflows
- Raise domain/service exceptions from `backend/consts/exceptions.py`
- No HTTP concerns (no HTTPException, JSONResponse, etc.)
- No direct environment variable access (use `consts.const`)
- Return plain Python objects, not HTTP responses

**Available Exceptions:**
- `AgentRunException`: When agent run fails
- `LimitExceededError`: When outer platform calls too frequently  
- `UnauthorizedError`: When user from outer platform is unauthorized
- `SignatureValidationError`: When X-Signature header validation fails
- `MemoryPreparationException`: When memory preprocessing/retrieval fails

**Correct Example:**
```python
from typing import Any, Dict
from consts.exceptions import LimitExceededError, AgentRunException, MemoryPreparationException

def run_agent(task_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run agent core workflow and return domain result dict."""
    if _is_rate_limited(task_payload):
        raise LimitExceededError("Too many requests for this tenant.")

    try:
        memory = _prepare_memory(task_payload)
    except Exception as exc:
        raise MemoryPreparationException("Failed to prepare memory.") from exc

    try:
        result = _execute_core_logic(task_payload, memory)
    except Exception as exc:
        raise AgentRunException("Agent execution failed.") from exc

    return {"status": "ok", "data": result}
```

## Migration Checklist

### Environment Variables
1. Add new vars to `backend/consts/const.py`
2. Update `deploy/env/.env.example`
3. Remove all direct `os.getenv()`/`os.environ.get()` outside `const.py`
4. Import from `consts.const` in backend modules
5. Pass configuration as parameters to SDK
6. Remove `from_env()` methods from config classes

### Code Quality
1. Convert all non-English comments to English
2. Ensure docstrings use proper English grammar
3. Add module-level loggers: `logger = logging.getLogger(__name__)`
4. Follow existing async/sync conventions in each module

## File Structure

```
backend/
├── apps/           # HTTP API layer (FastAPI endpoints)
├── services/       # Business logic orchestration
├── consts/
│   ├── const.py   # Single source of truth for env vars
│   └── exceptions.py # Domain exceptions
└── utils/
    └── auth_utils.py # Authentication utilities

sdk/               # Pure configuration-based, no env vars
```

## Validation Rules

- No direct env access outside `const.py`
- No `from_env()` in config classes
- All env vars defined in `const.py`
- SDK modules accept configuration via parameters
- All comments in English
- Service layer raises domain exceptions only
- App layer maps domain exceptions to HTTP status codes
- Use structured logging with module-level loggers