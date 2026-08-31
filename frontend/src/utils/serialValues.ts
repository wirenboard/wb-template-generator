/**
 * Разбор значений в записи wb-mqtt-serial — адрес и поля `serial_int`.
 *
 * Схема допускает у адреса три записи — десятичную, hex «0xFF» и побитовую
 * «109:1:2», у `on_value` и `off_value` две. Поле ввода текстовое, поэтому число от
 * строковых записей отделяем здесь.
 */

const DECIMAL_REGEX = /^\d+$/;
const HEX_REGEX = /^0x[\dA-F]+$/i;
// serial_int разрешает и отрицательное целое
const INTEGER_REGEX = /^-?\d+$/;

/** Число для десятичной записи, строка для hex и побитовой. Неразобранное — как введено. */
export function parseAddressInput(raw: string): string | number {
  const value = raw.trim();
  if (DECIMAL_REGEX.test(value)) return Number(value);
  // Схема требует префикс в нижнем регистре, сами цифры — в любом
  if (HEX_REGEX.test(value)) return `0x${value.slice(2)}`;
  return value;
}

/**
 * Ключ сортировки по адресу — сравнение строк поставило бы «0x10» перед 2. Побитовый
 * адрес даёт ключ по всем частям, чтобы биты одного регистра шли по порядку.
 */
export function addressSortKey(value: string | number | null | undefined): number[] {
  if (typeof value === 'number') return [value];
  if (typeof value !== 'string') return [0];
  return value.trim().split(':').map((part) => {
    if (DECIMAL_REGEX.test(part)) return Number(part);
    if (HEX_REGEX.test(part)) return parseInt(part.slice(2), 16);
    return 0;
  });
}

/**
 * Разбор поля, где схема разрешает две записи (`serial_int`) — число или «0xFF».
 * `undefined` для пустого поля, `null` для незавершённого ввода вроде «0x».
 */
export function parseSerialIntInput(raw: string): number | string | undefined | null {
  const value = raw.trim();
  if (!value) return undefined;
  if (INTEGER_REGEX.test(value)) return Number(value);
  // Схема требует префикс в нижнем регистре, сами цифры — в любом
  if (HEX_REGEX.test(value)) return `0x${value.slice(2)}`;
  return null;
}

/** Сравнение адресов по значению, часть за частью. */
export function compareAddresses(
  left: string | number | null | undefined,
  right: string | number | null | undefined,
): number {
  const a = addressSortKey(left);
  const b = addressSortKey(right);
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const diff = (a[i] ?? 0) - (b[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}
