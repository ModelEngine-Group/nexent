// Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

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
  aidpDownload: vi.fn(),
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

vi.mock('@/ext_components/aidp/shared/services/aidpKnowledgeService', () => ({
  default: { downloadDoc: h.aidpDownload },
}));

vi.mock('@assistant-ui/react-markdown', () => ({
  unstable_memoizeMarkdownComponents: (c: any) => c,
  MarkdownTextPrimitive: () => null,
  useIsMarkdownCodeBlock: () => false,
}));

vi.mock('@assistant-ui/react', () => ({
  useAuiState: (selector: (s: any) => any) => selector(h.aui),
}));

vi.mock('@/app/[locale]/newchat/ui/sources-panel-context', () => ({
  useSourcesPanel: () => ({ open: h.open }),
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
  conversationSourcesRegistry: { get: () => undefined },
}));

vi.mock('@/components/ui/button', () => ({
  Button: () => null,
}));

vi.mock('@/components/common/highlightedSourceText', () => ({
  CiteIndexBadge: () => null,
  HighlightedChunkText: () => null,
}));

vi.mock('@/lib/citationHighlight', () => ({
  extractHighlightTerms: () => [],
  mergeHighlightTerms: (a: any[], b: any[]) => [...(a ?? []), ...(b ?? [])],
}));

const Cite = defaultComponents.cite as unknown as (props: {
  citekey?: string;
}) => any;

beforeEach(() => {
  HTMLElement.prototype.scrollIntoView = vi.fn();
  h.citation.enabled = false;
  h.aui.message.id = 'msg-1';
  h.aui.message.content = [];
  h.open.mockClear();
  h.citeMarkerProps.length = 0;
  h.storageDownload.mockReset().mockResolvedValue(undefined);
  h.aidpDownload.mockReset().mockResolvedValue({ blob: async () => new Blob(['mock sample']) });
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
    expect(within(dialog).getAllByText('false')).toHaveLength(2);
    expect(within(dialog).getByText('business source')).toBeTruthy();
    fireEvent.click(within(dialog).getByText('standards'));
    fireEvent.click(within(dialog).getByText('code'));
    expect(within(dialog).getByText('E')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('tab', { name: 'chat.sources.rawJson' }));
    expect(JSON.parse(dialog.querySelector('pre')!.textContent!)).toEqual(first);
    expect(within(panel.container).getAllByText('chat.sources.knowledgeBase · AIDP')).toHaveLength(2);
    expect(preview).not.toHaveBeenCalled();
    expect(h.storageDownload).not.toHaveBeenCalled();
    expect(h.aidpDownload).not.toHaveBeenCalled();
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

  it('never enables AIDP downloads from names, business metadata, chunk IDs or image URLs', () => {
    const uuid = '12345678-1234-1234-1234-123456789abc';
    const panel = render(<SourcesPanel sources={[
      { ...sources[0], url: '/md_image/chunk.png', downloadUrl: 'https://example.com/chunk.pdf', objectName: 'attachments/same.pdf', sourceMetadata: { kds_id: 'kb-business', file_uuid: uuid }, sourceReference: { chunk_id: uuid } },
      { ...sources[1], sourceReference: { download_locator: { provider: 'aidp', kds_id: 'kb-explicit', file_uuid: 'chunk-2' } } },
      { ...sources[0], searchType: undefined, citeIndex: 3, url: 'https://example.com/image.png', sourceReference: {} },
      { ...sources[0], searchType: 'ind_aidp_search', toolSign: 'l', citeIndex: 1, sourceReference: { download_locator: { provider: 'aidp', kds_id: 'kb-explicit', file_uuid: uuid } } },
    ]} images={[]} open onClose={() => {}} />);
    expect(within(panel.container).queryByRole('button', { name: 'chat.sources.download' })).toBeNull();
    expect(h.storageDownload).not.toHaveBeenCalled();
    expect(h.aidpDownload).not.toHaveBeenCalled();
  });

  it('uses the existing AIDP proxy for explicit locators and preserves local downloads', async () => {
    const uuid = '12345678-1234-1234-1234-123456789abc';
    const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => 'blob:unit-download');
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    try {
      const panel = render(<SourcesPanel sources={[
        { ...sources[0], sourceReference: { download_locator: { provider: 'aidp', kds_id: 'kb-explicit', file_uuid: uuid } } },
        { sourceType: 'document', searchType: 'knowledge_base_search', title: 'local.pdf', filename: 'local.pdf', objectName: 'attachments/local.pdf' },
      ]} images={[]} open onClose={() => {}} />);
      const buttons = within(panel.container).getAllByRole('button', { name: 'chat.sources.download' });
      fireEvent.click(buttons[0]);
      await waitFor(() => expect(h.aidpDownload).toHaveBeenCalledWith('kb-explicit', uuid));
      expect(h.storageDownload).not.toHaveBeenCalled();
      await waitFor(() => expect(click).toHaveBeenCalledOnce());
      fireEvent.click(buttons[1]);
      await waitFor(() => expect(h.storageDownload).toHaveBeenCalledWith('attachments/local.pdf', 'local.pdf'));
      expect(h.aidpDownload).toHaveBeenCalledOnce();
      h.aidpDownload.mockRejectedValueOnce(new Error('AIDP file unavailable'));
      fireEvent.click(buttons[0]);
      await screen.findByText('chat.sources.downloadError');
      expect(h.storageDownload).toHaveBeenCalledOnce();
      fireEvent.click(buttons[0]);
      await waitFor(() => expect(h.aidpDownload).toHaveBeenCalledTimes(3));
      await waitFor(() => expect(within(panel.container).queryByText('chat.sources.downloadError')).toBeNull());
    } finally { click.mockRestore(); URL.createObjectURL = create; URL.revokeObjectURL = revoke; }
  });
});
