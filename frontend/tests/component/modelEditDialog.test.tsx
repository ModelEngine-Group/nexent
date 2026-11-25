// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { App } from "antd";

import { ModelEditDialog } from "../../app/[locale]/models/components/model/ModelEditDialog";
import { modelService } from "@/services/modelService";
import type { ModelOption } from "@/types/modelConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string; id?: string }) =>
      options?.defaultValue ?? (options?.id ? `${key}:${options.id}` : key),
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

it("ME-04 migration failures use the existing edit dialog with an inline warning", () => {
  renderDialog({ model: { ...llmModel, migrationStatus: "failed" } });
  expect(screen.getByRole("alert")).toHaveTextContent("modelMigration.failedHint");
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  expect(screen.queryByText("modelMigration.reviewTitle")).not.toBeInTheDocument();
});


it("shows the classified draft failure and clears it when a retry succeeds", async () => {
  vi.mocked(modelService.verifyModelConfigConnectivity)
    .mockResolvedValueOnce({
      model_name: "Qwen",
      connectivity: false,
      diagnostic: {
        category: "MODEL_AUTHENTICATION_ERROR",
        scope: "connection",
        request_id: "edit-probe-id",
        http_status: 401,
        messages: { en: "Authentication failed (401)" },
      },
    })
    .mockResolvedValueOnce({ model_name: "Qwen", connectivity: true });
  renderDialog();
  const check = screen.getByRole("button", { name: "检测连通性" });
  fireEvent.click(check);
  const details = await screen.findByRole("button", { name: "modelProfile.checkIssues" });
  fireEvent.click(details);
  expect(await screen.findByText(/Authentication failed \(401\).*edit-probe-id/)).toBeVisible();
  fireEvent.click(details);
  fireEvent.click(check);
  expect(await screen.findByText("可用")).toBeVisible();
  expect(screen.queryByRole("button", { name: "modelProfile.checkIssues" })).toBeNull();
});
