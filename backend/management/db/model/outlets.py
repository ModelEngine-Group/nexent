# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Management access to the shared relational outlet implementation."""

from infrastructure.rdb.outlets import (
    create_resolved_model_record as create_resolved_model_record,
    get_resolved_model_record as get_resolved_model_record,
    update_resolved_model_record as update_resolved_model_record,
    has_model_outlet_credential as has_model_outlet_credential,
    update_model_outlet_connectivity as update_model_outlet_connectivity,
    migrate_legacy_model_records as migrate_legacy_model_records,
    confirm_model_outlet_migration as confirm_model_outlet_migration,
    repair_legacy_model_record as repair_legacy_model_record,
)
