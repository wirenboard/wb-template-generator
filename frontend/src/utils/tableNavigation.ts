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
 * Что удаляет Delete: отмеченные чекбоксами строки, а если таких нет — текущую.
 *
 * @param selected    id, отмеченные чекбоксами
 * @param currentId   строка, на которой стоит пользователь (фокус, иначе подсветка)
 * @param existingIds id живых регистров — в selected остаётся мусор от строк,
 *                    удалённых кнопкой «x», и от замены таблицы импортом или анализом
 * @returns набор id либо null, если удалять нечего — тогда клавиша не перехватывается
 */
export function deleteTargets(
  selected: ReadonlySet<string>,
  currentId: string | null,
  existingIds: ReadonlySet<string>,
): Set<string> | null {
  const alive = [...selected].filter((id) => existingIds.has(id));
  if (alive.length > 0) return new Set(alive);
  if (currentId && existingIds.has(currentId)) return new Set([currentId]);
  return null;
}

/**
 * id регистра из id DOM-строки (`reg-row-<uuid>`).
 *
 * Нужно, чтобы Delete бил по строке, где стоит фокус: подсветка ставится только
 * кликом мыши, а обход по Tab её не двигает — без этого клавиатурный флоу удалял
 * бы не ту строку, которую пользователь видит перед собой.
 */
export function rowIdFromDomId(domId: string | null | undefined): string | null {
  const prefix = 'reg-row-';
  if (!domId || !domId.startsWith(prefix)) return null;
  return domId.slice(prefix.length) || null;
}

/**
 * Печатает ли пользователь в этом элементе — тогда клавиши строк ему не мешают.
 *
 * Чекбокс к таким не относится: Delete в нём ничего не делает, а фокус остаётся
 * ровно на нём сразу после того, как строку отметили галкой, — то есть в тот
 * момент, когда удаление и нужно.
 */
export function isTypingTarget(el: {
  tagName?: string;
  type?: string;
  isContentEditable?: boolean;
}): boolean {
  if (el.isContentEditable) return true;
  const tag = (el.tagName ?? '').toUpperCase();
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag !== 'INPUT') return false;
  const type = (el.type ?? 'text').toLowerCase();
  return !['checkbox', 'radio', 'button', 'submit', 'reset', 'file', 'range', 'color'].includes(type);
}

/** Что делает нажатая клавиша со строками таблицы */
export type RowHotkeyAction = 'add' | 'delete' | null;

/**
 * Решение по нажатой клавише — вынесено из компонента, чтобы проверки
 * (модалка, набор текста, автоповтор) покрывались тестами без DOM.
 *
 * @param key         значение KeyboardEvent.key
 * @param repeat      автоповтор зажатой клавиши
 * @param hasModifier зажат Ctrl/Cmd/Alt/Shift — тогда клавиша принадлежит системе
 * @param modalOpen   открыта любая модалка приложения
 * @param typing      фокус в поле, где набирают текст
 * @param inRow       фокус внутри строки таблицы регистров
 */
export function rowHotkeyAction({
  key, repeat, hasModifier, modalOpen, typing, inRow,
}: {
  key: string;
  repeat?: boolean;
  hasModifier: boolean;
  modalOpen: boolean;
  typing: boolean;
  inRow: boolean;
}): RowHotkeyAction {
  // Автоповтор зажатой клавиши плодил бы строки десятками, а при удалении
  // затирал бы тост отмены до того, как им успеют воспользоваться
  if (hasModifier || repeat || modalOpen) return null;

  if (key === 'Insert') {
    // В открытой ячейке Insert полезной нагрузки не несёт, поэтому забираем его
    // и коммитим ввод. В полях вне таблицы клавиша принадлежит им.
    return typing && !inRow ? null : 'add';
  }
  if (key === 'Delete') {
    // В поле ввода и в списке Delete стирает символ
    return typing ? null : 'delete';
  }
  return null;
}
