import { useEffect, useRef, useState } from 'react';
import { formatNumberValue, parseNumberInput } from '../utils/numberInput';

interface Props {
  /** Строка — запись, которую поле не разбирает (hex в min и max): показываем как есть */
  value: number | string | null | undefined;
  onChange: (value: number | undefined) => void;
  /** Значение для опустевшего поля там, где оно обязательное — scale → 1, offset → 0 */
  fallback?: number;
  /** Только целые — минус и цифры, без дробной части */
  integer?: boolean;
  placeholder?: string;
  className?: string;
}

/**
 * Числовое поле ввода — точка и запятая как разделитель дробной части, значение
 * можно стереть. Разметка текстовая, разбор в utils/numberInput.
 */
export default function NumberField({
  value, onChange, fallback, integer = false, placeholder, className,
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
    const parsed = parseNumberInput(raw, integer);
    if (parsed === null) return; // ввод незавершён, ждём остаток
    const next = parsed === undefined ? fallback : parsed;
    lastEmitted.current = next;
    onChange(next);
  };

  return (
    <input
      type="text"
      inputMode={integer ? 'numeric' : 'decimal'}
      value={text}
      onChange={(e) => handleChange(e.target.value)}
      // Уход из поля приводит текст к состоянию — «0,5» → «0.5», «1.» → «1»
      onBlur={() => setText(formatNumberValue(value))}
      placeholder={placeholder}
      className={className}
    />
  );
}
