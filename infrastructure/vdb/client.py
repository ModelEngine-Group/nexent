# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from nexent.vector_database.datamate_core import DataMateCore
from nexent.vector_database.elasticsearch_core import ElasticSearchCore


def create_elasticsearch_core(*, host: str | None, api_key: str | None) -> ElasticSearchCore:
    return ElasticSearchCore(host=host, api_key=api_key, verify_certs=False, ssl_show_warn=False)


def create_datamate_core(*, base_url: str) -> DataMateCore:
    return DataMateCore(base_url=base_url)
