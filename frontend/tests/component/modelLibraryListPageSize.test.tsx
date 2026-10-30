// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ModelLibraryList,
  computePageSize,
} from "../../app/[locale]/models/components/model/ModelLibraryList";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ModelOption } from "@/types/modelConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue ?? key,
  }),
}));

const permission = vi.hoisted(() => ({ edit: true }));
vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({
    isReady: true,
    can: (key: string) => key !== "model:update" || permission.edit,
    canAny: () => true,
  }),
}));

/** Controllable ResizeObserver: tests push measurements via trigger(). */
class MockResizeObserver {
  static instances: MockResizeObserver[] = [];
  callback: () => void;
  constructor(callback: () => void) {
    this.callback = callback;
    MockResizeObserver.instances.push(this);
  }
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  trigger() {
    this.callback();
  }
}

function makeModels(count: number): ModelOption[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i + 1,
    name: `vendor/model-${String(i + 1).padStart(2, "0")}`,
    displayName: `Model ${String(i + 1).padStart(2, "0")}`,
    type: "llm",
    source: "silicon",
    apiKey: "",
    apiUrl: "https://example.com/v1",
    maxTokens: 4096,
    connect_status: "available",
  }));
}

function renderList(models: ModelOption[]) {
  return render(
    <TooltipProvider>
      <ModelLibraryList
        models={models}
        defaultSlotMap={{}}
        onCheck={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
      />
    </TooltipProvider>
  );
}

const rowCount = () => document.querySelectorAll("[data-model-row]").length;

/** Stub jsdom geometry (all zero by default) and fire the observer. */
async function resizeTo(geometry: {
  container: number;
  row: number;
  header: number;
}) {
  const scroller = document.querySelector("[data-model-list-scroll]");
  expect(scroller).toBeTruthy();
  Object.defineProperty(scroller!, "clientHeight", {
    configurable: true,
    get: () => geometry.container,
  });
  scroller!.querySelectorAll("[data-model-row]").forEach((row) =>
    Object.defineProperty(row, "offsetHeight", {
      configurable: true,
      get: () => geometry.row,
    })
  );
  const header = scroller!.querySelector("[data-model-row-header]");
  if (header) {
    Object.defineProperty(header, "offsetHeight", {
      configurable: true,
      get: () => geometry.header,
    });
  }
  const observer = MockResizeObserver.instances[0];
  await act(async () => {
    observer.trigger();
  });
}

// setup.ts installs a non-configurable (but writable) ResizeObserver stub,
// so vi.stubGlobal cannot redefine it — assign and restore instead.
const originalResizeObserver = (globalThis as { ResizeObserver?: unknown })
  .ResizeObserver;

beforeEach(() => {
  permission.edit = true;
  MockResizeObserver.instances = [];
  (globalThis as { ResizeObserver: unknown }).ResizeObserver =
    MockResizeObserver;
});

afterEach(() => {
  (globalThis as { ResizeObserver: unknown }).ResizeObserver =
    originalResizeObserver;
});

describe("computePageSize", () => {
  it("falls back to the minimum before geometry is known", () => {
    expect(computePageSize(0, 64, 40)).toBe(8);
    expect(computePageSize(700, 0, 40)).toBe(8);
  });

  it("derives the row count from the measured geometry", () => {
    // (700 - 40) / 64 = 10.3 → 10 rows
    expect(computePageSize(700, 64, 40)).toBe(10);
    // no header on narrow viewports: 640 / 64 = 10
    expect(computePageSize(640, 64, 0)).toBe(10);
    // (1344 - 40) / 64 = 20.3 → 20 rows
    expect(computePageSize(1344, 64, 40)).toBe(20);
  });

  it("clamps to [8, 50]", () => {
    // (100 - 40) / 64 = 0 → minimum
    expect(computePageSize(100, 64, 40)).toBe(8);
    // huge viewport → maximum
    expect(computePageSize(100000, 64, 40)).toBe(50);
  });
});

describe("ModelLibraryList adaptive pagination", () => {
  it("fills the page from the measured viewport and keeps paging", async () => {
    const user = userEvent.setup();
    renderList(makeModels(25));

    // Before measurement the list keeps the previous fixed page size.
    expect(rowCount()).toBe(8);

    // 10 rows fit a 700px viewport with a 40px header and 64px rows.
    await resizeTo({ container: 700, row: 64, header: 40 });
    expect(rowCount()).toBe(10);
    expect(screen.getByText("共 25 个模型，第 1/3 页")).toBeInTheDocument();

    // Paging still works with the derived size.
    await user.click(screen.getByRole("button", { name: "3" }));
    expect(rowCount()).toBe(5);
    expect(screen.getByText("共 25 个模型，第 3/3 页")).toBeInTheDocument();
  });

  it("keeps the minimum page size on tiny viewports", async () => {
    renderList(makeModels(25));
    await resizeTo({ container: 100, row: 64, header: 40 });
    expect(rowCount()).toBe(8);
    expect(screen.getByText("共 25 个模型，第 1/4 页")).toBeInTheDocument();
  });

  it("caps the page size on huge viewports", async () => {
    renderList(makeModels(25));
    await resizeTo({ container: 100000, row: 64, header: 40 });
    expect(rowCount()).toBe(25);
    expect(screen.getByText("共 25 个模型，第 1/1 页")).toBeInTheDocument();
  });

  it("re-derives the page size when the viewport resizes", async () => {
    renderList(makeModels(25));
    await resizeTo({ container: 700, row: 64, header: 40 });
    expect(rowCount()).toBe(10);

    // A taller viewport fits 20 rows per page.
    await resizeTo({ container: 1344, row: 64, header: 40 });
    expect(rowCount()).toBe(20);
    expect(screen.getByText("共 25 个模型，第 1/2 页")).toBeInTheDocument();
  });

  it("re-derives the page size when the measured row height grows", async () => {
    renderList(makeModels(25));
    await resizeTo({ container: 700, row: 64, header: 40 });
    expect(rowCount()).toBe(10);

    // Rows stacking taller (e.g. narrow viewport) shrink the page:
    // (700 - 40) / 100 = 6.6 → clamped to the minimum of 8.
    await resizeTo({ container: 700, row: 100, header: 40 });
    expect(rowCount()).toBe(8);
    expect(screen.getByText("共 25 个模型，第 1/4 页")).toBeInTheDocument();
  });
});

it.each([
  ["migrated" as const, true, "modelMigration.pending"],
  ["failed" as const, undefined, "modelMigration.failed"],
])(
  "ME-01 %s review uses the single marked edit action",
  async (migrationStatus, migrationReviewRequired, hint) => {
    const edit = vi.fn();
    const model = {
      ...makeModels(1)[0],
      migrationStatus,
      migrationReviewRequired,
    };
    const { container } = render(
      <TooltipProvider>
        <ModelLibraryList
          models={[model]}
          defaultSlotMap={{}}
          onCheck={vi.fn()}
          onEdit={edit}
          onDelete={vi.fn()}
        />
      </TooltipProvider>
    );
    const action = screen.getByRole("button", {
      name: `common.edit · ${hint}`,
    });
    expect(action.querySelector("svg.lucide-circle-alert")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "modelMigration.review" })
    ).not.toBeInTheDocument();
    expect(
      container.querySelector("[data-model-row]")?.querySelectorAll("button")
    ).toHaveLength(3);
    await userEvent.click(action);
    expect(edit).toHaveBeenCalledExactlyOnceWith(model);
  }
);
it("ME-01 reviewed outlets have an ordinary pencil with no warning", () => {
  const { container } = renderList([
    {
      ...makeModels(1)[0],
      migrationStatus: "migrated",
      migrationReviewRequired: false,
    },
  ]);
  const edit = screen.getByRole("button", { name: "编辑" });
  expect(edit.querySelector("svg.lucide-circle-alert")).not.toBeInTheDocument();
  expect(
    container.querySelector("[data-model-row]")?.querySelectorAll("button")
  ).toHaveLength(3);
});

it("ME-01 review warnings do not bypass edit permission", () => {
  permission.edit = false;
  renderList([{ ...makeModels(1)[0], migrationStatus: "migrated", migrationReviewRequired: true }]);
  expect(screen.queryByRole("button", { name: /common.edit/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "modelMigration.review" })).not.toBeInTheDocument();
});
