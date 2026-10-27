// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, within, waitFor, act } from '@testing-library/react';
import {
  getCitationKey,
  getCitationLabel,
  SourcesPanel,
} from '@/app/[locale]/newchat/ui/sources-panel';
import { defaultComponents } from '@/app/[locale]/newchat/ui/markdown-text';

const h = vi.hoisted(() => ({
  citation: { enabled: false },
  aui: { message: { id: 'msg-1', content: [] as any[] } },
  open: vi.fn(),
  citeMarkerProps: [] as any[],
  storageDownload: vi.fn(),
  registered: undefined as any[] | undefined,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

vi.mock('@/lib/logger', () => ({ default: { error: vi.fn(), warn: vi.fn(), log: vi.fn() } }));

vi.mock('@/const/citation', () => ({
  get ENABLE_CITATION_CLICK_HIGHLIGHT() {
    return h.citation.enabled;
  },
}));

vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
}));

vi.mock('@/services/storageService', () => ({
  getLocalFileDownloadUrl: (u: any) => u,
  isLocalStorageObjectUrl: () => false,
  extractObjectNameFromUrl: () => null,
  fetchImageBlob: () => Promise.reject(new Error('not-implemented')),
  getLocalFilePreviewUrl: () => undefined,
  storageService: { downloadFileWithAuth: h.storageDownload },
}));

vi.mock('@assistant-ui/react-markdown', () => ({
  unstable_memoizeMarkdownComponents: (c: any) => c,
  MarkdownTextPrimitive: () => null,
  useIsMarkdownCodeBlock: () => false,
}));

vi.mock('@assistant-ui/react', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@assistant-ui/react')>()),
  useAuiState: (selector: (s: any) => any) => selector(h.aui),
}));

vi.mock('@/app/[locale]/newchat/ui/sources-panel-context', () => ({
  useSourcesPanelActions: () => ({ open: h.open }),
}));

vi.mock('@/app/[locale]/newchat/ui/cite-marker', () => ({
  CiteMarker: (props: any) => {
    h.citeMarkerProps.push(props);
    return null;
  },
}));

vi.mock('@/app/[locale]/newchat/ui/remark-cite', () => ({
  remarkCite: {},
}));

vi.mock('@/app/[locale]/newchat/ui/mermaid-diagram', () => ({
  MermaidDiagram: () => null,
}));

vi.mock('@/app/[locale]/newchat/ui/shiki-highlighter', () => ({
  SyntaxHighlighter: () => null,
}));

vi.mock('@/app/[locale]/newchat/ui/authenticated-image', () => ({
  AuthenticatedImage: () => null,
}));

vi.mock('@/app/[locale]/newchat/ui/tooltip-icon-button', () => ({
  TooltipIconButton: () => null,
}));

vi.mock('@/app/[locale]/newchat/adapter/remote-chat-model-adapter', () => ({
  searchSourcesRegistry: { get: () => undefined },
  searchImagesRegistry: { get: () => undefined },
  conversationSourcesRegistry: { get: () => h.registered },
}));

vi.mock('@/components/ui/button', () => ({
  Button: () => null,
}));

vi.mock('@/components/common/highlightedSourceText', () => ({
  CiteIndexBadge: ({ index }: { index?: number }) => Number.isFinite(index)
    ? <span data-testid='citation-index-badge'>{index}</span>
    : null,
  HighlightedChunkText: () => null,
}));

vi.mock('@/lib/citationHighlight', () => ({
  extractHighlightTerms: () => [],
  mergeHighlightTerms: (a: any[], b: any[]) => [...(a ?? []), ...(b ?? [])],
}));

const Cite = defaultComponents.cite as unknown as (props: {
  citekey?: string;
}) => any;

function openCurrentMessage(citekey: string) {
  h.open.mockClear();
  h.citeMarkerProps.length = 0;
  const marker = render(<Cite citekey={citekey} />);
  h.citeMarkerProps.at(-1).onClick(null);
  marker.unmount();
  return h.open.mock.calls.at(-1)![0];
}

beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = vi.fn();
  h.citation.enabled = false;
  h.aui.message.id = 'msg-1';
  h.aui.message.content = [];
  h.registered = undefined;
  h.open.mockClear();
  h.citeMarkerProps.length = 0;
  h.storageDownload.mockReset().mockResolvedValue(undefined);
});

describe('getCitationKey combined citation key generation', () => {
  it('UT-FE-AUTO-82166F602745F6D7 builds distinct combined keys from toolSign + citeIndex', () => {
    expect(getCitationKey({ citeIndex: 1, toolSign: 'a' })).toBe('a1');
    expect(getCitationKey({ citeIndex: 1, toolSign: 'b' })).toBe('b1');
    expect(getCitationKey({ citeIndex: 1, toolSign: 'A' })).toBe('a1');
    expect(getCitationKey({ citeIndex: 2, toolSign: 'a' })).toBe('a2');
  });

  it('falls back to a numeric key when toolSign is missing', () => {
    expect(getCitationKey({ citeIndex: 1 })).toBe('1');
  });

  it('returns undefined when citeIndex is not finite', () => {
    expect(getCitationKey({ citeIndex: undefined, toolSign: 'a' })).toBeUndefined();
    expect(getCitationKey({ citeIndex: NaN, toolSign: 'a' })).toBeUndefined();
  });
});

describe('getCitationLabel', () => {
  const labels = { knowledgeBase: 'kb', web: 'web', source: 'source' };

  it('labels knowledge-base tool signs', () => {
    expect(getCitationLabel({ citeIndex: 1, toolSign: 'a', sourceType: 'url' }, labels)).toBe('kb 1');
  });

  it('labels web tool signs', () => {
    expect(getCitationLabel({ citeIndex: 2, toolSign: 'b', sourceType: 'url' }, labels)).toBe('web 2');
  });

  it('labels unknown tool signs as generic source', () => {
    expect(getCitationLabel({ citeIndex: 3, sourceType: 'url' }, labels)).toBe('source 3');
  });
});

describe('citation marker resolution via findCiteSource', () => {
  const sourceA = { type: 'source', citeIndex: 1, toolSign: 'a', title: 'Source A', url: 'https://a.example.com' };
  const sourceB = { type: 'source', citeIndex: 1, toolSign: 'b', title: 'Source B', url: 'https://b.example.com' };

  it('matches a1 and b1 to their own sources without confusion', () => {
    h.aui.message.content = [
      { type: 'text', text: 'Answer [[a1]][[b1]]' },
      sourceA,
      sourceB,
    ];
    const { rerender } = render(<Cite citekey='a1' />);
    expect(h.citeMarkerProps[0].loading).toBe(false);
    expect(h.citeMarkerProps[0].title).toBe('Source A');

    rerender(<Cite citekey='b1' />);
    const b1props = h.citeMarkerProps[h.citeMarkerProps.length - 1];
    expect(b1props.loading).toBe(false);
    expect(b1props.title).toBe('Source B');
  });

  it('resolves a numeric-only legacy marker to the source with no toolSign', () => {
    h.aui.message.content = [
      { type: 'text', text: 'legacy [[1]]' },
      { type: 'source', citeIndex: 1, title: 'Legacy Source' },
    ];
    render(<Cite citekey='1' />);
    expect(h.citeMarkerProps[0].loading).toBe(false);
    expect(h.citeMarkerProps[0].title).toBe('Legacy Source');
  });

  it('resolves a numeric-only marker through the citeIndex fallback branch', () => {
    h.aui.message.content = [
      { type: 'text', text: 'legacy [[1]]' },
      { type: 'source', citeIndex: 1, toolSign: 'a', title: 'Migrated Source' },
    ];
    render(<Cite citekey='1' />);
    expect(h.citeMarkerProps[0].loading).toBe(false);
    expect(h.citeMarkerProps[0].title).toBe('Migrated Source');
  });

  it('shows loading for an unmatched citekey without throwing', () => {
    h.aui.message.content = [
      { type: 'text', text: 'answer [[q9]]' },
      { type: 'source', citeIndex: 5, toolSign: 'z', title: 'Unrelated' },
    ];
    expect(() => render(<Cite citekey='q9' />)).not.toThrow();
    expect(h.citeMarkerProps[0].loading).toBe(true);
  });
});

describe('citation click behaviour', () => {
  it('opens the panel with selectedCitationKey and passes through source fields when highlight is off', () => {
    h.citation.enabled = false;
    h.aui.message.content = [
      { type: 'text', text: 'Answer [[a1]]' },
      {
        type: 'source',
        citeIndex: 1,
        toolSign: 'a',
        title: 'Source A',
        url: 'https://a.example.com',
        publishedDate: '2026-01-01',
        retrievalHighlightTerms: ['alpha', 'beta'],
        searchType: 'aidp_search',
        sourceMetadata: { count: 0, enabled: false, custom: { values: [0, false] } },
        sourceReference: { chunk_id: 'chunk-a' },
      },
    ];
    render(<Cite citekey='a1' />);
    const onClick = h.citeMarkerProps[0].onClick;
    expect(typeof onClick).toBe('function');
    onClick(null);
    expect(h.open).toHaveBeenCalledTimes(1);
    const payload = h.open.mock.calls[0][0];
    expect(payload.selectedCitationKey).toBe('a1');
    expect(payload.citationContext).toBeUndefined();
    expect(payload.sources[0].retrievalHighlightTerms).toEqual(['alpha', 'beta']);
    expect(payload.sources[0].publishedDate).toBe('2026-01-01');
    expect(payload.sources[0].searchType).toBe('aidp_search');
    expect(payload.sources[0].sourceMetadata).toEqual({ count: 0, enabled: false, custom: { values: [0, false] } });
    expect(payload.sources[0].sourceReference).toEqual({ chunk_id: 'chunk-a' });
  });

  it('computes the preceding sentence scope as citationContext when highlight is on', () => {
    h.citation.enabled = true;
    h.aui.message.content = [
      { type: 'text', text: 'First sentence here. Second sentence here[[a1]]' },
      { type: 'source', citeIndex: 1, toolSign: 'a', title: 'Source A', url: 'https://a.example.com' },
    ];
    render(<Cite citekey='a1' />);
    h.citeMarkerProps[0].onClick(null);
    const payload = h.open.mock.calls[0][0];
    expect(payload.selectedCitationKey).toBe('a1');
    expect(payload.citationContext).toBe('Second sentence here');
  });

  it('stops sentence scope at a newline separator', () => {
    h.citation.enabled = true;
    const newline = String.fromCharCode(10);
    h.aui.message.content = [
      { type: 'text', text: 'First line sentence.' + newline + 'Second line[[a1]]' },
      { type: 'source', citeIndex: 1, toolSign: 'a', title: 'Source A' },
    ];
    render(<Cite citekey='a1' />);
    h.citeMarkerProps[0].onClick(null);
    expect(h.open.mock.calls[0][0].citationContext).toBe('Second line');
  });

  it('stops sentence scope at a table-cell separator', () => {
    h.citation.enabled = true;
    h.aui.message.content = [
      { type: 'text', text: 'Column A | Column B[[a1]]' },
      { type: 'source', citeIndex: 1, toolSign: 'a', title: 'Source A' },
    ];
    render(<Cite citekey='a1' />);
    h.citeMarkerProps[0].onClick(null);
    expect(h.open.mock.calls[0][0].citationContext).toBe('Column B');
  });
});

describe('SourcesPanel selection and passthrough', () => {
  it('keeps citation, tooltip and panel numbers aligned across source and image tabs', async () => {
    h.aui.message.content = [
      { type: 'text', text: 'Text [[a1]], figures [[a3]][[a4]], guideline [[a2]]' },
      { type: 'source', sourceType: 'document', citeIndex: 2, toolSign: 'a', title: 'Guideline' },
      { type: 'source', sourceType: 'document', citeIndex: 1, toolSign: 'a', title: 'Text' },
      { type: 'source', citeIndex: 4, toolSign: 'a', title: 'Second figure', url: 'https://example.com/second.png', isImage: true },
      { type: 'source', citeIndex: 3, toolSign: 'a', title: 'First figure', url: 'https://example.com/first.png', isImage: true },
    ];
    const marker = render(<Cite citekey='a2' />);
    const markerProps = h.citeMarkerProps.at(-1);
    expect(markerProps.displayIndex).toBe(4);
    expect(markerProps.sourceIndex).toBe(2);
    expect(markerProps.label).toBe('chat.sources.knowledgeBase 4');
    markerProps.onClick(null);
    const payload = h.open.mock.calls.at(-1)![0];
    expect(payload.selectedCitationKey).toBe('a2');
    expect(payload.sources.map((item: any) => item.citeIndex)).toEqual([1, 2]);
    const panel = render(<SourcesPanel {...payload} open onClose={() => {}} />);
    expect(within(panel.container).getAllByTestId('citation-index-badge').map((node) => node.textContent))
      .toEqual(['1', '4']);
    expect(screen.getByText('Guideline').closest('li')?.className).toContain('border-[#1677ff]');

    marker.rerender(<Cite citekey='a4' />);
    const imageMarkerProps = h.citeMarkerProps.at(-1);
    expect(imageMarkerProps.displayIndex).toBe(3);
    imageMarkerProps.onClick(null);
    const imagePayload = h.open.mock.calls.at(-1)![0];
    panel.rerender(<SourcesPanel {...imagePayload} selectionToken={imagePayload} open onClose={() => {}} />);
    await waitFor(() => expect(within(panel.container).getAllByTestId('citation-index-badge')
      .map((node) => node.textContent)).toEqual(['2', '3']));
    expect(screen.getByText('Second figure').closest('[data-citation-selected="true"]')).toBeTruthy();
    expect(imagePayload.selectedCitationKey).toBe('a4');
    marker.unmount();
    panel.unmount();

    const anchor = { type: 'source', sourceType: 'document', citeIndex: 1, toolSign: 'a', title: 'Anchor' };
    h.aui.message = { id: 'web-A', content: [anchor, ...Array.from({ length: 3 }, (_, index) => ({ type: 'source', citeIndex: 0, toolSign: '', isImage: true, title: `Web ${index + 1}`, url: `https://example.com/web-${index + 1}.png` }))] };
    const webPayload = openCurrentMessage('a1');
    expect(webPayload.images).toHaveLength(3);
    const web = render(<SourcesPanel {...webPayload} selectionToken={webPayload} open onClose={() => {}} />);
    fireEvent.click(within(web.container).getByRole('tab', { name: /chat.sources.images/ }));
    expect(web.container.querySelectorAll('.aui-global-search-image')).toHaveLength(3);
    h.aui.message = { id: 'web-B', content: [{ type: 'source', citeIndex: 1, toolSign: 'b', isImage: true, title: 'New image', url: 'https://example.com/new.png' }] };
    const nextPayload = openCurrentMessage('b1');
    web.rerender(<SourcesPanel {...nextPayload} selectionToken={nextPayload} open onClose={() => {}} />);
    expect.soft(web.container.querySelectorAll('.aui-global-search-image')).toHaveLength(1);
    expect.soft(within(web.container).queryByText('Web 1')).toBeNull();
    expect.soft(within(web.container).queryByText('Web 2')).toBeNull();
    web.unmount();

    const saved = { type: 'source', isImage: true, title: 'Saved image', url: 'https://example.com/saved.png' };
    const registryOnly = { ...saved, title: 'Registry image', url: 'https://example.com/registry.png' };
    h.aui.message = { id: 'history-images', content: [anchor, saved] };
    const numberedImage = Object.freeze({ type: 'source', citeIndex: 9, toolSign: 'a', isImage: true, title: 'Numbered image', url: 'https://example.com/numbered.png' });
    const registered = Object.freeze([saved, Object.freeze({ ...saved }), registryOnly, numberedImage]);
    h.registered = registered as any;
    const historyPayload = openCurrentMessage('a1');
    expect.soft(historyPayload.images).toHaveLength(3);
    expect(historyPayload.images.map((item: any) => item.title)).toEqual(['Numbered image', 'Saved image', 'Registry image']);
    expect(registered.map((item) => item.title)).toEqual(['Saved image', 'Saved image', 'Registry image', 'Numbered image']);
    expect(registered.every((item) => !('displayIndex' in item))).toBe(true);
    const history = render(<SourcesPanel {...historyPayload} open onClose={() => {}} />);
    fireEvent.click(within(history.container).getByRole('tab', { name: /chat.sources.images/ }));
    expect.soft(history.container.querySelectorAll('.aui-global-search-image')).toHaveLength(3);
    expect.soft(within(history.container).getAllByText('Saved image')).toHaveLength(1);
    expect(within(history.container).getByText('Registry image')).toBeInTheDocument();
    history.unmount();
    h.registered = undefined;

    // Exercise the shared derivation, actual citation action and paginated panel.
    const raw = Array.from({ length: 300 }, (_, index) => Object.freeze({
      type: 'source', sourceType: 'document', citeIndex: index === 100 ? 1 : index + 1,
      toolSign: index === 100 ? 'b' : index === 299 ? 'j' : 'a',
      title: `SOURCE-${index + 1}`,
    }));
    const content = Object.freeze([
      Object.freeze({ type: 'text', text: '[[a1]][[a20]][[a21]][[a100]][[b1]][[j300]]' }),
      ...raw,
    ]);
    h.aui.message = { id: 'sparse-300', content: content as any };
    const sparse = openCurrentMessage('j300');
    expect(sparse.selectedCitationKey).toBe('j300');
    expect(sparse.sources.slice(0, 6).map((item: any) => item.title))
      .toEqual(['SOURCE-1', 'SOURCE-20', 'SOURCE-21', 'SOURCE-100', 'SOURCE-101', 'SOURCE-300']);
    expect(sparse.sources.map((item: any) => item.displayIndex))
      .toEqual(Array.from({ length: 300 }, (_, index) => index + 1));
    const paged = render(<SourcesPanel {...sparse} selectionToken={sparse} open onClose={() => {}} />);
    const pageNumber = () => paged.container.querySelector('aside')?.getAttribute('data-source-page');
    expect(pageNumber()).toBe('1');
    expect(within(paged.container).getByText('SOURCE-300').closest('li')?.className).toContain('border-[#1677ff]');
    const visited: string[] = [];
    for (let page = 1; page <= 15; page++) {
      expect(pageNumber()).toBe(String(page));
      visited.push(...Array.from(paged.container.querySelectorAll('[data-citation-key]'))
        .map((node) => node.getAttribute('data-citation-key')!));
      expect(within(paged.container).getAllByTestId('citation-index-badge').map((node) => Number(node.textContent)))
        .toEqual(Array.from({ length: 20 }, (_, index) => (page - 1) * 20 + index + 1));
      if (page < 15) fireEvent.click(within(paged.container).getByTitle('Next Page'));
    }
    expect(new Set(visited).size).toBe(300);
    const repeated = openCurrentMessage('j300');
    paged.rerender(<SourcesPanel {...repeated} selectionToken={repeated} open onClose={() => {}} />);
    expect(pageNumber()).toBe('1');
    expect(within(paged.container).getByText('SOURCE-300')).toBeInTheDocument();
    // A new immutable streaming snapshot changes numbers and the selected page.
    h.aui.message.content = [
      { type: 'text', text: raw.map((item) => `[[${getCitationKey(item)}]]`).join('') },
      ...raw,
    ];
    const streamed = openCurrentMessage('j300');
    paged.rerender(<SourcesPanel {...streamed} selectionToken={streamed} open onClose={() => {}} />);
    expect(pageNumber()).toBe('15');
    expect(within(paged.container).getByText('SOURCE-300').closest('li')?.className).toContain('border-[#1677ff]');
    expect(content.slice(1)).toEqual(raw);
    expect(raw.every((item, index) => item.citeIndex === (index === 100 ? 1 : index + 1) && !('displayIndex' in item))).toBe(true);
    paged.unmount();

    // Real-message-shaped citation order and an ordinary third-hit-first answer.
    for (const [count, cited] of [[3, [3, 1]], [72, [46, 37, 52, 43, 40, 49]]] as const) {
      h.aui.message = { id: `ordinary-${count}`, content: [
        { type: 'text', text: cited.map((index) => `[[a${index}]]`).join('') },
        ...Array.from({ length: count }, (_, index) => ({ type: 'source', citeIndex: index + 1, toolSign: 'a', title: `Hit ${index + 1}` })),
      ] };
      const ordinary = openCurrentMessage(`a${cited[0]}`);
      expect(ordinary.sources.slice(0, cited.length).map((item: any) => item.citeIndex)).toEqual([...cited]);
    }

    // Legacy numeric resolution must use retrieval order, even after b1 sorts first.
    h.aui.message = { id: 'ambiguous-legacy', content: [
      { type: 'text', text: '[[b1]][[1]][[a1]]' },
      { type: 'source', citeIndex: 1, toolSign: 'a', title: 'Legacy first' },
      { type: 'source', citeIndex: 1, toolSign: 'b', title: 'Other tool' },
    ] };
    const legacy = openCurrentMessage('1');
    expect(legacy.selectedCitationKey).toBe('a1');
    expect(legacy.sources.map((item: any) => getCitationKey(item))).toEqual(['b1', 'a1']);
    expect(legacy.sources.map((item: any) => item.displayIndex)).toEqual([1, 2]);
  });

  it('selects and scrolls to the source matching selectedCitationKey and renders publishedDate', () => {
    const original = HTMLElement.prototype.scrollIntoView;
    const scrollSpy = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollSpy;
    const sources = [
      {
        sourceType: 'url',
        url: 'https://a.example.com',
        title: 'Source A',
        citeIndex: 1,
        toolSign: 'a',
        publishedDate: '2026-01-01',
      },
      {
        sourceType: 'url',
        url: 'https://b.example.com',
        title: 'Source B',
        citeIndex: 1,
        toolSign: 'b',
        publishedDate: '2026-02-02',
      },
    ];
    try {
      render(
        <SourcesPanel
          sources={sources}
          images={[]}
          open
          selectedCitationKey='a1'
          onClose={() => {}}
        />,
      );
      expect(screen.getByText('2026-01-01')).toBeTruthy();
      expect(screen.getByText('2026-02-02')).toBeTruthy();
      expect(scrollSpy).toHaveBeenCalledTimes(1);
    } finally {
      HTMLElement.prototype.scrollIntoView = original;
    }
  });
});

describe('per-hit attributes and safe citation downloads', () => {
  const first = { count: 0, enabled: false, source: 'business source', tags: [0, false, '中文'], standards: { code: { level: 'E' } } };
  const second = { count: 1, enabled: true };
  const sources = [
    { sourceType: 'document' as const, searchType: 'aidp_search', filename: 'same.pdf', title: 'same.pdf', citeIndex: 1, toolSign: 'j', sourceMetadata: first, sourceReference: { chunk_id: 'chunk-first' } },
    { sourceType: 'document' as const, searchType: 'aidp_search', filename: 'same.pdf', title: 'same.pdf', citeIndex: 2, toolSign: 'j', sourceMetadata: second, sourceReference: { chunk_id: 'chunk-second' } },
  ];

  it('keeps same-name hit snapshots distinct from citation click through the real panel', async () => {
    h.aui.message.content = [{ type: 'text', text: 'Answer [[j1]][[j2]]' }, ...sources.map(source => ({ ...source, type: 'source' }))];
    const marker = render(<Cite citekey='j2' />);
    h.citeMarkerProps[0].onClick(null);
    const payload = h.open.mock.calls[0][0];
    expect(payload.selectedCitationKey).toBe('j2');
    expect(payload.sources.map((source: any) => source.sourceMetadata)).toEqual([first, second]);
    expect(payload.sources.map((source: any) => source.sourceReference.chunk_id)).toEqual(['chunk-first', 'chunk-second']);
    marker.unmount();
    const preview = vi.spyOn(window, 'open').mockImplementation(() => null);
    const panel = render(<SourcesPanel sources={payload.sources} images={[]} selectedCitationKey={payload.selectedCitationKey} open onClose={() => {}} />);
    const triggers = within(panel.container).getAllByRole('button', { name: 'chat.sources.showAttributes' });
    fireEvent.mouseEnter(triggers[0]);
    const dialog = await screen.findByRole('dialog', { name: 'chat.sources.attributes' });
    fireEvent.click(triggers[0]);
    fireEvent.mouseLeave(triggers[0]);
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 250)); });
    expect(triggers[0].getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(within(dialog).getByText('tags'));
    await waitFor(() => expect(within(dialog).getAllByText('false')).toHaveLength(2));
    expect(within(dialog).getByText('business source')).toBeTruthy();
    fireEvent.click(within(dialog).getByText('standards'));
    fireEvent.click(await within(dialog).findByText('code'));
    expect(await within(dialog).findByText('E')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('tab', { name: 'chat.sources.rawJson' }));
    expect(JSON.parse(dialog.querySelector('pre')!.textContent!)).toEqual(first);
    expect(within(panel.container).getAllByText('chat.sources.knowledgeBase · AIDP')).toHaveLength(2);
    expect(preview).not.toHaveBeenCalled();
    expect(h.storageDownload).not.toHaveBeenCalled();
    preview.mockRestore();
  });

  it('omits empty attributes and supports focus access to a complete raw snapshot', async () => {
    const panel = render(<SourcesPanel sources={[
      { ...sources[0], sourceMetadata: {} }, { ...sources[1], sourceMetadata: undefined },
      { ...sources[0], citeIndex: 3 },
    ]} images={[]} open onClose={() => {}} />);
    expect(panel.container.querySelectorAll('[data-source-metadata]')).toHaveLength(1);
    const trigger = within(panel.container).getByRole('button', { name: 'chat.sources.showAttributes' });
    fireEvent.focus(trigger);
    const dialog = await screen.findByRole('dialog', { name: 'chat.sources.attributes' });
    fireEvent.click(within(dialog).getByRole('tab', { name: 'chat.sources.rawJson' }));
    expect(JSON.parse(dialog.querySelector('pre')!.textContent!)).toEqual(first);
    fireEvent.keyDown(dialog, { key: 'Escape' });
    await waitFor(() => expect(trigger.getAttribute('aria-expanded')).toBe('false'));
  });

  it('never enables unsupported AIDP citation downloads', () => {
    const panel = render(<SourcesPanel sources={[
      { ...sources[0], url: '/md_image/chunk.png', downloadUrl: 'https://example.com/chunk.pdf', objectName: 'attachments/same.pdf', sourceMetadata: { kds_id: 'kb-business', file_uuid: 'file-id' }, sourceReference: { chunk_id: 'chunk-id' } },
      { ...sources[1], searchType: 'ind_aidp_search', toolSign: 'l', citeIndex: 3, sourceReference: {} },
    ]} images={[]} open onClose={() => {}} />);
    expect(within(panel.container).queryByRole('button', { name: 'chat.sources.download' })).toBeNull();
    expect(h.storageDownload).not.toHaveBeenCalled();
  });

  it('preserves local downloads while AIDP citation downloads remain unsupported', async () => {
    const panel = render(<SourcesPanel sources={[
      { ...sources[0], downloadUrl: 'https://example.com/aidp.pdf', objectName: 'attachments/aidp.pdf' },
      { sourceType: 'document', searchType: 'knowledge_base_search', title: 'local.pdf', filename: 'local.pdf', objectName: 'attachments/local.pdf' },
    ]} images={[]} open onClose={() => {}} />);
    const buttons = within(panel.container).getAllByRole('button', { name: 'chat.sources.download' });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(h.storageDownload).toHaveBeenCalledWith('attachments/local.pdf', 'local.pdf'));
    panel.unmount();

    let failFirst!: (reason: Error) => void;
    h.storageDownload.mockImplementationOnce(() => new Promise<void>((_resolve, reject) => { failFirst = reject; }));
    const firstFile = { sourceType: 'document' as const, searchType: 'knowledge_base_search', citeIndex: 1, toolSign: 'a', title: 'first.pdf', filename: 'first.pdf', objectName: 'attachments/first.pdf' };
    const secondFile = { ...firstFile, title: 'second.pdf', filename: 'second.pdf', objectName: 'attachments/second.pdf' };
    const secondProps = { messageId: 'download-B', sources: [secondFile], images: [], selectedCitationKey: 'a1', open: true, onClose: () => {} };
    const scoped = render(<SourcesPanel {...secondProps} messageId='download-A' sources={[firstFile]} selectionToken={{}} />);
    const button = () => within(scoped.container).getByRole('button', { name: 'chat.sources.download' });
    fireEvent.click(button());
    expect(button()).toBeDisabled();
    scoped.rerender(<SourcesPanel {...secondProps} selectionToken={{}} />);
    expect.soft(button()).toBeEnabled();
    await act(async () => failFirst(new Error('First message download failed')));
    expect.soft(within(scoped.container).queryByText('chat.sources.downloadError')).toBeNull();
    expect(button()).toBeEnabled();

    let finishSecond!: () => void;
    h.storageDownload.mockImplementationOnce(() => new Promise<void>((resolve) => { finishSecond = resolve; }));
    fireEvent.click(button());
    const pendingButton = button();
    expect(pendingButton).toBeDisabled();
    scoped.rerender(<SourcesPanel {...secondProps} selectionToken={{}} />);
    expect(button()).toBe(pendingButton);
    expect(button()).toBeDisabled();
    await act(async () => finishSecond());
    expect(button()).toBeEnabled();

  });
});
