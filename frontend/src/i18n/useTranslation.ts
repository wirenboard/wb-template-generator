import { useCallback } from 'react';
import { useStore } from '../store';
import translations, { type Locale } from './translations';

/** Подставляет параметры {key} в строку */
function interpolate(str: string, params?: Record<string, string | number>): string {
  if (!params) return str;
  return str.replace(/\{(\w+)\}/g, (_, key) => {
    const val = params[key];
    return val !== undefined ? String(val) : `{${key}}`;
  });
}

/** React-хук: возвращает функцию перевода t(key, params?) */
export function useT(): (key: string, params?: Record<string, string | number>) => string {
  const locale = useStore((s) => s.uiLocale);

  return useCallback(
    (key: string, params?: Record<string, string | number>) => {
      const dict = translations[locale];
      const str = dict?.[key] ?? translations.ru[key] ?? key;
      return interpolate(str, params);
    },
    [locale],
  );
}

/** Не-React функция перевода (для store, api и т.д.) */
export function getT(): (key: string, params?: Record<string, string | number>) => string {
  const locale = useStore.getState().uiLocale;
  const dict = translations[locale];
  return (key: string, params?: Record<string, string | number>) => {
    const str = dict?.[key] ?? translations.ru[key] ?? key;
    return interpolate(str, params);
  };
}

/** Хук: текущая локаль + setter */
export function useLocale(): [Locale, (l: Locale) => void] {
  const locale = useStore((s) => s.uiLocale);
  const setLocale = useStore((s) => s.setUiLocale);
  return [locale, setLocale];
}
