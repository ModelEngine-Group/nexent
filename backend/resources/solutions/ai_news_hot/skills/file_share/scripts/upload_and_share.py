#!/usr/bin/env python3
"""Upload a local file to MinIO and return a browser-accessible download URL.

Usage:
    python upload_and_share.py <local_file_path>

Output (JSON to stdout):
    {"url": "http://localhost:9010/nexent/...", "object_name": "..."}  on success
    {"error": "..."}                                                   on failure

The script uses the platform's existing MinioClient (nexent.storage) which is
already configured with the correct endpoint, credentials, and bucket.
"""

import json
import os
import sys


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: upload_and_share.py <local_file_path>"}))
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.isfile(file_path):
        print(json.dumps({"error": f"File not found: {file_path}"}))
        sys.exit(1)

    # Ensure the backend module path is importable (run_skill_script runs in the
    # runtime venv, which has /opt/backend as the working directory).
    sys.path.insert(0, "/opt/backend")

    try:
        from database.client import minio_client
    except ImportError as exc:
        print(json.dumps({"error": f"Cannot import minio_client: {exc}"}))
        sys.exit(1)

    # Use the file's basename as the object name (avoid path conflicts).
    object_name = os.path.basename(file_path)

    try:
        ok, msg = minio_client.upload_file(file_path, object_name=object_name)
        if not ok:
            print(json.dumps({"error": f"Upload failed: {msg}"}))
            sys.exit(1)
    except Exception as exc:
        print(json.dumps({"error": f"Upload exception: {exc}"}))
        sys.exit(1)

    # Get a presigned download URL (valid 24h).
    try:
        ok, url = minio_client.get_file_url(object_name)
        if not ok:
            print(json.dumps({"error": f"get_file_url failed: {url}"}))
            sys.exit(1)
    except Exception as exc:
        print(json.dumps({"error": f"get_file_url exception: {exc}"}))
        sys.exit(1)

    # Replace the Docker-internal MinIO endpoint with a browser-accessible one.
    # The MinIO container maps port 9000 -> 9010 on the host.
    minio_endpoint = os.environ.get("MINIO_ENDPOINT", "http://nexent-minio:9000")
    # Try to derive the host-accessible port from the endpoint or env.
    # The docker-compose maps 0.0.0.0:9010->9000 — use localhost:9010.
    browser_endpoint = minio_endpoint.replace("nexent-minio:9000", "localhost:9010")
    url = url.replace(minio_endpoint, browser_endpoint)

    print(json.dumps({"url": url, "object_name": object_name}))


if __name__ == "__main__":
    main()
