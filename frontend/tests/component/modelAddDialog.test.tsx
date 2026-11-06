// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { App } from "antd";

import { ModelAddDialog } from "../../app/[locale]/models/components/model/ModelAddDialog";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? key,
  }),
}));

const createManageTenantModel = vi.fn().mockResolvedValue(undefined);
const addCustomModel = vi.fn().mockResolvedValue(undefined);

vi.mock("@/services/modelService", () => ({
  modelService: {
    createManageTenantModel: (...args: unknown[]) =>
      createManageTenantModel(...args),
    addCustomModel: (...args: unknown[]) => addCustomModel(...args),
    getFullCatalog: vi.fn().mockResolvedValue({ catalog: { providers: [] } }),
    verifyModelConfigConnectivity: vi
      .fn()
      .mockResolvedValue({ connectivity: true }),
    suggestCapacity: vi.fn().mockResolvedValue(undefined),
  },
  ModelError: class ModelError extends Error {},
}));

function renderDialog(props?: { tenantId?: string }) {
  return render(
    <App>
      <ModelAddDialog isOpen onClose={vi.fn()} onSuccess={vi.fn()} {...props} />
    </App>
  );
}

async function fillAndProbe(user: ReturnType<typeof userEvent.setup>) {
  // Default provider is the custom one: name + Base URL unlock the probe.
  await user.type(
    screen.getByPlaceholderText("Qwen/Qwen3-8B"),
    "Qwen/Qwen3-8B"
  );
  await user.type(
    screen.getByPlaceholderText("https://api.example.com/v1"),
    "https://api.example.com/v1"
  );
  await user.click(screen.getByRole("button", { name: "检测连通性" }));
  await waitFor(() =>
    expect(screen.getByText("可用", { exact: true })).toBeInTheDocument()
  );
}

it("routes tenant creates through the manage endpoint", async () => {
  const user = userEvent.setup();
  renderDialog({ tenantId: "tenant-1" });

  await fillAndProbe(user);
  await user.click(screen.getByRole("button", { name: "添加模型" }));

  await waitFor(() => expect(createManageTenantModel).toHaveBeenCalledOnce());
  expect(createManageTenantModel.mock.calls[0][0]).toMatchObject({
    tenantId: "tenant-1",
    name: "Qwen/Qwen3-8B",
    type: "llm",
    url: "https://api.example.com/v1",
  });
  expect(addCustomModel).not.toHaveBeenCalled();
});

it("keeps personal creates on the custom-model endpoint", async () => {
  const user = userEvent.setup();
  renderDialog();

  await fillAndProbe(user);
  await user.click(screen.getByRole("button", { name: "添加模型" }));

  await waitFor(() => expect(addCustomModel).toHaveBeenCalledOnce());
  expect(addCustomModel.mock.calls[0][0]).toMatchObject({
    name: "Qwen/Qwen3-8B",
    type: "llm",
  });
  expect(createManageTenantModel).not.toHaveBeenCalled();
});
