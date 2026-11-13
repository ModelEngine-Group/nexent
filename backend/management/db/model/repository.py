# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from infrastructure.rdb.model_records import (
    create_model_record as create_model_record,
    update_model_record as update_model_record,
    fail_detecting_models_on_startup as fail_detecting_models_on_startup,
    delete_model_record as delete_model_record,
    get_model_records as get_model_records,
    get_model_by_display_name as get_model_by_display_name,
    get_models_by_display_name as get_models_by_display_name,
    get_model_id_by_display_name as get_model_id_by_display_name,
    get_model_by_model_id as get_model_by_model_id,
    get_model_by_model_id_ignore_delete as get_model_by_model_id_ignore_delete,
    get_models_by_tenant_factory_type as get_models_by_tenant_factory_type,
    get_valid_model_ids as get_valid_model_ids,
    get_model_by_name_factory as get_model_by_name_factory,
)
