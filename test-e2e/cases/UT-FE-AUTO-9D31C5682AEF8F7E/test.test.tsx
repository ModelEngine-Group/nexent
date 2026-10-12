import React from 'react';
import { render, cleanup, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { formatKnowledgeBaseDeleteError } from '@/lib/knowledgeBaseDeleteError';
import { ErrorCode } from '@/const/errorCode';
import {
  KnowledgeBaseProvider,
  useKnowledgeBaseContext,
} from '@/app/[locale]/knowledges/contexts/KnowledgeBaseContext';
import knowledgeBaseService from '@/services/knowledgeBaseService';

vi.mock('@/services/knowledgeBaseService', () => ({
  default: {
    getKnowledgeBasesInfo: vi.fn(),
    getAllFiles: vi.fn(),
    createKnowledgeBase: vi.fn(),
    deleteKnowledgeBase: vi.fn(),
  },
}));

vi.mock('@/hooks/useConfig', () => ({
  useConfig: () => ({
    appConfig: { datamateUrl: null },
    modelConfig: {
      embedding: { displayName: '' },
      multiEmbedding: { displayName: '' },
    },
  }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/lib/logger', () => ({
  default: {
    debug: () => {},
    info: () => {},
    warn: () => {},
    error: () => {},
    log: () => {},
  },
}));

const mockDelete = knowledgeBaseService.deleteKnowledgeBase as unknown as {
  mockReset: () => void;
  mockRejectedValueOnce: (value: unknown) => void;
  mockResolvedValueOnce: (value: unknown) => void;
};

let captured: {
  deleteKnowledgeBase: (id: string) => Promise<boolean>;
  state: any;
} | null = null;

function Capture() {
  const { deleteKnowledgeBase, state } = useKnowledgeBaseContext();
  captured = { deleteKnowledgeBase, state };
  return null;
}

function renderHarness() {
  captured = null;
  render(
    React.createElement(
      KnowledgeBaseProvider,
      null,
      React.createElement(Capture)
    )
  );
  return captured!;
}

const FALLBACK_KEY = 'knowledgeBase.message.deleteError';

beforeEach(() => {
  vi.resetAllMocks();
  captured = null;
});

afterEach(() => {
  cleanup();
});

describe('formatKnowledgeBaseDeleteError', () => {
  it('UT-FE-AUTO-9D31C5682AEF8F7E formats KNOWLEDGE_DELETE_BLOCKED with per-file name/status labels', () => {
    const t = vi.fn((key: string, options?: Record<string, unknown>) =>
      options && typeof options.files === 'string'
        ? `${key}|${options.files}`
        : key
    );
    const error = {
      code: ErrorCode.KNOWLEDGE_DELETE_BLOCKED,
      details: {
        blocking_files: [
          { file_name: 'a.txt', status: 'READY' },
          { file_name: 'b.pdf', status: 'PROCESSING' },
        ],
      },
    };

    const result = formatKnowledgeBaseDeleteError(error, t, FALLBACK_KEY);

    expect(t).toHaveBeenCalledWith(
      'knowledgeBase.message.deleteBlockedWithFiles',
      { files: 'a.txt (READY), b.pdf (PROCESSING)' }
    );
    expect(result).toBe(
      'knowledgeBase.message.deleteBlockedWithFiles|a.txt (READY), b.pdf (PROCESSING)'
    );
  });

  it('renders a bare file name when status is empty', () => {
    const t = vi.fn((key: string, options?: Record<string, unknown>) =>
      options && typeof options.files === 'string'
        ? `${key}|${options.files}`
        : key
    );
    const error = {
      code: ErrorCode.KNOWLEDGE_DELETE_BLOCKED,
      details: { blocking_files: [{ file_name: 'c.md', status: '' }] },
    };

    const result = formatKnowledgeBaseDeleteError(error, t, FALLBACK_KEY);

    expect(result).toBe('knowledgeBase.message.deleteBlockedWithFiles|c.md');
  });

  it('falls back to deleteBlocked when blocking_files is missing', () => {
    const t = vi.fn((key: string) => key);
    const error = { code: ErrorCode.KNOWLEDGE_DELETE_BLOCKED, details: {} };

    expect(formatKnowledgeBaseDeleteError(error, t, FALLBACK_KEY)).toBe(
      'knowledgeBase.message.deleteBlocked'
    );
  });

  it('falls back to deleteBlocked when error has no details', () => {
    const t = vi.fn((key: string) => key);
    const error = { code: ErrorCode.KNOWLEDGE_DELETE_BLOCKED };

    expect(formatKnowledgeBaseDeleteError(error, t, FALLBACK_KEY)).toBe(
      'knowledgeBase.message.deleteBlocked'
    );
  });

  it('falls back to deleteBlocked when blocking_files is an empty array', () => {
    const t = vi.fn((key: string) => key);
    const error = {
      code: ErrorCode.KNOWLEDGE_DELETE_BLOCKED,
      details: { blocking_files: [] },
    };

    expect(formatKnowledgeBaseDeleteError(error, t, FALLBACK_KEY)).toBe(
      'knowledgeBase.message.deleteBlocked'
    );
  });

  it('falls back to deleteBlocked when all files have empty file_name', () => {
    const t = vi.fn((key: string) => key);
    const error = {
      code: ErrorCode.KNOWLEDGE_DELETE_BLOCKED,
      details: {
        blocking_files: [{ file_name: '' }, { file_name: '   ' }],
      },
    };

    expect(formatKnowledgeBaseDeleteError(error, t, FALLBACK_KEY)).toBe(
      'knowledgeBase.message.deleteBlocked'
    );
  });

  it('returns error.message for a non-blocked Error instance', () => {
    const t = vi.fn((key: string) => key);
    const error = new Error('raw deletion failed');

    expect(formatKnowledgeBaseDeleteError(error, t, FALLBACK_KEY)).toBe(
      'raw deletion failed'
    );
  });

  it('returns error.message for an Error carrying a different EDS code', () => {
    const t = vi.fn((key: string) => key);
    const error = Object.assign(new Error('other failure'), { code: '000101' });

    expect(formatKnowledgeBaseDeleteError(error, t, FALLBACK_KEY)).toBe(
      'other failure'
    );
  });

  it('returns fallbackKey for an input with no code and no message', () => {
    const t = vi.fn((key: string) => key);

    expect(formatKnowledgeBaseDeleteError({}, t, FALLBACK_KEY)).toBe(
      FALLBACK_KEY
    );
    expect(formatKnowledgeBaseDeleteError(null, t, FALLBACK_KEY)).toBe(
      FALLBACK_KEY
    );
    expect(formatKnowledgeBaseDeleteError('text', t, FALLBACK_KEY)).toBe(
      FALLBACK_KEY
    );
  });

  it('returns fallbackKey for an Error with an empty message', () => {
    const t = vi.fn((key: string) => key);
    const error = new Error('');

    expect(formatKnowledgeBaseDeleteError(error, t, FALLBACK_KEY)).toBe(
      FALLBACK_KEY
    );
  });
});

describe('deleteKnowledgeBase', () => {
  it('rethrows the original EDS error preserving code/details and dispatches ERROR', async () => {
    const edsError = {
      code: ErrorCode.KNOWLEDGE_DELETE_BLOCKED,
      details: {
        blocking_files: [{ file_name: 'report.pdf', status: 'LOCKED' }],
      },
      message: 'cannot delete',
    };
    mockDelete.mockRejectedValueOnce(edsError);

    const api = renderHarness();

    let caught: unknown;
    await act(async () => {
      try {
        await api.deleteKnowledgeBase('kb-1');
      } catch (error) {
        caught = error;
      }
    });

    expect(caught).toBe(edsError);
    expect(caught).toMatchObject({ code: ErrorCode.KNOWLEDGE_DELETE_BLOCKED });
    expect(
      (caught as { details: { blocking_files: unknown[] } }).details
        .blocking_files
    ).toHaveLength(1);
    expect(mockDelete).toHaveBeenCalledWith('kb-1');
    expect(captured?.state.error).toBe('knowledgeBase.error.deleteRetry');
  });

  it('returns true on success without swallowing into a fake success', async () => {
    mockDelete.mockResolvedValueOnce(undefined);

    const api = renderHarness();

    let result: boolean | undefined;
    await act(async () => {
      result = await api.deleteKnowledgeBase('kb-1');
    });

    expect(result).toBe(true);
    expect(mockDelete).toHaveBeenCalledWith('kb-1');
    expect(captured?.state.error).toBe(null);
  });
});
