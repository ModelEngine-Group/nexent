// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import UploadAreaUI from "../../app/[locale]/knowledges/components/upload/UploadAreaUI";
import { KNOWLEDGE_BASE_MAX_FILE_SIZE_MB } from "@/const/knowledgeBase";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => {
      if (key === "knowledgeBase.upload.fileSizeLimit") {
        return `单个文件不得超过 ${values?.limit ?? "{{limit}}"} MB`;
      }
      return key;
    },
  }),
}));

describe("knowledge-base upload area", () => {
  it("displays the configured file-size limit in the creation hint", () => {
    render(
      <UploadAreaUI
        fileList={[]}
        uploadProps={{}}
        isLoading={false}
        isKnowledgeBaseReady={false}
        isCreatingMode
        nameStatus="available"
        isUploading={false}
        disabled={false}
        componentHeight="146px"
        newKnowledgeBaseName="新建知识库"
        selectedFiles={[]}
      />
    );

    expect(
      screen.getByText(`单个文件不得超过 ${KNOWLEDGE_BASE_MAX_FILE_SIZE_MB} MB`)
    ).toBeVisible();
  });
});
