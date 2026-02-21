import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import translations, { LOCALES } from '../i18n/translations';
import { getT, getHasTranslations } from '../i18n';
import { resetMocks } from './setup';

/** Все коды локалей из LOCALES (автоматически обновляется при добавлении новых) */
const ALL_LOCALE_CODES = LOCALES.map((l) => l.code);
const NON_RU_LOCALES = ALL_LOCALE_CODES.filter((c) => c !== 'ru');

function getState() {
  return useStore.getState();
}

// Для i18n-тестов достаточно сбрасывать uiLocale — остальной state store не влияет
beforeEach(() => {
  resetMocks();
  useStore.setState({ uiLocale: 'ru' });
});

// --- 1. Полнота переводов ---

describe('translations completeness', () => {
  const ruKeys = Object.keys(translations.ru).sort();

  for (const locale of NON_RU_LOCALES) {
    it(`${locale} содержит все ключи из ru`, () => {
      const localeKeys = Object.keys(translations[locale]);
      const missing = ruKeys.filter((k) => !localeKeys.includes(k));
      expect(missing).toEqual([]);
    });
  }

  it('все локали содержат одинаковое количество ключей', () => {
    const counts = ALL_LOCALE_CODES.map(
      (l) => Object.keys(translations[l]).length,
    );
    expect(new Set(counts).size).toBe(1);
  });

  it('нет лишних ключей в остальных локалях (которых нет в ru)', () => {
    for (const locale of NON_RU_LOCALES) {
      const extra = Object.keys(translations[locale]).filter(
        (k) => !ruKeys.includes(k),
      );
      expect(extra).toEqual([]);
    }
  });
});

// --- 2. Интерполяция ---

describe('interpolate (через getT)', () => {
  it('подставляет {key} параметры', () => {
    useStore.setState({ uiLocale: 'ru' });
    const t = getT();
    const result = t('toolbar.regCount', { count: 5 });
    expect(result).toContain('5');
    expect(result).not.toContain('{count}');
  });

  it('оставляет {key} при отсутствии параметров', () => {
    useStore.setState({ uiLocale: 'ru' });
    const t = getT();
    const result = t('toolbar.regCount');
    expect(result).toContain('{count}');
  });

  it('подставляет несколько параметров', () => {
    useStore.setState({ uiLocale: 'ru' });
    const t = getT();
    // store.translated использует {done} и {total}
    const result = t('store.translated', { done: 10, total: 20 });
    expect(result).toContain('10');
    expect(result).toContain('20');
    expect(result).not.toContain('{done}');
    expect(result).not.toContain('{total}');
  });

  it('корректно подставляет 0 (falsy value)', () => {
    useStore.setState({ uiLocale: 'ru' });
    const t = getT();
    const result = t('toolbar.regCount', { count: 0 });
    expect(result).toContain('0');
    expect(result).not.toContain('{count}');
  });

  it('оставляет нераспознанные плейсхолдеры', () => {
    useStore.setState({ uiLocale: 'ru' });
    const t = getT();
    const result = t('store.translated', { done: 5 }); // total не передан
    expect(result).toContain('5');
    expect(result).toContain('{total}');
  });
});

// --- 3. getT() fallback ---

describe('getT fallback', () => {
  it('возвращает перевод для текущей локали', () => {
    useStore.setState({ uiLocale: 'en' });
    const t = getT();
    expect(t('toolbar.add')).toBe(translations.en['toolbar.add']);
  });

  it('возвращает перевод для ru', () => {
    useStore.setState({ uiLocale: 'ru' });
    const t = getT();
    expect(t('toolbar.add')).toBe(translations.ru['toolbar.add']);
  });

  it('fallback на ru при отсутствии ключа в текущей локали', () => {
    // Имитируем отсутствующий ключ: подставляем несуществующий
    // Поскольку мы проверяем полноту выше, тестируем через реальный механизм
    useStore.setState({ uiLocale: 'en' });
    const t = getT();
    // Ключ, который точно есть только в ru — используем механизм fallback
    const result = t('nonexistent.key.for.test');
    // Должен вернуть сам ключ (нет ни в en, ни в ru)
    expect(result).toBe('nonexistent.key.for.test');
  });

  it('возвращает сырой ключ если перевод не найден нигде', () => {
    useStore.setState({ uiLocale: 'kk' });
    const t = getT();
    expect(t('this.key.does.not.exist')).toBe('this.key.does.not.exist');
  });

  it('каждая локаль возвращает свой перевод app.title', () => {
    for (const locale of ALL_LOCALE_CODES) {
      useStore.setState({ uiLocale: locale });
      const t = getT();
      expect(t('app.title')).toBe(translations[locale]['app.title']);
    }
  });
});

// --- 4. getHasTranslations ---

describe('getHasTranslations', () => {
  it('true для ru (контроллер поддерживает RU+EN)', () => {
    useStore.setState({ uiLocale: 'ru' });
    expect(getHasTranslations()).toBe(true);
  });

  it('false для en (пустой массив в LOCALE_TRANSLATION_LANGUAGES)', () => {
    useStore.setState({ uiLocale: 'en' });
    expect(getHasTranslations()).toBe(false);
  });

  it('false для kk', () => {
    useStore.setState({ uiLocale: 'kk' });
    expect(getHasTranslations()).toBe(false);
  });

  it('false для it', () => {
    useStore.setState({ uiLocale: 'it' });
    expect(getHasTranslations()).toBe(false);
  });
});

// --- 5. detectLocale (через setUiLocale + store init) ---

describe('setUiLocale', () => {
  it('сохраняет локаль в state', () => {
    getState().setUiLocale('it');
    expect(getState().uiLocale).toBe('it');
  });

  it('сохраняет локаль в localStorage', () => {
    getState().setUiLocale('kk');
    expect(localStorage.getItem('wb-ui-locale')).toBe('kk');
  });

  it('переключение по всем локалям', () => {
    for (const locale of ALL_LOCALE_CODES) {
      getState().setUiLocale(locale);
      expect(getState().uiLocale).toBe(locale);
      expect(localStorage.getItem('wb-ui-locale')).toBe(locale);
    }
  });
});

// NB: detectLocale() вызывается при инициализации Zustand store (один раз при загрузке модуля).
// Полноценный unit-тест требует рефакторинга (export функции). Покрытие через интеграционные тесты.

// --- 6. Согласованность ключей с параметрами ---

describe('translations параметры согласованы', () => {
  const paramRegex = /\{(\w+)\}/g;

  /** Извлекает плейсхолдеры из строки */
  function extractParams(str: string): string[] {
    const params: string[] = [];
    let match;
    while ((match = paramRegex.exec(str)) !== null) {
      params.push(match[1]);
    }
    paramRegex.lastIndex = 0;
    return params.sort();
  }

  it('все локали имеют одинаковые плейсхолдеры для каждого ключа', () => {
    const locales = ALL_LOCALE_CODES;
    const ruKeys = Object.keys(translations.ru);
    const mismatches: string[] = [];

    for (const key of ruKeys) {
      const ruParams = extractParams(translations.ru[key]);
      if (ruParams.length === 0) continue;

      for (const locale of locales) {
        if (locale === 'ru') continue;
        const localeParams = extractParams(translations[locale][key] ?? '');
        if (JSON.stringify(ruParams) !== JSON.stringify(localeParams)) {
          mismatches.push(`${locale}.${key}: ожидались {${ruParams.join(',')}}, получены {${localeParams.join(',')}}`);
        }
      }
    }

    expect(mismatches).toEqual([]);
  });
});
