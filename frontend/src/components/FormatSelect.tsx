import { FORMAT_OPTIONS } from '../constants';

interface FormatSelectProps {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

/** Dropdown формата с подсказками — показывает описание каждого формата */
export default function FormatSelect({ value, onChange, className = '' }: FormatSelectProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={className}
      title={FORMAT_OPTIONS.find((f) => f.value === value)?.description}
    >
      {FORMAT_OPTIONS.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label} — {opt.description}
        </option>
      ))}
    </select>
  );
}
