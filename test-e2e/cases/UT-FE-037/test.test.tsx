import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchWithAuth, getAuthHeaders } from '@/lib/auth';
import { ApiError } from '@/services/api';
import { ErrorCode } from '@/const/errorCode';

const session = vi.hoisted(() => ({ hasCookies: true, valid: true, expired: vi.fn() }));
vi.mock('@/lib/session', () => ({
  hasAuthCookies: () => session.hasCookies, checkSessionValid: () => session.valid,
  handleSessionExpired: session.expired,
}));
vi.mock('@/lib/authFlow', () => ({ authFlowState: { isExplicitLogoutInProgress: () => false } }));
beforeEach(() => { session.valid = true; session.hasCookies = true; session.expired.mockClear(); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe('UT-FE-037 current cookie authentication boundary', () => {
  it('does not read browser JWT or inject Authorization and preserves caller headers/signal', async () => {
    const read = vi.spyOn(Storage.prototype, 'getItem');
    const request = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', request);
    const abort = new AbortController();
    await fetchWithAuth('/api/test-fixture', { method: 'POST', body: '{}', signal: abort.signal, headers: { 'X-Test': 'fixture' } });
    expect(request).toHaveBeenCalledOnce();
    expect(request.mock.calls[0][1]).toMatchObject({ signal: abort.signal, headers: { 'Content-Type': 'application/json', 'X-Test': 'fixture' } });
    expect(request.mock.calls[0][1].headers).not.toHaveProperty('Authorization');
    expect(getAuthHeaders()).not.toHaveProperty('Authorization');
    expect(read).not.toHaveBeenCalled();
  });
  it('local expiry prevents request and signals forced login', async () => {
    session.valid = false;
    const request = vi.fn(); vi.stubGlobal('fetch', request);
    await expect(fetchWithAuth('/api/test-fixture')).rejects.toBeInstanceOf(ApiError);
    expect(request).not.toHaveBeenCalled(); expect(session.expired).toHaveBeenCalledOnce();
  });
  it.each([401, 499])('HTTP %s signals expiry without hidden refresh/retry', async status => {
    const request = vi.fn().mockResolvedValue(new Response('{}', { status }));
    vi.stubGlobal('fetch', request);
    await expect(fetchWithAuth('/api/test-fixture')).rejects.toBeInstanceOf(ApiError);
    expect(session.expired).toHaveBeenCalledOnce(); expect(request).toHaveBeenCalledOnce();
  });
  it('business TOKEN_EXPIRED preserves structured details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: {
      code: ErrorCode.TOKEN_EXPIRED, message: 'Expired fixture session', details: { recover: 'login' },
    } }), { status: 400 })));
    await expect(fetchWithAuth('/api/test-fixture')).rejects.toMatchObject({ code: ErrorCode.TOKEN_EXPIRED, details: { recover: 'login' } });
    expect(session.expired).toHaveBeenCalledOnce();
  });
  it('cancellation remains AbortError and does not expire the session', async () => {
    const request = vi.fn((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal!.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')), { once: true });
    }));
    vi.stubGlobal('fetch', request);
    const abort = new AbortController();
    const pending = fetchWithAuth('/api/test-fixture', { signal: abort.signal });
    const rejection = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    abort.abort(); await rejection;
    expect(session.expired).not.toHaveBeenCalled(); expect(request).toHaveBeenCalledOnce();
  });
  it('FormData leaves the multipart boundary to the browser', async () => {
    const request = vi.fn().mockResolvedValue(new Response('{}')); vi.stubGlobal('fetch', request);
    await fetchWithAuth('/api/test-fixture', { method: 'POST', body: new FormData() });
    expect(request.mock.calls[0][1].headers).not.toHaveProperty('Content-Type');
  });
});
