import { FORMAT_OPTIONS } from '../constants';
import { useT } from '../i18n';

interface FormatSelectProps {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

/** Dropdown формата с подсказками — показывает описание каждого формата */
export default function FormatSelect({ value, onChange, className = '' }: FormatSelectProps) {
  const t = useT();
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
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
