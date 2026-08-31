import { useEffect, useRef, useState } from 'react';
import { formatNumberValue, parseNumberInput, resolveFieldValue } from '../utils/numberInput';
import { parseSerialIntInput } from '../utils/serialValues';

interface BaseProps {
  value: number | string | null | undefined;
  /** Значение для опустевшего поля там, где оно обязательное — scale → 1, offset → 0 */
  fallback?: number;
  /** Только целые — минус и цифры, без дробной части */
  integer?: boolean;
  /** Границы значения — поле не отдаёт наружу то, что вне них */
  min?: number;
  max?: number;
  placeholder?: string;
  className?: string;
}

// У полей serial_int запись бывает и hex, поэтому наружу уходит строка
type Props = BaseProps & (
  | { hex?: false; onChange: (value: number | undefined) => void }
  | { hex: true; onChange: (value: number | string | undefined) => void }
);

/**
 * Числовое поле ввода — точка и запятая как разделитель дробной части, значение
 * можно стереть. Разметка текстовая, разбор в utils/numberInput. С `hex` принимает
 * и запись «0xFF» и отдаёт её строкой.
 */
export default function NumberField({
  value, onChange, fallback, integer = false, hex = false, min, max, placeholder, className,
}: Props) {
  const [text, setText] = useState(() => formatNumberValue(value));
  // Последнее отданное наружу значение — чтобы свой же onChange не сбрасывал набранное
  const lastEmitted = useRef(value);

  // Значение сменилось снаружи (выбран другой регистр, сработал автофикс) — показываем его
  useEffect(() => {
    if (value !== lastEmitted.current) {
      lastEmitted.current = value;
      setText(formatNumberValue(value));
    }
  }, [value]);

  const handleChange = (raw: string) => {
    setText(raw);
    const parsed = hex ? parseSerialIntInput(raw) : parseNumberInput(raw, integer);
    if (parsed === null) return; // ввод незавершён, ждём остаток
    const next = typeof parsed === 'string' ? parsed : resolveFieldValue(parsed, fallback, min, max);
    lastEmitted.current = next;
    (onChange as (v: number | string | undefined) => void)(next);
  };

  return (
    <input
      type="text"
      inputMode={hex ? 'text' : integer ? 'numeric' : 'decimal'}
      value={text}
      onChange={(e) => handleChange(e.target.value)}
      // Уход из поля приводит текст к состоянию — «0,5» → «0.5», «1.» → «1»
      onBlur={() => setText(formatNumberValue(value))}
      placeholder={placeholder}
      className={className}
    />
  );
}
