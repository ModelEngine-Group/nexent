// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { render } from "./resourceDrawerTestUtils";
import TagDefinitionManagementPanel from "@/components/tag/TagDefinitionManagementPanel";
import { tagManagementApi } from "@/services/tagManagementService";
import type { TagDefinition } from "@/types/tagManagement";

// Unlike tagLibraryManagement.test.tsx, this spec resolves the localized strings
// the table actually renders, so the "search by the name the user sees" defect
// stays observable.
const { translations } = vi.hoisted(() => ({
  translations: {
    "tagManagement.systemDefinition.keywords": "关键词",
    "tagManagement.empty.noDefinitions": "暂无标签",
    "tagManagement.empty.noMatchingDefinitions": "没有匹配的标签定义",
  } as Record<string, string>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => translations[key] ?? key,
  }),
}));

vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listDefinitions: vi.fn(),
    createDefinition: vi.fn(),
    updateDefinitionStatus: vi.fn(),
    moveDefinitionToTop: vi.fn(),
    deleteDefinition: vi.fn(),
    createValue: vi.fn(),
    updateValue: vi.fn(),
    updateValueStatus: vi.fn(),
    deleteValue: vi.fn(),
  },
}));

const keywordsDefinition: TagDefinition = {
  definition_id: 1,
  bucket_id: 1,
  definition_key: "keywords",
  definition_name: "Keywords",
  selection_mode: "multi_select",
  sort_order: 1,
  status: "active",
  active_value_count: 1,
  value_capacity: 1000,
  values: [
    {
      value_id: 11,
      display_value: "Cache",
      normalized_value: "cache",
      sort_order: 1,
      status: "active",
    },
    {
      value_id: 12,
      display_value: "Legacy",
      normalized_value: "legacy",
      sort_order: 2,
      status: "disabled",
    },
  ],
};

const departmentDefinition: TagDefinition = {
  definition_id: 2,
  bucket_id: 1,
  definition_key: "department",
  definition_name: "Department",
  selection_mode: "single_select",
  sort_order: 2,
  status: "active",
  active_value_count: 1,
  value_capacity: 1000,
  values: [
    {
      value_id: 21,
      display_value: "财务",
      normalized_value: "finance",
      sort_order: 1,
      status: "active",
    },
  ],
};

const regionDefinition: TagDefinition = {
  definition_id: 3,
  bucket_id: 1,
  definition_key: "region",
  definition_name: "Region",
  selection_mode: "no_value",
  sort_order: 3,
  status: "active",
  active_value_count: 0,
  value_capacity: 0,
  values: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(tagManagementApi.listDefinitions).mockResolvedValue([
    keywordsDefinition,
    departmentDefinition,
    regionDefinition,
  ]);
});

function renderPanel() {
  return render(
    <App>
      <TagDefinitionManagementPanel bucketId={1} canManage />
    </App>
  );
}

async function searchFor(keyword: string) {
  const user = userEvent.setup();
  const input = screen.getByPlaceholderText("tagManagement.form.searchTags");
  await user.clear(input);
  await user.type(input, keyword);
  return input;
}

async function expectVisibleNames(visible: string[], hidden: string[]) {
  await waitFor(() =>
    visible.forEach((name) =>
      expect(screen.getByText(name)).toBeInTheDocument()
    )
  );
  hidden.forEach((name) =>
    expect(screen.queryByText(name)).not.toBeInTheDocument()
  );
}

it("shows every definition before a search starts", async () => {
  renderPanel();
  await expectVisibleNames(["关键词", "Department", "Region"], []);
});

it("matches a definition by the localized name the table renders", async () => {
  renderPanel();
  await screen.findByText("关键词");

  await searchFor("关键");

  await expectVisibleNames(["关键词"], ["Department", "Region"]);
});

it("matches a definition by its raw key", async () => {
  renderPanel();
  await screen.findByText("关键词");

  await searchFor("department");

  await expectVisibleNames(["Department"], ["关键词", "Region"]);
});

it("matches a definition by a value display value and by a normalized value", async () => {
  renderPanel();
  await screen.findByText("关键词");

  await searchFor("cache");
  await expectVisibleNames(["关键词"], ["Department", "Region"]);

  await searchFor("财务");
  await expectVisibleNames(["Department"], ["关键词", "Region"]);

  await searchFor("fin");
  await expectVisibleNames(["Department"], ["关键词", "Region"]);
});

it("finds a definition through a disabled value the expanded rows still show", async () => {
  renderPanel();
  await screen.findByText("关键词");

  await searchFor("legacy");

  await expectVisibleNames(["关键词"], ["Department", "Region"]);
});

it("treats a blank search as no filter and reports no results honestly", async () => {
  renderPanel();
  await screen.findByText("关键词");

  await searchFor("   ");
  await expectVisibleNames(["关键词", "Department", "Region"], []);

  await searchFor("nothing-matches");
  expect(await screen.findByText("没有匹配的标签定义")).toBeInTheDocument();
  expect(screen.queryByText("暂无标签")).not.toBeInTheDocument();
});

it("keeps the empty-library message when there is nothing to search", async () => {
  vi.mocked(tagManagementApi.listDefinitions).mockResolvedValue([]);
  renderPanel();

  expect(await screen.findByText("暂无标签")).toBeInTheDocument();
  expect(screen.queryByText("没有匹配的标签定义")).not.toBeInTheDocument();
});
