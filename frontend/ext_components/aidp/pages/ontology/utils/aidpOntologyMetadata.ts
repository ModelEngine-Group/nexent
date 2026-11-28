// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { AidpMetadataFieldType, AidpOntologyMetadataField } from "@/ext_components/aidp/shared/types/ontology";

export const AIDP_METADATA_PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
export const AIDP_METADATA_DEFAULT_PAGE_SIZE = 10;

export const AIDP_METADATA_TYPE_LABEL_KEYS: Record<AidpMetadataFieldType, string> = {
  string: "aidpKnowledge.ontologyMetadataTypeText",
  date: "aidpKnowledge.ontologyMetadataTypeDate",
  number: "aidpKnowledge.ontologyMetadataTypeNumber",
};

export const aidpMetadataFieldKey = (
  field: AidpOntologyMetadataField
): string => String(field.id ?? field.field_name);
