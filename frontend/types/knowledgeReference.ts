// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export interface KnowledgeFileReference {
  knowledge_id: number;
  file_id: string;
  file_version: number;
}

export interface KnowledgeObjectReference {
  space: string;
  key: string;
  version: string;
  sha256: string;
}

export interface KnowledgeLegacyImageReference {
  knowledge_id: number;
  chunk_key: string;
  index_uuid: string;
  sequence: number;
  primary_term: number;
  image_ref: KnowledgeObjectReference;
}

interface KnowledgeFileContentRequest extends KnowledgeFileReference {
  image_ref?: KnowledgeObjectReference;
}

export type KnowledgeContentRequest =
  KnowledgeFileContentRequest | KnowledgeLegacyImageReference;

export type KnowledgePictureReference = (
  | {
      fileRef: KnowledgeFileReference;
      imageRef: KnowledgeObjectReference;
      legacyImageRef?: never;
    }
  | {
      legacyImageRef: KnowledgeLegacyImageReference;
      fileRef?: never;
      imageRef?: never;
    }
) & { citeIndex: number; toolSign: string };
