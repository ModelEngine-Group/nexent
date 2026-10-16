// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ModelMigrationReviewButton } from "../../app/[locale]/models/components/model/ModelMigrationReviewButton";
import type { ModelOption } from "../../types/modelConfig";

const mocks = vi.hoisted(() => ({
  role: "ADMIN",
  getModelOutlet: vi.fn(),
  confirmModelOutletMigration: vi.fn(),
}));
vi.mock("../../components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { role: mocks.role } }),
}));
vi.mock("../../services/modelProfileService", () => ({
  getModelOutlet: mocks.getModelOutlet,
  confirmModelOutletMigration: mocks.confirmModelOutletMigration,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const model: ModelOption = {
  id: 42,
  name: "exact",
  type: "llm",
  maxTokens: 4096,
  source: "OpenAI-API-Compatible",
  apiKey: "",
  apiUrl: "https://models.invalid/v1",
  displayName: "chosen",
  configRevision: 6,
  migrationStatus: "migrated",
  migrationReviewRequired: true,
};
function setup(value = model) {
  const onReviewed = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const rendered = render(
    <QueryClientProvider client={client}>
      <App>
        <ModelMigrationReviewButton model={value} onReviewed={onReviewed} />
      </App>
    </QueryClientProvider>
  );
  return { ...rendered, onReviewed };
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.role = "ADMIN";
  mocks.confirmModelOutletMigration.mockReset().mockResolvedValue(undefined);
  mocks.getModelOutlet.mockReset().mockResolvedValue({
    model_id: 42,
    config_revision: 7,
    has_credential: true,
    profile: {
      identity: { request_model_id: "exact" },
      connection: { base_url: "https://models.invalid/v1" },
      capabilities: {
        context: { combined_window: 200000 },
        reasoning: { status: "unsupported" },
        tools: { status: "unsupported" },
      },
      parameter_values: { temperature: 0 },
      extra_api_parameters: [],
    },
  });
});
it("only permits administrators to open a review", () => {
  mocks.role = "DEV";
  const { container } = setup();
  expect(container.textContent).toBe("");
  expect(mocks.getModelOutlet).not.toHaveBeenCalled();
});
it("confirms the displayed fresh revision and does not expose credential contents", async () => {
  const { onReviewed } = setup();
  fireEvent.click(
    screen.getByRole("button", { name: "modelMigration.review" })
  );
  await screen.findByText("modelMigration.credentialPresent");
  fireEvent.click(
    screen.getByRole("button", { name: "modelMigration.confirm" })
  );
  await waitFor(() => expect(onReviewed).toHaveBeenCalledOnce());
  expect(mocks.confirmModelOutletMigration).toHaveBeenCalledExactlyOnceWith(
    42,
    7
  );
});
it("keeps a conflicting review open and asks the administrator to review again", async () => {
  mocks.confirmModelOutletMigration.mockRejectedValue(
    new Error("MODEL_OUTLET_VERSION_CONFLICT")
  );
  const { onReviewed } = setup();
  fireEvent.click(
    screen.getByRole("button", { name: "modelMigration.review" })
  );
  await screen.findByText("modelMigration.credentialPresent");
  fireEvent.click(
    screen.getByRole("button", { name: "modelMigration.confirm" })
  );
  await screen.findByText("modelMigration.confirmFailed");
  expect(onReviewed).not.toHaveBeenCalled();
  expect(
    await screen.findByRole("button", { name: "modelMigration.confirm" })
  ).toBeVisible();
});
it("shows migration failures without loading or confirming a non-existent snapshot", async () => {
  setup({
    ...model,
    migrationStatus: "failed",
    migrationDiagnostic: { category: "LEGACY_OUTLET_INVALID" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "modelMigration.review" })
  );
  await screen.findByText("LEGACY_OUTLET_INVALID");
  expect(mocks.getModelOutlet).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "modelMigration.confirm" })
  ).toBeNull();
});
