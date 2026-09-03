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

/**
 * Что удаляет Delete: отмеченные чекбоксами строки, а если таких нет — подсвеченную.
 *
 * @returns набор id либо null, если удалять нечего — тогда клавиша не перехватывается
 */
export function deleteTargets(
  selected: ReadonlySet<string>,
  highlightedId: string | null,
): Set<string> | null {
  if (selected.size > 0) return new Set(selected);
  if (highlightedId) return new Set([highlightedId]);
  return null;
}

/**
 * Печатает ли пользователь в этом элементе — тогда клавиши строк ему не мешают.
 *
 * Чекбокс к таким не относится: Delete в нём ничего не делает, а фокус остаётся
 * ровно на нём сразу после того, как строку отметили галкой, — то есть в тот
 * момент, когда удаление и нужно.
 */
export function isTypingTarget(el: {
  tagName: string;
  type?: string;
  isContentEditable?: boolean;
}): boolean {
  if (el.isContentEditable) return true;
  const tag = el.tagName.toUpperCase();
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag !== 'INPUT') return false;
  const type = (el.type ?? 'text').toLowerCase();
  return !['checkbox', 'radio', 'button', 'submit', 'reset', 'file', 'range', 'color'].includes(type);
}
