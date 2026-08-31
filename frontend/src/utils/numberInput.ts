/**
 * Разбор числа из текстового поля ввода.
 *
 * Поле type="number" на незавершённом вводе («0.», «-») отдаёт пустой value, и
 * контролируемое поле откатывает набранное. Поэтому поля текстовые, а разбор здесь.
 */

// String() выводит значения вида 1e-7 только в этой записи, иначе их не отредактировать
const DECIMAL_REGEX = /^-?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$/;
const INTEGER_REGEX = /^-?\d+$/;

/**
 * Число, `undefined` для пустого поля и `null` для незавершённого ввода. При `null`
 * состояние не меняем, пользователь ещё набирает.
 */
export function parseNumberInput(text: string, integer = false): number | undefined | null {
  const value = text.trim();
  if (!value) return undefined;
  if (!(integer ? INTEGER_REGEX : DECIMAL_REGEX).test(value)) return null;
  const parsed = Number(value.replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * Значение, которое поле отдаёт наружу. Пустое даёт `fallback` там, где значение
 * обязательное, иначе `undefined`. Набранное зажимается в границы `min`/`max`.
 */
export function resolveFieldValue(
  parsed: number | undefined,
  fallback?: number,
  min?: number,
  max?: number,
): number | undefined {
  if (parsed === undefined) return fallback;
  if (min !== undefined && parsed < min) return min;
  if (max !== undefined && parsed > max) return max;
  return parsed;
}

/** Текст поля для значения из состояния — всегда с точкой. */
export function formatNumberValue(value: number | string | null | undefined): string {
  return value == null || Number.isNaN(value) ? '' : String(value);
}
