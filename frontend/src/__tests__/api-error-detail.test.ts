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
