import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { resetMocks } from './setup';

// Тестируем настоящий api.ts: глобальный setup мокает '../api'
let api: typeof import('../api');

beforeEach(async () => {
  resetMocks();
  api = await vi.importActual<typeof import('../api')>('../api');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('getClientId', () => {
  it('один и тот же между вызовами — иначе каждый запрос считался бы новым браузером', () => {
    const first = api.getClientId();
    expect(first).toBeTruthy();
    expect(api.getClientId()).toBe(first);
    expect(localStorage.getItem('wb-template-client-id')).toBe(first);
  });
});

describe('trackUsage', () => {
  it('шлёт событие с идентификатором браузера', () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));

    api.trackUsage('download_json');

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/usage');
    expect(JSON.parse(init!.body as string)).toEqual({ event: 'download_json' });
    expect((init!.headers as Record<string, string>)['X-Client-Id']).toBe(api.getClientId());
  });

  it('сбой сети не выходит наружу', async () => {
    // Необработанный отказ vitest засчитал бы как ошибку прогона
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('offline'));

    expect(() => api.trackUsage('page_open')).not.toThrow();
    await new Promise((r) => setTimeout(r, 0));
  });
});
