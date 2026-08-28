/**
 * Разбор числа из текстового поля ввода.
 *
 * Поле type="number" на незавершённом вводе («0.», «-») отдаёт в value пустую
 * строку, и контролируемое поле откатывает набранное. Поэтому числовые поля
 * размечены как текстовые, а разбор и вывод значения живут здесь.
 */

// Экспонента принимается потому, что String() выводит значения вида 1e-7 только в
// этой записи — иначе такое значение нельзя было бы отредактировать
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

/** Текст поля для значения из состояния — всегда с точкой. */
export function formatNumberValue(value: number | string | null | undefined): string {
  return value == null || Number.isNaN(value) ? '' : String(value);
}
