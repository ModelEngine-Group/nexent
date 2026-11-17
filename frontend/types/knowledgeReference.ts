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

export interface KnowledgeContentRequest extends KnowledgeFileReference {
  image_ref?: KnowledgeObjectReference;
}

export interface KnowledgePictureReference {
  fileRef: KnowledgeFileReference;
  imageRef: KnowledgeObjectReference;
  citeIndex: number;
  toolSign: string;
}
