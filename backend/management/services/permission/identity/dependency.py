# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""The single identity dependency for internal and northbound routes.

One declaration replaces the four historical authentication spellings
(manual ``await``, ``Header`` pass-through, self-wrapping helpers and
``Depends``):

    async def delete_conversation(
        conversation_id: int,
        ctx: AuthenticatedIdentity = Depends(unified_identity),
    ) -> dict:
        ...

The credential kind follows the same rule the gateway uses: a ``/nb`` path is
an API-Key caller, everything else is a browser session. That single rule makes
a route clone-able: the identical declaration resolves the partner credential
on the northbound clone and the session on the internal route.

Accounting comes for free: an API-Key request is recorded here, so business
code never participates in usage accounting.
"""

import logging
from typing import Optional

from fastapi import Header, Request

from contracts.authentication import AuthenticatedIdentity, CredentialKind
from contracts.constants.constants import NORTHBOUND_PATH_PREFIX
from contracts.errors.exceptions import UnauthorizedError
from management.utils.request_context import get_request_id

logger = logging.getLogger(__name__)


def is_northbound_path(path: str) -> bool:
    """Whether a request path belongs to the public northbound namespace."""
    normalized = path or ""
    return normalized == NORTHBOUND_PATH_PREFIX or normalized.startswith(f"{NORTHBOUND_PATH_PREFIX}/")


def _request_path(request: Request) -> str:
    scope_path = request.scope.get("path") if request is not None else ""
    return scope_path or (request.url.path if request is not None else "")


def credential_kind_for_path(path: str) -> CredentialKind:
    """Select the credential policy from the path, never from unverified claims."""
    return CredentialKind.API_KEY if is_northbound_path(path) else CredentialKind.SESSION


async def unified_identity(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> AuthenticatedIdentity:
    """Resolve the request principal through the single supported identity path.

    The Gateway already verified the credential and bound the identity to the
    request; ``authenticate_identity`` consumes that identity first and only
    falls back to legacy self-verification when the gateway did not run.

    Imports stay inside the function so importing the exposure mechanism does
    not pull the credential, database and token stacks at module load.
    """
    from management.services.permission.identity.northbound import record_api_key_usage
    from management.services.permission.identity.session import authenticate_identity

    path = _request_path(request)
    kind = credential_kind_for_path(path)
    principal = authenticate_identity(authorization, kind=kind, request=request)
    if not principal.user_id or not principal.tenant_id:
        raise UnauthorizedError("Authenticated principal is incomplete")

    request.state.authenticated_identity = principal
    request.state.request_id = get_request_id(request)
    if principal.kind == CredentialKind.API_KEY:
        record_api_key_usage(principal, request)
    return principal
