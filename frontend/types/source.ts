// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type {
  KnowledgeFileReference,
  KnowledgeObjectReference,
} from "./knowledgeReference";

export type JsonValue =
  string | number | boolean | null | JsonValue[] | JsonObject;

export interface JsonObject {
  [key: string]: JsonValue;
}

export interface SourceAttributes {
  fileRef?: KnowledgeFileReference;
  imageRef?: KnowledgeObjectReference;
  sourceLocation?: JsonObject;
  searchType?: string;
  toolSign?: string;
  sourceMetadata?: JsonObject;
  sourceReference?: Record<string, unknown>;
}
