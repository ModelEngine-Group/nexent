import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

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
  storageService: { downloadFileWithAuth: () => Promise.resolve() },
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
  h.citation.enabled = false;
  h.aui.message.id = 'msg-1';
  h.aui.message.content = [];
  h.open.mockClear();
  h.citeMarkerProps.length = 0;
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
