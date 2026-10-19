// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Relative import: the component-suite vitest config only maps "@" to the
// frontend root (no "@/app/" → "app/[locale]" rule like tsconfig has), so a
// literal relative path is the only form that resolves in both places.
import { ModelAddDialog } from "../../app/[locale]/models/components/model/ModelAddDialog";
import { modelService, ModelError } from "@/services/modelService";
import zh from "@/public/locales/zh/common.json";

// Resolve keys against the real zh bundle with {{var}} interpolation so a
// key/variable mismatch fails here instead of leaking a raw placeholder into
// the UI; missing keys still fall back to defaultValue.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (
      key: string,
      options?: { defaultValue?: string } & Record<string, unknown>
    ) => {
      const template =
        (zh as unknown as Record<string, string>)[key] ??
        options?.defaultValue ??
        key;
      return String(template).replace(
        /\{\{(\w+)\}\}/g,
        (placeholder: string, name: string) =>
          options && options[name] !== undefined
            ? String(options[name])
            : placeholder
      );
    },
  }),
}));

// Keep the real ModelError class so `instanceof` checks in the component
// work against the same constructor the mocked service throws. The service
// itself is an exported object, so its methods are mocked on that object.
vi.mock("@/services/modelService", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/services/modelService")>();
  return {
    ...actual,
    modelService: {
      ...actual.modelService,
      getFullCatalog: vi.fn(),
      addProviderModel: vi.fn(),
      suggestCapacity: vi.fn(),
      verifyModelConfigConnectivity: vi.fn(),
      addCustomModel: vi.fn(),
      backfillDefaults: vi.fn(),
    },
  };
});

// The exact detail the backend returns (HTTP 409) when a create collides
// with an existing display_name — see create_model_for_tenant.
const CONFLICT_DETAIL =
  "Name BAAI/bge-m3 is already in use, please choose another display name";

const DUP_MODEL = "BAAI/bge-m3";
const OK_MODEL = "BAAI/bge-large-en";

function renderBatchDialog() {
  const onSuccess = vi.fn();
  const onClose = vi.fn();
  render(
    <App>
      <ModelAddDialog
        isOpen
        onClose={onClose}
        onSuccess={onSuccess}
        initialTab="batch"
      />
    </App>
  );
  return { onSuccess, onClose };
}

/** Fill the batch form, fetch `models` from the provider, select every row
 *  and pass the connectivity gate, leaving the dialog ready to submit. */
async function prepareSelection(models: string[]) {
  vi.mocked(modelService.addProviderModel).mockResolvedValue(
    models.map((name) => ({
      id: name,
      model_name: name,
      model_type: "embedding",
    }))
  );
  const user = userEvent.setup();
  await user.type(screen.getByPlaceholderText("sk-..."), "sk-test");
  await user.type(
    screen.getByPlaceholderText("https://api.example.com/v1"),
    "https://api.example.com/v1"
  );
  await user.click(screen.getByRole("button", { name: /获取模型列表/ }));
  for (const name of models) {
    await screen.findByText(name);
  }
  for (const name of models) {
    await user.click(screen.getByText(name));
  }
  await user.click(screen.getByRole("button", { name: /批量检测/ }));
  await waitFor(() =>
    expect(modelService.verifyModelConfigConnectivity).toHaveBeenCalledTimes(
      models.length
    )
  );
  return user;
}

describe("ModelAddDialog batch duplicate handling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(modelService.getFullCatalog).mockResolvedValue({
      catalog: { version: "0.0.0", metadata: {}, providers: [] },
      catalogAvailable: false,
    });
    // Catalog miss: the real service throws, and the dialog's fetch loop
    // catches it and leaves the row's suggestions empty.
    vi.mocked(modelService.suggestCapacity).mockRejectedValue(
      new ModelError("no catalog entry", 404)
    );
    vi.mocked(modelService.verifyModelConfigConnectivity).mockResolvedValue({
      connectivity: true,
      model_name: "probe",
    });
    vi.mocked(modelService.backfillDefaults).mockResolvedValue({});
  });

  it("names the duplicate models when every selected row already exists", async () => {
    vi.mocked(modelService.addCustomModel).mockImplementation(async () => {
      throw new ModelError(CONFLICT_DETAIL, 409);
    });
    const { onSuccess } = renderBatchDialog();
    const user = await prepareSelection([DUP_MODEL]);

    await user.click(screen.getByRole("button", { name: "添加 1 个模型" }));

    // The failure reason must be surfaced, not just "all failed".
    expect(
      await screen.findByText(
        `全部 1 个模型添加失败：模型已存在（${DUP_MODEL}），请勿重复添加`
      )
    ).toBeInTheDocument();
    // Dialog stays open so the operator can fix the selection.
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("reports duplicates separately when part of the batch succeeds", async () => {
    vi.mocked(modelService.addCustomModel).mockImplementation(
      async (params: { displayName?: string }) => {
        if (params.displayName === DUP_MODEL) {
          throw new ModelError(CONFLICT_DETAIL, 409);
        }
        return {};
      }
    );
    const { onSuccess } = renderBatchDialog();
    const user = await prepareSelection([DUP_MODEL, OK_MODEL]);

    await user.click(screen.getByRole("button", { name: "添加 2 个模型" }));

    expect(
      await screen.findByText(
        `已添加 1 个模型，1 个失败，其中 1 个模型已存在（${DUP_MODEL}）`
      )
    ).toBeInTheDocument();
    expect(onSuccess).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(modelService.backfillDefaults).toHaveBeenCalledWith([OK_MODEL])
    );
  });

  it("keeps the generic all-failed message for non-duplicate errors", async () => {
    vi.mocked(modelService.addCustomModel).mockImplementation(async () => {
      throw new ModelError("connectivity probe failed", 500);
    });
    const { onSuccess } = renderBatchDialog();
    const user = await prepareSelection([OK_MODEL]);

    await user.click(screen.getByRole("button", { name: "添加 1 个模型" }));

    expect(
      await screen.findByText("全部 1 个模型添加失败，请检查后重试")
    ).toBeInTheDocument();
    expect(screen.queryByText(/已存在/)).not.toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("interpolates the selected count instead of leaking the i18n placeholder", async () => {
    renderBatchDialog();
    await prepareSelection([DUP_MODEL, OK_MODEL]);

    // Regression: the footer used to render "已选 {{selectedCount}} 个模型"
    // because the t() call passed `count` while the locale template expects
    // the `selectedCount` variable.
    expect(screen.getByText("已选 2 个模型")).toBeInTheDocument();
  });
});
