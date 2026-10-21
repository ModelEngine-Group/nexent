# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from enum import Enum


class VectorDatabaseType(str, Enum):
    ELASTICSEARCH = "elasticsearch"
    DATAMATE = "datamate"
