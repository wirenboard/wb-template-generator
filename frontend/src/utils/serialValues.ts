/**
 * Разбор значений в записи wb-mqtt-serial — адрес и числовые лимиты.
 *
 * Схема драйвера допускает у адреса три записи — десятичное число, hex-строку
 * «0xFF» и побитовую «109:1:2». Поле ввода текстовое, поэтому число от строковых
 * записей отделяем здесь.
 */

const DECIMAL_REGEX = /^\d+$/;
const HEX_REGEX = /^0x[\dA-F]+$/i;

/** Число для десятичной записи, строка для hex и побитовой. Неразобранное — как введено. */
export function parseAddressInput(raw: string): string | number {
  const value = raw.trim();
  if (DECIMAL_REGEX.test(value)) return Number(value);
  // Схема требует префикс в нижнем регистре, сами цифры — в любом
  if (HEX_REGEX.test(value)) return `0x${value.slice(2)}`;
  return value;
}

/**
 * Значение адреса для сортировки таблицы: сравнение строк поставило бы «0x10»
 * перед 2. Побитовый адрес идёт по своему регистру, неразобранный — по нулю.
 */
export function addressSortValue(value: string | number | null | undefined): number {
  if (typeof value === 'number') return value;
  if (typeof value !== 'string') return 0;
  const head = value.trim().split(':')[0];
  if (DECIMAL_REGEX.test(head)) return Number(head);
  if (HEX_REGEX.test(head)) return parseInt(head.slice(2), 16);
  return 0;
}

/**
 * Числовое значение лимита, `null` — запись не разобрана. `min` и `max` бывают
 * записаны hex-строкой, поэтому считать по ним нельзя, не приведя к числу.
 */
export function numericValue(value: string | number | null | undefined): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string') return null;
  const text = value.trim();
  if (HEX_REGEX.test(text)) return parseInt(text.slice(2), 16);
  const parsed = Number(text.replace(',', '.'));
  return text !== '' && Number.isFinite(parsed) ? parsed : null;
}
