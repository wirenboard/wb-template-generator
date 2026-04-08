/**
 * Типы и хелперы для отображения результатов валидации регистров.
 * Бэкенд возвращает ошибки с i18n-ключами, фронтенд рендерит через t().
 */

export type ValidationSeverity = 'error' | 'warning';

export interface FieldValidationError {
  field: string;
  severity: ValidationSeverity;
  message_key: string;
  message_params: Record<string, string | number>;
  suggestion?: string | null;
}

export interface RegisterValidationResult {
  register_id: string;
  errors: FieldValidationError[];
}

export interface ValidationResponse {
  registers: RegisterValidationResult[];
  error_count: number;
  warning_count: number;
}

/** Индексированный Map для O(1) доступа при рендеринге */
export type ValidationMap = Map<string, FieldValidationError[]>;

/** Собирает Map из ответа API */
export function buildValidationMap(results: RegisterValidationResult[]): ValidationMap {
  const map = new Map<string, FieldValidationError[]>();
  for (const rv of results) {
    if (rv.errors.length > 0) {
      map.set(rv.register_id, rv.errors);
    }
  }
  return map;
}

/** Ошибки конкретного поля конкретного регистра */
export function getFieldErrors(
  map: ValidationMap, registerId: string, field: string,
): FieldValidationError[] {
  const errors = map.get(registerId);
  if (!errors) return [];
  return errors.filter((e) => e.field === field);
}

/** Максимальная серьёзность для регистра (для иконки в строке) */
export function getRegisterSeverity(
  map: ValidationMap, registerId: string,
): ValidationSeverity | null {
  const errors = map.get(registerId);
  if (!errors || errors.length === 0) return null;
  return errors.some((e) => e.severity === 'error') ? 'error' : 'warning';
}

/** Суммарные счётчики для тулбара/модалки */
export function getValidationSummary(
  map: ValidationMap,
): { errors: number; warnings: number } {
  let errors = 0;
  let warnings = 0;
  for (const errs of map.values()) {
    for (const e of errs) {
      if (e.severity === 'error') errors++;
      else warnings++;
    }
  }
  return { errors, warnings };
}
