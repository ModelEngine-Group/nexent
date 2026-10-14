import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en", resolvedLanguage: "en" },
  }),
}));

vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ appConfig: null }),
}));

vi.mock("@/services/storageService", () => ({
  extractObjectNameFromUrl: () => null,
  storageService: {
    downloadFile: vi.fn(),
    downloadDatamateFile: vi.fn(),
  },
  fetchImageBlob: vi.fn(),
  getLocalFilePreviewUrl: () => undefined,
  isLocalStorageObjectUrl: () => false,
}));

vi.mock("@/lib/logger", () => ({
  default: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    log: vi.fn(),
  },
}));

vi.mock("@/app/i18n", () => ({
  default: { language: "en", t: (key: string) => key },
  resourcesCustom: {},
}));

import {
  escapeRegExp,
  normalizeForHighlight,
  mergeHighlightTerms,
  extractHighlightTerms,
  splitSourceTextIntoSentences,
} from "@/lib/citationHighlight";
import {
  CiteIndexBadge,
  HighlightedChunkText,
} from "@/components/common/highlightedSourceText";
import {
  SourcesPanel,
  type PanelSourceItem,
} from "@/app/newchat/ui/sources-panel";
import { ENABLE_CITATION_CLICK_HIGHLIGHT } from "@/const/citation";

const noop = () => {};

function buildSources(): PanelSourceItem[] {
  return [
    {
      title: "来源 A",
      url: "https://example.com/a",
      text: "这是一个包含检索词的内容段落。",
      sourceType: "url",
      toolSign: "a",
      citeIndex: 1,
      retrievalHighlightTerms: ["检索词"],
    },
    {
      title: "来源 B",
      url: "https://example.com/b",
      text: "另一段无关内容。",
      sourceType: "url",
      toolSign: "b",
      citeIndex: 2,
    },
  ];
}

let scrollSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  scrollSpy = vi.fn();
  HTMLElement.prototype.scrollIntoView = scrollSpy as any;
});

afterEach(() => {
  cleanup();
});

describe("citationHighlight 检索高亮公共函数", () => {
  it("UT-FE-AUTO-7C7FED1DFB34DA15 转义正则特殊字符", () => {
    expect(escapeRegExp("plain")).toBe("plain");
    const escaped = escapeRegExp(".");
    expect(escaped).toHaveLength(2);
    expect(escaped.endsWith(".")).toBe(true);
  });

  it("归一化为小写", () => {
    expect(normalizeForHighlight("ABC")).toBe("abc");
  });

  it("合并去重并丢弃子串", () => {
    expect(mergeHighlightTerms(["abc", "abcdef", "x", "abc"])).toEqual([
      "abcdef",
      "x",
    ]);
  });

  it("过滤短于阈值或不在来源中的词", () => {
    expect(extractHighlightTerms("", "文本")).toEqual([]);
    expect(extractHighlightTerms("不存在的短语", "这是内容")).toEqual([]);
    expect(extractHighlightTerms("检索", "检索")).toEqual([]);
  });

  it("提取出现在来源中的中文检索词", () => {
    expect(
      extractHighlightTerms("检索词", "这是一个包含检索词的内容段落。"),
    ).toEqual(["检索词"]);
  });

  it("按句子切分来源文本", () => {
    expect(splitSourceTextIntoSentences("第一句。第二句！")).toEqual([
      "第一句。",
      "第二句！",
    ]);
  });
});

describe("HighlightedChunkText 高亮渲染", () => {
  it("将匹配句子渲染为 mark", () => {
    const { container } = render(
      <HighlightedChunkText
        text={"包含检索词的句子。另一句。"}
        terms={["检索词"]}
      />,
    );
    const mark = container.querySelector("mark");
    expect(mark).not.toBeNull();
    expect(mark?.textContent).toContain("检索词");
  });

  it("无检索词时不渲染 mark", () => {
    const { container } = render(
      <HighlightedChunkText text={"普通文本。"} terms={[]} />,
    );
    expect(container.querySelector("mark")).toBeNull();
    expect(container.textContent).toContain("普通文本");
  });

  it("检索词不在来源中时不渲染 mark", () => {
    const { container } = render(
      <HighlightedChunkText text={"普通文本。"} terms={["不存在的词"]} />,
    );
    expect(container.querySelector("mark")).toBeNull();
  });
});

describe("CiteIndexBadge 引用索引徽标", () => {
  it("有限索引渲染数字", () => {
    const { container } = render(<CiteIndexBadge index={1} />);
    expect(container.textContent).toContain("1");
  });

  it("非有限索引返回 null", () => {
    const { container } = render(<CiteIndexBadge index={undefined} />);
    expect(container.textContent).toBe("");
  });
});

describe("SourcesPanel 引用点击定位与高亮", () => {
  it("默认折叠且无来源卡选中", () => {
    const { container } = render(
      <SourcesPanel
        sources={buildSources()}
        images={[]}
        onClose={noop}

        open={false}
      />,
    );
    expect(
      container.querySelectorAll('[class*="border-[#1677ff]"]'),
    ).toHaveLength(0);
    expect(container.querySelector("mark")).toBeNull();
    expect(container.firstChild).toBeNull();
    expect(scrollSpy).not.toHaveBeenCalled();
  });

  it("选中来源卡进入蓝色边框、滚动定位并高亮检索词", () => {
    const { container } = render(
      <SourcesPanel
        sources={buildSources()}
        images={[]}
        onClose={noop}

        open

        selectedCitationKey={"a1"}
        citationContext={""}
      />,
    );
    const selected = container.querySelectorAll('[class*="border-[#1677ff]"]');
    expect(selected).toHaveLength(1);
    expect(selected[0].textContent).toContain("来源 A");
    expect(selected[0].textContent).not.toContain("来源 B");
    const mark = container.querySelector("mark");
    expect(mark).not.toBeNull();
    expect(mark?.textContent).toContain("检索词");
    expect(scrollSpy).toHaveBeenCalledWith(
      expect.objectContaining({ block: "center" }),
    );
  });

  it("过滤短于 2 字符的检索高亮词", () => {
    const sources = buildSources();
    sources[0].text = "检验内容。";
    sources[0].retrievalHighlightTerms = ["检", "不存在的词"];
    const { container } = render(
      <SourcesPanel
        sources={sources}
        images={[]}
        onClose={noop}

        open

        selectedCitationKey={"a1"}
        citationContext={""}
      />,
    );
    expect(
      container.querySelector('[class*="border-[#1677ff]"]'),
    ).not.toBeNull();
    expect(container.querySelector("mark")).toBeNull();
  });
});

describe("ENABLE_CITATION_CLICK_HIGHLIGHT 开关", () => {
  it("默认关闭，仅定位不高亮", () => {
    expect(ENABLE_CITATION_CLICK_HIGHLIGHT).toBe(false);
  });
});

// Exercise the real Markdown citation -> context -> SourcesPanel collaboration.
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
} from "@assistant-ui/react";
import { ReadOnlyConversation } from "@/app/newchat/assistant-ui/thread";

function CitationConversation() {
  const content = [
    { type: "text", text: "answer context [[a1]]" },
    ...buildSources().map((source, index) => ({
      type: "source",
      id: `source-${index}`,
      ...source,
    })),
  ];
  const runtime = useExternalStoreRuntime({
    messages: [
      {
        id: "citation-turn",
        role: "assistant" as const,
        content,
        status: { type: "complete" as const, reason: "stop" as const },
        createdAt: new Date(),
      },
    ],
    isRunning: false,
    onNew: async () => {},
    convertMessage: (message: any) => message,
  });
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ReadOnlyConversation
        agent={{ agent_id: 1, name: "fixture" } as any}
        title="Citations"
      />
    </AssistantRuntimeProvider>
  );
}

it("UT-FE-AUTO-7C7FED1DFB34DA15 clicking a citation opens and locates the source with context highlighting disabled", () => {
  const { container } = render(<CitationConversation />);
  expect(container.querySelector('[data-slot="sources-panel"]')).toBeNull();
  const marker = container.querySelector<HTMLButtonElement>(
    "button[data-citation-marker]",
  );
  expect(marker).not.toBeNull();
  fireEvent.click(marker!);
  const panel = container.querySelector('[data-slot="sources-panel"]');
  expect(panel).not.toBeNull();
  const selected = panel!.querySelector('[class*="border-[#1677ff]"]');
  expect(selected?.textContent).toContain("来源 A");
  expect(selected?.textContent).not.toContain("来源 B");
  expect(selected?.querySelector("mark")?.textContent).toContain("检索词");
  expect(selected?.textContent).not.toContain("answer context");
  expect(scrollSpy).toHaveBeenCalledWith(
    expect.objectContaining({ block: "center" }),
  );
});
