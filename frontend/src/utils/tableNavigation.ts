/**
 * Навигация по редактируемым ячейкам строки таблицы регистров.
 *
 * Вынесено из RegisterTable отдельным модулем, чтобы логику перехода
 * можно было покрыть тестами без DOM (vitest работает в environment: 'node').
 */

/**
 * Соседнее редактируемое поле строки.
 *
 * @param fields  поля в порядке колонок таблицы
 * @param current текущее поле
 * @param dir     1 — вперёд (Tab), -1 — назад (Shift+Tab)
 * @returns следующее поле либо null, если вышли за край колонок
 *          (тогда фокус уводится за пределы редактируемой части строки)
 */
export function nextField<F extends string>(
  fields: readonly F[],
  current: F,
  dir: 1 | -1,
): F | null {
  const index = fields.indexOf(current);
  if (index === -1) return null;
  return fields[index + dir] ?? null;
}
