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
    "tagManagement.hint.matchedValues": "仅显示匹配搜索的标签值",
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

let view: ReturnType<typeof render>;

function renderPanel() {
  view = render(
    <App>
      <TagDefinitionManagementPanel bucketId={1} canManage />
    </App>
  );
  return view;
}

async function searchFor(keyword: string) {
  const user = userEvent.setup();
  const input = screen.getByPlaceholderText("tagManagement.form.searchTags");
  await user.clear(input);
  if (keyword) await user.type(input, keyword);
  return input;
}

/**
 * Highlighting wraps the matched fragment of a cell in <mark>, so a searched
 * name or value is split across text nodes. Assertions therefore read the text
 * of the whole panel instead of a single text node, and skip subtrees rc-table
 * keeps mounted with display:none once a row has been collapsed again.
 */
function collectVisibleText(node: Node): string {
  if (node instanceof HTMLElement && node.style.display === "none") return "";
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  return Array.from(node.childNodes).map(collectVisibleText).join("");
}

function renderedText(): string {
  return collectVisibleText(view.container);
}

async function expectVisibleNames(visible: string[], hidden: string[]) {
  await waitFor(() =>
    visible.forEach((name) => expect(renderedText()).toContain(name))
  );
  hidden.forEach((name) => expect(renderedText()).not.toContain(name));
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

it("opens a row that matched only through one of its values and lists just that value", async () => {
  renderPanel();
  await screen.findByText("关键词");

  await searchFor("cache");

  // "Cache" only exists in the expanded table, so the row has to open for the
  // match to be visible, and it must not drag the other value along with it.
  await waitFor(() => expect(renderedText()).toContain("Cache"));
  expect(renderedText()).not.toContain("Legacy");
  expect(renderedText()).not.toContain("Department");

  // A disabled value still selects its row and narrows the inner list to itself.
  await searchFor("legacy");

  await waitFor(() => expect(renderedText()).toContain("Legacy"));
  expect(renderedText()).not.toContain("Cache");
});

it("keeps a row that matched by its own name or key collapsed", async () => {
  renderPanel();
  await screen.findByText("关键词");

  await searchFor("关键");

  await expectVisibleNames(["关键词"], []);
  expect(renderedText()).not.toContain("Cache");
  expect(renderedText()).not.toContain("Legacy");

  await searchFor("keywords");

  await expectVisibleNames(["keywords"], []);
  expect(renderedText()).not.toContain("Cache");
  expect(renderedText()).not.toContain("Legacy");
});

it("highlights the matched fragment of a name and of a value", async () => {
  renderPanel();
  await screen.findByText("关键词");

  await searchFor("关键");

  await waitFor(() =>
    expect(view.container.querySelector("mark")?.textContent).toBe("关键")
  );
  expect(renderedText()).toContain("关键词");

  await searchFor("cac");

  await waitFor(() => expect(renderedText()).toContain("Cache"));
  expect(
    Array.from(view.container.querySelectorAll("mark")).map(
      (mark) => mark.textContent
    )
  ).toEqual(["Cac"]);
});

it("restores the collapsed rows and the full value list when the search is cleared", async () => {
  renderPanel();
  await screen.findByText("关键词");

  await searchFor("cache");
  await waitFor(() => expect(renderedText()).toContain("Cache"));
  expect(renderedText()).not.toContain("Legacy");

  await searchFor("");

  await waitFor(() => expect(renderedText()).toContain("Region"));
  expect(renderedText()).toContain("关键词");
  expect(renderedText()).not.toContain("Cache");
  expect(renderedText()).not.toContain("Legacy");
});

it("lets the user collapse a row the search opened", async () => {
  renderPanel();
  await screen.findByText("关键词");

  await searchFor("cache");
  await waitFor(() => expect(renderedText()).toContain("Cache"));

  const user = userEvent.setup();
  const expandIcon = view.container.querySelector(
    ".ant-table-row-expand-icon"
  ) as HTMLElement;
  await user.click(expandIcon);

  await waitFor(() => expect(renderedText()).not.toContain("Cache"));
});
