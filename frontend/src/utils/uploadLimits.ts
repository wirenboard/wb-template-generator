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
 * Отбирает файлы по остатку бюджета. Потолок стоит на запрос целиком — и у сервера,
 * и у nginx перед ним, — поэтому размеры складываются.
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

export interface Limits {
  allowedExtensions: string[] | null;
  maxFiles: number | null;
  maxRequestSizeMb: number | null;
}

/** Отказ по потолку: ключ локализации и параметры, текст собирает интерфейс. */
export interface IntakeError {
  key: string;
  params: Record<string, string | number>;
}

export interface Intake {
  accepted: File[];
  errors: IntakeError[];
}

/**
 * Отбирает файлы по потолкам сервера — формат, число, суммарный размер.
 * Потолок ещё не приехал из /api/status — проверка пропускается, отберёт сервер.
 */
export function intakeFiles(chosen: File[], incoming: File[], limits: Limits): Intake {
  const errors: IntakeError[] = [];
  const names = (list: File[]) => list.map((f) => f.name).join(', ');
  let candidates = incoming;

  if (limits.allowedExtensions) {
    const { accepted, rejected } = splitByExtension(candidates, limits.allowedExtensions);
    if (rejected.length > 0) {
      errors.push({
        key: 'upload.formatError',
        params: { names: names(rejected), formats: limits.allowedExtensions.join(', ') },
      });
    }
    candidates = accepted;
  }

  if (limits.maxFiles !== null) {
    const { accepted, rejected } = splitByCount(chosen, candidates, limits.maxFiles);
    if (rejected.length > 0) {
      errors.push({
        key: 'upload.countError',
        params: { max: limits.maxFiles, names: names(rejected) },
      });
    }
    candidates = accepted;
  }

  if (limits.maxRequestSizeMb !== null) {
    const { accepted, rejected } = splitByRequestBudget(
      chosen, candidates, limits.maxRequestSizeMb * 1024 * 1024,
    );
    if (rejected.length > 0) {
      errors.push({
        key: 'upload.sizeError',
        params: {
          size: limits.maxRequestSizeMb,
          names: rejected
            .map((f) => `${f.name} (${(f.size / 1024 / 1024).toFixed(1)} MB)`)
            .join(', '),
        },
      });
    }
    candidates = accepted;
  }

  return { accepted: candidates, errors };
}
