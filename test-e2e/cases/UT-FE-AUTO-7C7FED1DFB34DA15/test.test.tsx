import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';

vi.mock('@/lib/utils', () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(' '),
  formatDate: (d: unknown) => (d ? String(d) : ''),
  formatUrl: (r: any) => (r && r.url ? r.url : ''),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/hooks/useConfig', () => ({
  useConfig: () => ({ appConfig: null }),
}));

vi.mock('@/services/storageService', () => ({
  extractObjectNameFromUrl: () => null,
  storageService: {
    downloadFile: vi.fn(),
    downloadDatamateFile: vi.fn(),
  },
  fetchImageBlob: vi.fn(),
}));

vi.mock('@/lib/logger', () => ({
  default: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    log: vi.fn(),
  },
}));

vi.mock('@/app/i18n', () => ({
  default: { language: 'en', t: (key: string) => key },
  resourcesCustom: {},
}));

vi.mock('antd', async () => {
  const React = await import('react');
  return {
    message: { error: vi.fn(), success: vi.fn() },
    Button: ({ children, ...props }: any) =>
      React.createElement('button', props, children),
  };
});

import {
  escapeRegExp,
  normalizeForHighlight,
  mergeHighlightTerms,
  extractHighlightTerms,
  splitSourceTextIntoSentences,
} from '@/lib/citationHighlight';
import { CiteIndexBadge, HighlightedChunkText } from '@/components/common/highlightedSourceText';
import { ChatRightPanel } from '@/app/[locale]/chat/components/chatRightPanel';
import { ENABLE_CITATION_CLICK_HIGHLIGHT } from '@/const/citation';
import type { ChatMessageType } from '@/types/chat';

const noop = () => {};

function buildMessage(): ChatMessageType {
  return {
    id: 'm1',
    role: 'assistant',
    content: '答案 [[a1]]',
    finalAnswer: '这是包含 [[a1]] 引用标记的回答文本。',
    searchResults: [
      {
        title: '来源 A',
        url: 'https://example.com/a',
        text: '这是一个包含检索词的内容段落。',
        published_date: '',
        source_type: 'url',
        tool_sign: 'a',
        cite_index: 1,
        score_details: { retrieval_highlight_terms: ['检索词'] },
      },
      {
        title: '来源 B',
        url: 'https://example.com/b',
        text: '另一段无关内容。',
        published_date: '',
        source_type: 'url',
        tool_sign: 'b',
        cite_index: 2,
      },
    ],
  };
}

let scrollSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  scrollSpy = vi.fn();
  HTMLElement.prototype.scrollIntoView = scrollSpy as any;
});

afterEach(() => {
  cleanup();
});

describe('citationHighlight 检索高亮公共函数', () => {
  it('UT-FE-AUTO-7C7FED1DFB34DA15 转义正则特殊字符', () => {
    expect(escapeRegExp('plain')).toBe('plain');
    const escaped = escapeRegExp('.');
    expect(escaped).toHaveLength(2);
    expect(escaped.endsWith('.')).toBe(true);
  });

  it('归一化为小写', () => {
    expect(normalizeForHighlight('ABC')).toBe('abc');
  });

  it('合并去重并丢弃子串', () => {
    expect(mergeHighlightTerms(['abc', 'abcdef', 'x', 'abc'])).toEqual([
      'abcdef',
      'x',
    ]);
  });

  it('过滤短于阈值或不在来源中的词', () => {
    expect(extractHighlightTerms('', '文本')).toEqual([]);
    expect(extractHighlightTerms('不存在的短语', '这是内容')).toEqual([]);
    expect(extractHighlightTerms('检索', '检索')).toEqual([]);
  });

  it('提取出现在来源中的中文检索词', () => {
    expect(extractHighlightTerms('检索词', '这是一个包含检索词的内容段落。')).toEqual([
      '检索词',
    ]);
  });

  it('按句子切分来源文本', () => {
    expect(splitSourceTextIntoSentences('第一句。第二句！')).toEqual([
      '第一句。',
      '第二句！',
    ]);
  });
});

describe('HighlightedChunkText 高亮渲染', () => {
  it('将匹配句子渲染为 mark', () => {
    const { container } = render(
      <HighlightedChunkText text={'包含检索词的句子。另一句。'} terms={['检索词']} />
    );
    const mark = container.querySelector('mark');
    expect(mark).not.toBeNull();
    expect(mark?.textContent).toContain('检索词');
  });

  it('无检索词时不渲染 mark', () => {
    const { container } = render(
      <HighlightedChunkText text={'普通文本。'} terms={[]} />
    );
    expect(container.querySelector('mark')).toBeNull();
    expect(container.textContent).toContain('普通文本');
  });

  it('检索词不在来源中时不渲染 mark', () => {
    const { container } = render(
      <HighlightedChunkText text={'普通文本。'} terms={['不存在的词']} />
    );
    expect(container.querySelector('mark')).toBeNull();
  });
});

describe('CiteIndexBadge 引用索引徽标', () => {
  it('有限索引渲染数字', () => {
    const { container } = render(<CiteIndexBadge index={1} />);
    expect(container.textContent).toContain('1');
  });

  it('非有限索引返回 null', () => {
    const { container } = render(<CiteIndexBadge index={undefined} />);
    expect(container.textContent).toBe('');
  });
});

describe('ChatRightPanel 引用点击定位与高亮', () => {
  it('默认折叠且无来源卡选中', () => {
    const { container } = render(
      <ChatRightPanel
        messages={[buildMessage()]}
        onImageError={noop}
        isVisible={false}
        selectedMessageId={'m1'}
      />
    );
    expect(container.querySelectorAll('.border-blue-300')).toHaveLength(0);
    expect(container.querySelector('mark')).toBeNull();
    expect(container.textContent).toContain('来源 A');
    expect(container.textContent).toContain('来源 B');
    expect(container.firstElementChild?.className).toContain('opacity-0');
  });

  it('选中来源卡进入蓝色边框、滚动定位并高亮检索词', () => {
    const { container } = render(
      <ChatRightPanel
        messages={[buildMessage()]}
        onImageError={noop}
        isVisible
        selectedMessageId={'m1'}
        selectedCitationKey={'a1'}
        selectedCitationContext={''}
      />
    );
    const selected = container.querySelectorAll('.border-blue-300');
    expect(selected).toHaveLength(1);
    expect(selected[0].textContent).toContain('来源 A');
    expect(selected[0].textContent).not.toContain('来源 B');
    const mark = container.querySelector('mark');
    expect(mark).not.toBeNull();
    expect(mark?.textContent).toContain('检索词');
    expect(scrollSpy).toHaveBeenCalledWith(
      expect.objectContaining({ block: 'center' })
    );
  });

  it('过滤短于 2 字符的检索高亮词', () => {
    const msg = buildMessage();
    msg.searchResults = [
      {
        title: '来源 A',
        url: 'https://example.com/a',
        text: '检验内容。',
        published_date: '',
        source_type: 'url',
        tool_sign: 'a',
        cite_index: 1,
        score_details: { retrieval_highlight_terms: ['检'] },
      },
    ];
    const { container } = render(
      <ChatRightPanel
        messages={[msg]}
        onImageError={noop}
        isVisible
        selectedMessageId={'m1'}
        selectedCitationKey={'a1'}
        selectedCitationContext={''}
      />
    );
    expect(container.querySelector('.border-blue-300')).not.toBeNull();
    expect(container.querySelector('mark')).toBeNull();
  });
});

describe('ENABLE_CITATION_CLICK_HIGHLIGHT 开关', () => {
  it('默认关闭，仅定位不高亮', () => {
    expect(ENABLE_CITATION_CLICK_HIGHLIGHT).toBe(false);
  });
});
