# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise authenticated attachment ingress and the stable download surface."""

from contextlib import ExitStack
import hashlib
from urllib.parse import quote

import httpx


def require_status(response, status, operation):
    if response.status_code != status:
        raise AssertionError(f"{operation}: expected HTTP {status}, got {response.status_code}")


def sign_in(client, identity):
    response = client.post("/api/user/signin", json={key: identity[key] for key in ("email", "password")})
    require_status(response, 200, "Fixture sign-in through Gateway")
    data = response.json()["data"]
    if data["user"]["id"] != identity["user_id"] or not data["session"]["access_token"]:
        raise AssertionError("The Gateway sign-in did not return the expected fixture identity")
    return {"Authorization": f"Bearer {data['session']['access_token']}"}


def upload_attachment(runtime, authorization, user_id, filename, content):
    response = runtime.post("/api/file/storage", headers=authorization,
                            data={"folder": "attachments"}, files={"files": (filename, content, "text/plain")})
    require_status(response, 200, "Authenticated upload through the selected Runtime Pod")
    body = response.json()
    assert (body["success_count"], body["failed_count"]) == (1, 0)
    result, = body["results"]
    assert result["success"] is True
    object_name = result["object_name"]
    assert object_name.startswith(f"attachments/{user_id}/")
    assert result["original_file_name"] == filename
    return object_name


def verify_authenticated_attachments(url_a, url_b, stable_url, identities, token, peer_read):
    records = []
    with ExitStack() as stack:
        runtime_a, runtime_b, stable = [stack.enter_context(httpx.Client(base_url=url, timeout=30, trust_env=False))
                                        for url in (url_a, url_b, stable_url)]
        owner, foreign = identities["owner"], identities["foreign"]
        owner_auth, foreign_auth = sign_in(stable, owner), sign_in(stable, foreign)
        assert owner["tenant_id"] != foreign["tenant_id"] and owner["user_id"] != foreign["user_id"]
        require_status(runtime_a.post("/api/file/storage", files={"files": ("unauthenticated.txt", b"denied")}), 401,
                       "Anonymous Runtime upload")
        for role, writer in (("a", runtime_a), ("b", runtime_b)):
            content = f"authenticated-attachment:{token}:{role}\n".encode()
            object_name = upload_attachment(writer, owner_auth, owner["user_id"], f"attachment-{role}.txt", content)
            path = f"/api/file/download/{quote(object_name, safe='/')}"
            permitted = stable.get(path, headers=owner_auth, params={"download": "stream"})
            require_status(permitted, 200, "Authenticated attachment download through the stable Gateway")
            assert permitted.content == content
            require_status(stable.get(path, headers=foreign_auth, params={"download": "stream"}), 403,
                           "Foreign-tenant attachment download")
            require_status(stable.get(path, params={"download": "stream"}), 401, "Anonymous attachment download")
            digest = hashlib.sha256(content).hexdigest()
            assert peer_read(role, owner["user_id"], owner["tenant_id"], object_name) == {"status": "read", "sha256": digest}
            assert peer_read(role, foreign["user_id"], foreign["tenant_id"], object_name) == {"status": "denied"}
            records.append({"writer": role, "peer_digest": digest, "foreign_access_denied": True})
    return records
