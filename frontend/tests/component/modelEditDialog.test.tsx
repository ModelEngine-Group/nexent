// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { App } from "antd";

import { ModelEditDialog } from "../../app/[locale]/models/components/model/ModelEditDialog";
import type { ModelOption } from "@/types/modelConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? key,
  }),
}));

const updateManageTenantModel = vi.fn().mockResolvedValue(undefined);
const updateSingleModel = vi.fn().mockResolvedValue(undefined);

vi.mock("@/services/modelService", () => ({
  modelService: {
    updateManageTenantModel: (...args: unknown[]) =>
      updateManageTenantModel(...args),
    updateSingleModel: (...args: unknown[]) => updateSingleModel(...args),
    verifyModelConfigConnectivity: vi
      .fn()
      .mockResolvedValue({ connectivity: false }),
    suggestCapacity: vi.fn().mockResolvedValue(undefined),
  },
  ModelError: class ModelError extends Error {},
}));

const llmModel: ModelOption = {
  id: 42,
  name: "Qwen/Qwen2.5-32B-Instruct",
  displayName: "Qwen2.5",
  source: "silicon",
  type: "llm",
  maxTokens: 4096,
  apiKey: "",
  apiUrl: "https://api.siliconflow.cn/v1/",
};

function renderDialog(props?: {
  model?: ModelOption | null;
  tenantId?: string;
}) {
  return render(
    <App>
      <ModelEditDialog
        model={props?.model === undefined ? llmModel : props.model}
        tenantId={props?.tenantId}
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    </App>
  );
}

it("routes tenant edits through the manage endpoint and persists a retyped model_type", async () => {
  const user = userEvent.setup();
  renderDialog({ tenantId: "tenant-1" });

  await user.click(screen.getByRole("combobox"));
  await user.click(await screen.findByRole("option", { name: "rerank" }));
  await user.click(screen.getByRole("button", { name: "保存" }));

  await waitFor(() => expect(updateManageTenantModel).toHaveBeenCalledOnce());
  expect(updateManageTenantModel.mock.calls[0][0]).toMatchObject({
    tenantId: "tenant-1",
    currentDisplayName: "Qwen2.5",
    type: "rerank",
  });
  expect(updateSingleModel).not.toHaveBeenCalled();
});

it("omits model_type when the type is unchanged in a tenant edit", async () => {
  const user = userEvent.setup();
  renderDialog({ tenantId: "tenant-1" });

  await user.click(screen.getByRole("button", { name: "保存" }));

  await waitFor(() => expect(updateManageTenantModel).toHaveBeenCalledOnce());
  expect(updateManageTenantModel.mock.calls[0][0]).not.toHaveProperty("type");
  expect(updateSingleModel).not.toHaveBeenCalled();
});

it("keeps personal edits on the single-model endpoint", async () => {
  const user = userEvent.setup();
  renderDialog();

  await user.click(screen.getByRole("button", { name: "保存" }));

  await waitFor(() => expect(updateSingleModel).toHaveBeenCalledOnce());
  expect(updateSingleModel.mock.calls[0][0]).toMatchObject({
    currentDisplayName: "Qwen2.5",
  });
  expect(updateManageTenantModel).not.toHaveBeenCalled();
});
