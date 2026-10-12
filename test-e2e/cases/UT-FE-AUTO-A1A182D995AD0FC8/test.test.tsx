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

describe('citation click-highlight feature gate', () => {
  it('UT-FE-AUTO-A1A182D995AD0FC8 preserves citation selection while gating sentence context', () => {
    h.aui.message.content = [
      { type: 'text', text: 'First sentence. Highlight this sentence[[a1]]' },
      { type: 'source', citeIndex: 1, toolSign: 'a', title: 'Source A' },
    ];

    h.citation.enabled = false;
    const first = render(<Cite citekey='a1' />);
    h.citeMarkerProps[0].onClick(null);
    expect(h.open.mock.calls[0][0].selectedCitationKey).toBe('a1');
    expect(h.open.mock.calls[0][0].citationContext).toBeUndefined();
    first.unmount();

    h.open.mockClear();
    h.citeMarkerProps.length = 0;
    h.citation.enabled = true;
    render(<Cite citekey='a1' />);
    h.citeMarkerProps[0].onClick(null);
    expect(h.open.mock.calls[0][0].selectedCitationKey).toBe('a1');
    expect(h.open.mock.calls[0][0].citationContext).toBe('Highlight this sentence');
  });
});
