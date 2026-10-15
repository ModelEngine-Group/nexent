import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

import {
  Reasoning,
  extractStepLabel,
  stripStepLabel,
} from '@/app/[locale]/newchat/ui/reasoning';

const auiState = vi.hoisted(() => ({
  state: { part: null as any },
}));

vi.mock('@assistant-ui/react', () => ({
  useAuiState: (selector: (state: any) => any) => selector(auiState.state),
}));

vi.mock('@/lib/utils', () => ({
  cn: (...classes: Array<string | false | null | undefined>) =>
    classes.filter(Boolean).join(' '),
}));

vi.mock('@/app/[locale]/newchat/ui/markdown-text', () => ({
  defaultComponents: {},
}));

vi.mock('@assistant-ui/react-markdown', async () => {
  const ReactMarkdown = (await import('react-markdown')).default;
  return {
    MarkdownTextPrimitive: ({ remarkPlugins, components }: any) => {
      const part = auiState.state.part;
      const text = part?.type === 'reasoning' ? part.text : '';
      return (
        <div data-testid='markdown-text-primitive'>
          <ReactMarkdown remarkPlugins={remarkPlugins} components={components}>
            {text}
          </ReactMarkdown>
        </div>
      );
    },
  };
});

function setReasoningPart(text: string, running: boolean) {
  auiState.state.part = {
    type: 'reasoning',
    text,
    status: { type: running ? 'running' : 'complete' },
  };
}

const CODE_CONTENT = [
  '这是推理过程。',
  '',
  '```python',
  'x = 1',
  'y = 2',
  '```',
  '',
  '行内代码 `inline_code` 以及多行文本。',
  '第二行文本。',
].join('\n');

afterEach(() => {
  cleanup();
  auiState.state.part = null;
});

describe('extractStepLabel / stripStepLabel', () => {
  it('UT-FE-AUTO-86600D51047336D3 extracts a leading **步骤 N** marker', () => {
    expect(extractStepLabel('**步骤 2** 内容')).toBe('步骤 2');
    expect(extractStepLabel('**Step 1** 继续')).toBe('Step 1');
  });

  it('returns undefined without a leading marker', () => {
    expect(extractStepLabel('plain text')).toBeUndefined();
    expect(extractStepLabel('')).toBeUndefined();
    expect(extractStepLabel(undefined)).toBeUndefined();
  });

  it('strips only the leading marker', () => {
    expect(stripStepLabel('**步骤 2** 内容')).toBe('内容');
    expect(stripStepLabel('正文没有标记')).toBe('正文没有标记');
  });
});

describe('StreamingReasoning markdown rendering', () => {
  it('running state keeps fenced code block and inline code intact', () => {
    setReasoningPart(CODE_CONTENT, true);
    const { container } = render(<Reasoning />);

    const text = container.textContent ?? '';
    expect(text).toContain('x = 1');
    expect(text).toContain('y = 2');
    expect(text).toContain('inline_code');
    expect(text).toContain('第二行文本');

    const inlineCode = Array.from(container.querySelectorAll('code')).find(
      (el) => el.textContent?.trim() === 'inline_code',
    );
    expect(inlineCode).toBeDefined();
    expect(inlineCode?.textContent).toBe('inline_code');
  });

  it('non-running state routes through MarkdownTextPrimitive', () => {
    setReasoningPart(CODE_CONTENT, false);
    const { container } = render(<Reasoning />);

    expect(screen.getByTestId('markdown-text-primitive')).toBeInTheDocument();
    expect(container.textContent ?? '').toContain('inline_code');
  });

  it('does not leak raw <code> tags from truncated fragments', () => {
    const truncated = ['开始', '```python', 'x = 1', '', '<code>unclosed'].join('\n');
    setReasoningPart(truncated, true);
    const { container } = render(<Reasoning />);

    expect(container.textContent ?? '').toContain('x = 1');
    expect(container.textContent ?? '').toContain('<code>unclosed');
    expect(container.innerHTML).not.toContain('<code>unclosed');
  });

  it('renders without console errors', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      setReasoningPart(CODE_CONTENT, true);
      render(<Reasoning />);
      expect(errorSpy).not.toHaveBeenCalled();
    } finally {
      errorSpy.mockRestore();
    }
  });
});
