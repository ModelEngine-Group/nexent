import React from 'react';
import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { App } from 'antd';
import EvaluationDetailPage from '@/app/[locale]/evaluation/[id]/page';

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: '42' }),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

const RUN = {
  agent_evaluation_id: 42,
  agent_id: 1,
  agent_name: 'Test Agent',
  status: 'COMPLETED',
  score_overall: 0.8,
  create_time: '2024-01-01T00:00:00.000Z',
  update_time: '2024-01-01T00:01:00.000Z',
  progress_done: 10,
  progress_total: 10,
  annotation_schema_ids: [],
  evaluation_set_name: 'Set',
  judge_model_name: 'Judge',
  evaluator_config: { no_set_mode: false },
};

const STATS = {
  pass_count: 7,
  fail_count: 3,
  total: 10,
  per_evaluator: [],
  histogram: [],
};

function jsonResponse(data, status) {
  const s = status || 200;
  return { ok: s < 400, status: s, json: async () => data };
}

function deferred() {
  let resolve: any;
  let reject: any;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function casesData(items, total) {
  return { data: { items: items || [], total: total } };
}

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: () => ({
      matches: false,
      media: '',
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function installFetch(casesImpl) {
  global.fetch = vi.fn((url, options) => {
    const u = String(url);
    if (u.includes('/cases')) return casesImpl(u, options);
    if (u.includes('/stats')) return Promise.resolve(jsonResponse({ data: STATS }));
    if (u.includes('/evaluators')) return Promise.resolve(jsonResponse({ data: [] }));
    if (u.includes('/evaluation-annotations/schemas')) return Promise.resolve(jsonResponse({ data: [] }));
    if (u.includes('/annotations')) return Promise.resolve(jsonResponse({ data: {} }));
    if (u.includes('/agent-evaluations/')) return Promise.resolve(jsonResponse({ data: RUN }));
    return Promise.reject(new Error('unmocked ' + u));
  });
}

describe('', () => {
  it('UT-FE-AUTO-21C38AB35F467377 shows stats fallback total on the all tab until the cases query resolves, then the current total', async () => {
    const d = deferred();
    installFetch(() => d.promise);
    render(<App><EvaluationDetailPage /></App>);

    await screen.findByRole('tab', { name: /tabAll/ });
    expect(screen.getByRole('tab', { name: /tabAll/ }).textContent).toContain('(10)');

    d.resolve(jsonResponse(casesData([{ agent_evaluation_case_id: 1 }], 25)));
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /tabAll/ }).textContent).toContain('(25)');
    });
  });

  it('falls back to stats passCount while the pass tab loads, then shows the pass total', async () => {
    let passDeferred: any;
    installFetch((u) => {
      if (u.includes('pass_filter=pass')) {
        passDeferred = deferred();
        return passDeferred.promise;
      }
      return Promise.resolve(jsonResponse(casesData([], 10)));
    });

    render(<App><EvaluationDetailPage /></App>);
    await screen.findByRole('tab', { name: /tabAll/ });
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /tabAll/ }).textContent).toContain('(10)');
    });

    fireEvent.click(screen.getByRole('tab', { name: /tabPass/ }));

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /tabPass/ }).textContent).toContain('(7)');
    });

    passDeferred.resolve(jsonResponse(casesData([], 12)));
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /tabPass/ }).textContent).toContain('(12)');
    });
  });

  it('rapid all to pass to fail aborts stale requests and shows the fail total', async () => {
    const d: any = {};
    const signals: any[] = [];
    installFetch((u, options) => {
      signals.push({ url: u, signal: options.signal });
      if (u.includes('pass_filter=fail')) {
        d.fail = deferred();
        return d.fail.promise;
      }
      if (u.includes('pass_filter=pass')) {
        d.pass = deferred();
        return d.pass.promise;
      }
      d.all = deferred();
      return d.all.promise;
    });

    render(<App><EvaluationDetailPage /></App>);
    await screen.findByRole('tab', { name: /tabAll/ });

    fireEvent.click(screen.getByRole('tab', { name: /tabPass/ }));
    fireEvent.click(screen.getByRole('tab', { name: /tabFail/ }));

    const allCall = signals.find((s) => !s.url.includes('pass_filter'));
    const passCall = signals.find((s) => s.url.includes('pass_filter=pass'));
    const failCall = signals.find((s) => s.url.includes('pass_filter=fail'));
    expect(allCall.signal.aborted).toBe(true);
    expect(passCall.signal.aborted).toBe(true);
    expect(failCall.signal.aborted).toBe(false);

    d.fail.resolve(jsonResponse(casesData([], 20)));
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /tabFail/ }).textContent).toContain('(20)');
      expect(screen.getByRole('tab', { name: /tabPass/ }).textContent).toContain('(7)');
      expect(screen.getByRole('tab', { name: /tabAll/ }).textContent).toContain('(10)');
    });
  });

  it('resets the total query key on remount so a stale total does not leak', async () => {
    const first = deferred();
    installFetch(() => first.promise);
    const view = render(<App><EvaluationDetailPage /></App>);
    await screen.findByRole('tab', { name: /tabAll/ });
    first.resolve(jsonResponse(casesData([], 25)));
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /tabAll/ }).textContent).toContain('(25)');
    });

    view.unmount();

    const second = deferred();
    installFetch(() => second.promise);
    render(<App><EvaluationDetailPage /></App>);
    await screen.findByRole('tab', { name: /tabAll/ });
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /tabAll/ }).textContent).toContain('(10)');
    });
  });
});
