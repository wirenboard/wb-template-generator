import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Тестируем НАСТОЯЩИЙ api.ts (глобальный setup мокает '../api' — обходим через importActual).
// Форма анализа собирается общим маппингом имён, лимит токенов добавляется отдельно.

let api: typeof import('../api');

beforeEach(async () => {
  api = await vi.importActual<typeof import('../api')>('../api');
});

afterEach(() => {
  vi.restoreAllMocks();
});

function stubSse() {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    body: { getReader: () => ({ read: async () => ({ done: true, value: undefined }) }) },
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function callbacks() {
  return { onProgress: vi.fn(), onResult: vi.fn(), onError: vi.fn(), onDone: vi.fn() };
}

async function sentForm(llm?: Parameters<typeof api.analyzeFiles>[1]['llm']): Promise<FormData> {
  const fetchMock = stubSse();
  await api.analyzeFiles([], { templateType: 'full', llm }, callbacks());
  return fetchMock.mock.calls[0][1].body as FormData;
}

describe('analyzeFiles: настройки LLM в multipart', () => {
  it('поля уходят в именах бэкенда', async () => {
    const form = await sentForm({
      apiUrl: 'https://user.example/v1',
      apiKey: 'sk-user',
      model: 'local-model',
      timeout: 42,
    });

    expect(form.get('llm_api_url')).toBe('https://user.example/v1');
    expect(form.get('llm_api_key')).toBe('sk-user');
    expect(form.get('llm_model')).toBe('local-model');
    expect(form.get('llm_timeout')).toBe('42');
  });

  it('лимит токенов принимает только анализ, и он доходит', async () => {
    const form = await sentForm({ maxTokens: 8192 });

    expect(form.get('llm_max_tokens')).toBe('8192');
  });

  it('ноль и false значимы — не теряются как falsy', async () => {
    const form = await sentForm({ temperature: 0, legacyMaxTokens: false });

    expect(form.get('llm_temperature')).toBe('0');
    expect(form.get('llm_legacy_max_tokens')).toBe('false');
  });

  it('незаданное не отправляется — сервер подставит свою настройку', async () => {
    const form = await sentForm({ model: 'only-model' });

    expect(form.get('llm_model')).toBe('only-model');
    expect(form.has('llm_api_url')).toBe(false);
    expect(form.has('llm_temperature')).toBe(false);
    expect(form.has('llm_max_tokens')).toBe(false);
  });

  it('без настроек LLM полей нет вовсе', async () => {
    const form = await sentForm();

    expect(form.get('template_type')).toBe('full');
    expect([...form.keys()].filter((k) => k.startsWith('llm_'))).toEqual([]);
  });
});
