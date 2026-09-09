# -*- coding: utf-8 -*-
"""Langfuse API helper - bypasses SDK v4 Pydantic validation issues.

The Langfuse Python SDK v4.13.1 expects a `media_references` field in
DatasetItem responses that older self-hosted servers (v3.x) don't return.
This module uses the raw HTTP API for dataset operations while still
using the SDK for run_experiment (which works fine).
"""
import os
from typing import Any

import requests


class LangfuseAPI:
    """Thin wrapper around Langfuse's REST API for dataset operations."""

    def __init__(
        self,
        host: str = None,
        public_key: str = None,
        secret_key: str = None,
    ):
        self.host = (host or os.environ.get("LANGFUSE_HOST", "")).rstrip("/")
        self.public_key = public_key or os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        self.secret_key = secret_key or os.environ.get("LANGFUSE_SECRET_KEY", "")

        if not all([self.host, self.public_key, self.secret_key]):
            raise ValueError(
                "LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY must be set"
            )

    def _post(self, path: str, json: dict) -> dict:
        resp = requests.post(
            f"{self.host}{path}",
            auth=(self.public_key, self.secret_key),
            json=json,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _get(self, path: str, params: dict = None) -> dict:
        resp = requests.get(
            f"{self.host}{path}",
            auth=(self.public_key, self.secret_key),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> None:
        resp = requests.delete(
            f"{self.host}{path}",
            auth=(self.public_key, self.secret_key),
            timeout=30,
        )
        resp.raise_for_status()

    def health_check(self) -> bool:
        """Verify Langfuse connectivity."""
        try:
            resp = requests.get(
                f"{self.host}/api/public/health",
                auth=(self.public_key, self.secret_key),
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def create_dataset(self, name: str, description: str = "",
                       metadata: dict = None) -> dict:
        """Create a dataset (idempotent - returns existing if name matches)."""
        return self._post("/api/public/datasets", {
            "name": name,
            "description": description,
            "metadata": metadata or {},
        })

    def create_dataset_item(
        self,
        dataset_name: str,
        input: Any,
        expected_output: Any = None,
        metadata: dict = None,
        item_id: str = None,
    ) -> dict:
        """Create a dataset item via raw API."""
        payload = {
            "datasetName": dataset_name,
            "input": input,
        }
        if expected_output is not None:
            payload["expectedOutput"] = expected_output
        if metadata:
            payload["metadata"] = metadata
        if item_id:
            payload["id"] = item_id

        return self._post("/api/public/dataset-items", payload)

    def get_dataset(self, name: str) -> dict:
        """Get dataset with items."""
        return self._get(f"/api/public/datasets/{name}")

    def list_datasets(self, page: int = 1, limit: int = 50) -> dict:
        """List all datasets."""
        return self._get("/api/public/datasets", {"page": page, "limit": limit})

    def delete_dataset(self, name: str) -> None:
        """Delete a dataset."""
        self._delete(f"/api/public/datasets/{name}")
