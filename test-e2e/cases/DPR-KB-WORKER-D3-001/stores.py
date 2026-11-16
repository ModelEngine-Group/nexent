# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prepare only this probe's disposable infrastructure and close it by owned ID."""

import json
import subprocess
import time

import boto3
import httpx
import sqlalchemy as sa
from botocore.config import Config
from elasticsearch import Elasticsearch


def docker(*args):
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.PIPE, timeout=30
    ).strip()


class Stores:
    def __init__(self, run_id):
        self.run_id, self.containers = run_id, []
        self.engine = self.legacy = None
        self.images = {}

    def start(self):
        images = {
            "pg": "postgres:15-alpine",
            "minio": "quay.io/minio/minio:RELEASE.2023-12-20T01-00-02Z",
            "es": "docker.elastic.co/elasticsearch/elasticsearch:8.17.2",
        }
        for name, image in images.items():
            self.images[name] = docker("image", "inspect", "--format", "{{.Id}}", image)

        def start(name, *args):
            container = docker(
                "run",
                "--rm",
                "-d",
                "--label",
                "nexent.test_run=" + self.run_id,
                *args,
                images[name],
                *({"minio": ["server", "/data"]}.get(name, [])),
            )
            self.containers.append(container)
            mapping = json.loads(docker("inspect", container))[0]["NetworkSettings"][
                "Ports"
            ]
            return "127.0.0.1:" + next(iter(mapping.values()))[0]["HostPort"]

        pg = start(
            "pg", "-e", "POSTGRES_PASSWORD=fixture-password", "-p", "127.0.0.1::5432"
        )
        self.minio = "http://" + start(
            "minio",
            "-e",
            "MINIO_ROOT_USER=fixture-user",
            "-e",
            "MINIO_ROOT_PASSWORD=fixture-password",
            "-p",
            "127.0.0.1::9000",
        )
        self.es = "http://" + start(
            "es",
            "--memory",
            "1g",
            "--cpus",
            "2",
            "-e",
            "discovery.type=single-node",
            "-e",
            "xpack.security.enabled=false",
            "-e",
            "ingest.geoip.downloader.enabled=false",
            "-e",
            "xpack.ml.enabled=false",
            "-e",
            "ES_JAVA_OPTS=-Xms256m -Xmx256m",
            "-p",
            "127.0.0.1::9200",
        )
        self.engine = sa.create_engine(
            "postgresql+psycopg2://postgres:fixture-password@" + pg + "/postgres",
            connect_args={"connect_timeout": 1},
            hide_parameters=True,
        )
        self.legacy = Elasticsearch(
            self.es, request_timeout=2, max_retries=0, retry_on_timeout=False
        )
        deadline = time.monotonic() + 70
        while True:
            try:
                with self.engine.connect() as connection:
                    connection.exec_driver_sql("SELECT 1")
                with httpx.Client(trust_env=False, timeout=1) as client:
                    ready = (
                        client.get(self.minio + "/minio/health/ready").status_code
                        == 200
                    )
                if ready and self.legacy.ping():
                    break
            except (sa.exc.OperationalError, httpx.HTTPError):
                pass
            assert time.monotonic() < deadline, (
                "Owned storage startup exceeded deadline"
            )
            time.sleep(0.2)
        client = boto3.client(
            "s3",
            endpoint_url=self.minio,
            aws_access_key_id="fixture-user",
            aws_secret_access_key="fixture-password",
            region_name="us-east-1",
            config=Config(
                retries={"total_max_attempts": 1}, proxies={"http": None, "https": None}
            ),
        )
        try:
            client.create_bucket(Bucket="worker-files")
        finally:
            client.close()
        return {
            "POSTGRES_USER": "postgres",
            "NEXENT_POSTGRES_PASSWORD": "fixture-password",
            "POSTGRES_HOST": self.engine.url.host,
            "POSTGRES_PORT": str(self.engine.url.port),
            "POSTGRES_DB": "postgres",
            "MINIO_ENDPOINT": self.minio,
            "MINIO_ACCESS_KEY": "fixture-user",
            "MINIO_SECRET_KEY": "fixture-password",
            "MINIO_DEFAULT_BUCKET": "worker-files",
            "MINIO_REGION": "us-east-1",
            "ES_HOST": self.es,
            "ES_API_KEY": "",
            "JWT_SECRET": "synthetic-worker-probe-key",
        }

    def close(self):
        if self.legacy is not None:
            self.legacy.close()
        if self.engine is not None:
            self.engine.dispose()
        # The parent also checks the run label if startup lost a returned container ID.
        remaining = docker(
            "ps", "-aq", "--filter", "label=nexent.test_run=" + self.run_id
        )
        for container in remaining.splitlines():
            docker("rm", "-f", "-v", container)
        assert not docker(
            "ps", "-aq", "--filter", "label=nexent.test_run=" + self.run_id
        )
