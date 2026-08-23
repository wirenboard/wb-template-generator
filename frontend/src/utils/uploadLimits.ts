/**
 * Запас на то, что едет в теле помимо файлов: обвязка multipart и поля формы.
 * Весомо в них только своё описание задачи для модели — около 20 КБ.
 */
export const REQUEST_OVERHEAD_BYTES = 64 * 1024;

export interface Split {
  accepted: File[];
  rejected: File[];
}

/** Отбирает файлы по расширению. Список приходит с бэкенда в `/api/status`. */
export function splitByExtension(incoming: File[], allowed: string[]): Split {
  const accepted: File[] = [];
  const rejected: File[] = [];
  for (const file of incoming) {
    const dot = file.name.lastIndexOf('.');
    const ext = dot >= 0 ? file.name.slice(dot).toLowerCase() : '';
    (allowed.includes(ext) ? accepted : rejected).push(file);
  }
  return { accepted, rejected };
}

/** Отбирает файлы по остатку до максимума на запрос с учётом уже выбранных. */
export function splitByCount(chosen: File[], incoming: File[], maxFiles: number): Split {
  const free = Math.max(0, maxFiles - chosen.length);
  return { accepted: incoming.slice(0, free), rejected: incoming.slice(free) };
}

/**
 * Отбирает файлы по остатку бюджета: nginx режет тело целиком, поэтому лимит
 * относится к сумме выбранных файлов, а не к размеру каждого.
 */
export function splitByRequestBudget(chosen: File[], incoming: File[], maxBytes: number): Split {
  const budget = maxBytes - REQUEST_OVERHEAD_BYTES;
  let used = chosen.reduce((sum, f) => sum + f.size, 0);
  const accepted: File[] = [];
  const rejected: File[] = [];
  for (const file of incoming) {
    if (used + file.size <= budget) {
      accepted.push(file);
      used += file.size;
    } else {
      rejected.push(file);
    }
  }
  return { accepted, rejected };
}
