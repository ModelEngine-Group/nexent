"""Controlled-assets tests: Range semantics, status codes, runtime registration.

These exercise the /assets route set directly over HTTP (no product adapter
involved) — the contract here is the HTTP semantics the product's resource
paths depend on (file preview proxying, image fetching, download proxies).
"""
from urllib.parse import quote

LARGE_SIZE = 32768


def test_full_download_without_range_header(http_client):
    response = http_client.get("/assets/large.txt")
    assert response.status_code == 200
    assert len(response.content) == LARGE_SIZE
    assert response.headers["accept-ranges"] == "bytes"


def test_range_request_returns_206(http_client):
    response = http_client.get("/assets/large.txt", headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-99/{LARGE_SIZE}"
    assert len(response.content) == 100


def test_open_ended_and_suffix_ranges(http_client):
    open_ended = http_client.get("/assets/large.txt", headers={"Range": "bytes=32760-"})
    assert open_ended.status_code == 206
    assert open_ended.headers["content-range"] == f"bytes 32760-32767/{LARGE_SIZE}"
    assert len(open_ended.content) == 8

    suffix = http_client.get("/assets/large.txt", headers={"Range": "bytes=-4"})
    assert suffix.status_code == 206
    assert suffix.headers["content-range"] == f"bytes 32764-32767/{LARGE_SIZE}"
    assert len(suffix.content) == 4


def test_unsatisfiable_range_returns_416(http_client):
    response = http_client.get("/assets/large.txt", headers={"Range": "bytes=99999-100000"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{LARGE_SIZE}"


def test_asset_without_range_support_returns_full_body(http_client):
    response = http_client.get("/assets/no-range.bin", headers={"Range": "bytes=0-9"})
    assert response.status_code == 200
    assert len(response.content) == 1024
    assert "accept-ranges" not in response.headers


def test_content_disposition_and_content_types(http_client):
    response = http_client.get("/assets/document.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert quote("样例文档.pdf") in disposition  # RFC 5987 encoded


def test_image_asset_serves_real_png_bytes(http_client):
    response = http_client.get("/assets/image.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_configured_status_and_redirect(http_client):
    assert http_client.get("/assets/unauthorized.png").status_code == 401

    moved = http_client.get("/assets/moved.bin", follow_redirects=False)
    assert moved.status_code == 302
    assert moved.headers["location"] == "/assets/image.png"


def test_runtime_asset_registration_and_reset(http_client):
    declared = http_client.post(
        "/_mock/assets",
        json={"assets": [{"name": "runtime.bin", "content_type": "application/octet-stream", "size": 128}]},
    )
    assert declared.status_code == 200
    assert declared.json()["registered"] == ["runtime.bin"]

    served = http_client.get("/assets/runtime.bin")
    assert served.status_code == 200
    assert len(served.content) == 128

    # A scoped reset drops runtime declarations and restores the seed set.
    http_client.post("/_reset", json={"services": ["assets"]})
    assert http_client.get("/assets/runtime.bin").status_code == 404
    assert http_client.get("/assets/image.png").status_code == 200


def test_unknown_asset_404(http_client):
    assert http_client.get("/assets/missing.bin").status_code == 404
