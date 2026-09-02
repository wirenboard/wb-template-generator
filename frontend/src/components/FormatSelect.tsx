import { FORMAT_OPTIONS } from '../constants';
import { useT } from '../i18n';

interface FormatSelectProps {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  /** Ref для автофокуса — при inline-редактировании ячейка сама наводит фокус */
  inputRef?: React.RefCallback<HTMLElement>;
  onKeyDown?: (e: React.KeyboardEvent<HTMLSelectElement>) => void;
  onBlur?: () => void;
}

/** Dropdown формата с подсказками — показывает описание каждого формата */
export default function FormatSelect({ value, onChange, className = '', inputRef, onKeyDown, onBlur }: FormatSelectProps) {
  const t = useT();
  return (
    <select
      ref={inputRef}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={onKeyDown}
      onBlur={onBlur}
      className={className}
      title={t(FORMAT_OPTIONS.find((f) => f.value === value)?.descriptionKey ?? '')}
    >
      {FORMAT_OPTIONS.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label} — {t(opt.descriptionKey)}
        </option>
      ))}
    </select>
  );
}
