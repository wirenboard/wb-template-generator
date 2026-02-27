import type { Register } from '../types';

/** Нормализация имени: "Show modes as range" → "show_modes_as_range" */
function normalize(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
}

/** Regex для извлечения имён из condition-выражений */
const CONDITION_REF_RE = /(?:^|[^a-zA-Z0-9_])([a-zA-Z_][a-zA-Z0-9_ ]*?)(?:==|!=|>=|<=|>|<)/g;

/**
 * Возвращает Set id регистров, у которых condition ссылается на канал (не параметр).
 * Condition может зависеть только от параметров (is_parameter: true).
 */
export function findInvalidConditionIds(registers: Register[]): Set<string> {
  const ids = new Set<string>();
  for (const reg of registers) {
    if (!reg.condition) continue;
    const refs = reg.condition.matchAll(CONDITION_REF_RE);
    for (const m of refs) {
      const refNorm = normalize(m[1].trim());
      const target = registers.find((r) =>
        normalize(r.name) === refNorm || normalize(r.id) === refNorm ||
        (r.original_channel_id && normalize(r.original_channel_id) === refNorm)
      );
      // Если target найден и он НЕ параметр — невалидная зависимость
      if (target && !target.is_parameter) {
        ids.add(reg.id);
      }
    }
  }
  return ids;
}
