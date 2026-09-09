#!/usr/bin/env python3
"""Upload GAIA benchmark attachments to MinIO under the gaia/ prefix.

Usage:
    backend/.venv/bin/python sdk/benchmark/generic/tools/gaia/upload_files.py
    backend/.venv/bin/python sdk/benchmark/generic/tools/gaia/upload_files.py \
        --dataset-dir $NEXENT_BENCHMARK_DATA_ROOT/datasets/gaia_level1 \
        --prefix gaia
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


GENERIC_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(GENERIC_DIR))

try:
    from ...common.benchmark_paths import DATASET_ROOT
except ImportError:
    from common.benchmark_paths import DATASET_ROOT

load_dotenv()
load_dotenv(GENERIC_DIR.parents[2] / ".env")


def upload_gaia_files(dataset_dir: str, prefix: str = "gaia"):
    import boto3
    from botocore.config import Config

    endpoint = os.getenv("MINIO_ENDPOINT", "http://localhost:9010")
    access_key = os.getenv("MINIO_ACCESS_KEY", "nexent")
    secret_key = os.getenv("MINIO_SECRET_KEY", "nexent@4321")
    bucket = os.getenv("MINIO_DEFAULT_BUCKET", "nexent")

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
    )

    dataset_path = Path(dataset_dir)
    if not dataset_path.is_dir():
        print(f"ERROR: dataset dir not found: {dataset_dir}")
        sys.exit(1)

    attachment_extensions = {
        ".mp3", ".wav", ".m4a", ".ogg", ".flac",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
        ".pdf", ".docx", ".doc", ".pptx", ".ppt",
        ".xlsx", ".xls", ".csv", ".tsv",
        ".txt", ".md", ".html", ".htm", ".rtf",
        ".mp4", ".avi", ".mov", ".mkv", ".webm",
        ".py", ".json", ".xml", ".epub",
        ".zip", ".tar", ".gz",
    }

    files = [
        f for f in dataset_path.iterdir()
        if f.is_file() and f.suffix.lower() in attachment_extensions
    ]

    if not files:
        print(f"No attachment files found in {dataset_dir}")
        return

    print(f"Found {len(files)} attachment files in {dataset_dir}")
    print(f"Uploading to MinIO ({endpoint}) bucket={bucket} prefix={prefix}/")

    uploaded = 0
    skipped = 0
    failed = 0

    for f in sorted(files):
        object_name = f"{prefix}/{f.name}"

        try:
            s3.head_object(Bucket=bucket, Key=object_name)
            skipped += 1
            continue
        except Exception:
            pass

        try:
            s3.upload_file(str(f), bucket, object_name)
            uploaded += 1
            print(f"  ✓ {f.name} → s3://{bucket}/{object_name}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {f.name}: {e}")

    print(f"\nDone: {uploaded} uploaded, {skipped} skipped (already exist), {failed} failed")


def main():
    parser = argparse.ArgumentParser(description="Upload GAIA attachments to MinIO")
    parser.add_argument(
        "--dataset-dir",
        type=str,
        default=str(DATASET_ROOT / "gaia_level1"),
        help="Directory containing GAIA attachment files",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="gaia",
        help="MinIO object prefix (default: gaia)",
    )
    args = parser.parse_args()
    upload_gaia_files(args.dataset_dir, args.prefix)


if __name__ == "__main__":
    main()
