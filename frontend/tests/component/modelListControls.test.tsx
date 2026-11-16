// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { modelService } from "../../services/modelService";
import { ModelSelector } from "../../app/[locale]/newchat/ui/model-selector";

vi.mock("../../lib/auth", () => ({ getAuthHeaders: () => ({}) }));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({ modelContext: () => ({ register: () => () => undefined }) }),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../../services/modelProfileService", () => ({
  getModelOutlet: vi.fn(async () => ({ config_revision: 7, profile: {
    parameter_values: { temperature: 0.7 }, parameter_rules: [],
    capabilities: { reasoning: { status: "unknown" } },
  }})),
  getConversationModelPreferences: vi.fn(),
  patchConversationModelPreferences: vi.fn(),
}));
afterEach(() => vi.unstubAllGlobals());

it("maps real list response metadata through getAllModels into the selector parameter entry", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ status: 200, json: async () => ({ data: [{
    model_id: 42, model_name: "Profile model", model_type: "llm", model_factory: "OpenAI",
    profile_schema_version: 1, config_revision: 7, migration_status: "migrated",
    migration_review_required: true, connect_status: "available",
  }]}) })));
  const models = await modelService.getAllModels();
  expect(models[0]).toMatchObject({ profileSchemaVersion: 1, configRevision: 7,
    migrationStatus: "migrated", migrationReviewRequired: true });
  render(<QueryClientProvider client={new QueryClient()}><App>
    <ModelSelector models={models.map((model) => ({ ...model, id: String(model.id) }))}
      value="42" defaultOpen parameterSettingsScopeKey="real-list-contract" />
  </App></QueryClientProvider>);
  expect(await screen.findByRole("button", { name: "workbench.controls.advanced" })).toBeVisible();
});
