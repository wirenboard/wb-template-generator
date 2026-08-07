import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useStore } from '../store';
import translations from '../i18n/translations';

// Тестируем НАСТОЯЩИЙ api.ts (глобальный setup мокает '../api' — обходим через importActual).
// Ошибки бэкенда приходят ключом (message_key + message_params), интерфейс на
// четырёх языках рендерит их сам. Русский detail — фолбек для незнакомых ключей.

let api: typeof import('../api');

beforeEach(async () => {
  api = await vi.importActual<typeof import('../api')>('../api');
});

afterEach(() => {
  vi.restoreAllMocks();
});

function stubFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));
}

describe('importTemplate: ошибка приходит ключом', () => {
  it('ключ переводится на язык интерфейса, а не берётся русский detail', async () => {
    useStore.setState({ uiLocale: 'en' });
    stubFetch({
      ok: false,
      status: 400,
      json: async () => ({
        detail: 'Файл не похож на шаблон wb-mqtt-serial: не найдены каналы, параметры или тип устройства.',
        message_key: 'serverError.importNotTemplate',
        message_params: {},
      }),
    });

    await expect(api.importTemplate(new File(['{}'], 't.json'))).rejects.toThrow(
      translations.en['serverError.importNotTemplate'],
    );
  });

  it('422 от pydantic (detail — массив) даёт фолбек с кодом, а не [object Object]', async () => {
    useStore.setState({ uiLocale: 'ru' });
    stubFetch({
      ok: false,
      status: 422,
      json: async () => ({ detail: [{ loc: ['body', 'file'], msg: 'field required' }] }),
    });

    await expect(api.importTemplate(new File(['{}'], 't.json'))).rejects.toThrow(/422/);
  });
});

describe('resolveMessage: ключ вместо русской прозы', () => {
  beforeEach(() => {
    useStore.setState({ uiLocale: 'en' });
  });

  it('подставляет параметры в переведённую фразу', () => {
    const result = api.resolveMessage(
      { message_key: 'serverError.importJinjaTooLarge', message_params: { max: 512 } },
      'русский фолбек',
    );

    expect(result).toBe(translations.en['serverError.importJinjaTooLarge'].replace('{max}', '512'));
  });

  it('номер строки и текст jinja2 доходят до автора шаблона', () => {
    const result = api.resolveMessage(
      {
        message_key: 'serverError.importJinjaErrorLine',
        message_params: { line: 7, error: 'Unexpected end of template' },
      },
      'фолбек',
    );

    expect(result).toContain('7');
    expect(result).toContain('Unexpected end of template');
  });

  it('незнакомый ключ — показываем текст бэкенда, а не сам ключ', () => {
    const result = api.resolveMessage(
      { message_key: 'serverError.fromFutureVersion', message_params: {} },
      'Текст с сервера',
    );

    expect(result).toBe('Текст с сервера');
  });

  it('ответа без ключа достаточно старого detail', () => {
    expect(api.resolveMessage({}, 'Текст с сервера')).toBe('Текст с сервера');
  });
});

// Ключ приезжает со всех маршрутов, а не только с импорта шаблона. Вместе с ним
// доезжает номер запроса — раньше обёртка анализа тело ответа вообще не читала,
// поэтому и текст отказа, и номер терялись.
describe('остальные маршруты: ключ и номер запроса', () => {
  function analyzeCallbacks() {
    return {
      onProgress: vi.fn(), onResult: vi.fn(), onError: vi.fn(), onDone: vi.fn(),
    };
  }

  it('analyzeFiles: отказ до потока переводится и приносит request_id', async () => {
    useStore.setState({ uiLocale: 'en' });
    stubFetch({
      ok: false,
      status: 429,
      json: async () => ({
        detail: 'Превышен лимит запросов (10 за 60 сек). Попробуйте позже.',
        message_key: 'serverError.rateLimit',
        message_params: { requests: 10, window: 60 },
        request_id: 'req-42',
      }),
    });
    const cb = analyzeCallbacks();

    await api.analyzeFiles([], { templateType: 'small' }, cb);

    const [message, requestId] = cb.onError.mock.calls[0];
    expect(message).toBe(
      translations.en['serverError.rateLimit'].replace('{requests}', '10').replace('{window}', '60'),
    );
    expect(requestId).toBe('req-42');
  });

  it('analyzeFiles: ошибка ВНУТРИ SSE-потока тоже переводится', async () => {
    useStore.setState({ uiLocale: 'en' });
    const sse = [
      'event: error',
      'data: {"message":"Нет данных для анализа. Загрузите PDF, Excel или изображение.",'
        + '"message_key":"serverError.noData","message_params":{},"request_id":"r-7"}',
      '', '',
    ].join('\n');
    let sent = false;
    stubFetch({
      ok: true,
      body: {
        getReader: () => ({
          read: async () => {
            if (sent) return { done: true, value: undefined };
            sent = true;
            return { done: false, value: new TextEncoder().encode(sse) };
          },
        }),
      },
    } as never);
    const cb = analyzeCallbacks();

    await api.analyzeFiles([], { templateType: 'small' }, cb);

    expect(cb.onError).toHaveBeenCalledWith(translations.en['serverError.noData'], 'r-7');
  });

  it('fetchModels: ключ провайдера переводится, а не показывается русским', async () => {
    useStore.setState({ uiLocale: 'en' });
    stubFetch({
      ok: false,
      status: 503,
      json: async () => ({
        detail: 'LLM не настроен. Задайте LLM_API_URL или укажите URL в настройках.',
        message_key: 'serverError.llmNotConfigured',
        message_params: {},
      }),
    });

    await expect(api.fetchModels()).rejects.toThrow(
      translations.en['serverError.llmNotConfigured'],
    );
  });

  it('buildJinjaTemplate: отказ читается из тела, как у buildTemplate', async () => {
    useStore.setState({ uiLocale: 'en' });
    stubFetch({
      ok: false,
      status: 500,
      json: async () => ({
        detail: 'Внутренняя ошибка сервера',
        message_key: 'serverError.internal',
        message_params: {},
      }),
    });

    await expect(api.buildJinjaTemplate({} as never)).rejects.toThrow(
      translations.en['serverError.internal'],
    );
  });
});
