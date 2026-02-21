import { useStore } from '../store';
import { useT } from '../i18n';
import type { WBParameter } from '../types';

interface ParameterPreviewProps {
  paramKey: string;
  param: WBParameter;
  registerId?: string;
  displayName: string;
  displayDescription?: string;
  onValueChange?: (name: string, value: number) => void;
}

/** Превью параметра в стиле WB (настройки устройства) */
export default function ParameterPreview({ param, paramKey, registerId, displayName, displayDescription, onValueChange }: ParameterPreviewProps) {
  const t = useT();
  const setHighlightedRegister = useStore((s) => s.setHighlightedRegister);
  const highlightedRegisterId = useStore((s) => s.highlightedRegisterId);

  const enumValues = param.enum;
  const enumTitles = param.enum_titles;
  const defaultValue = param.default;
  const min = param.min;
  const max = param.max;
  const condition = param.condition;
  const isReadonly = param.readonly;

  const isHighlighted = registerId != null && highlightedRegisterId === registerId;

  const handleClick = () => {
    if (registerId) {
      setHighlightedRegister(isHighlighted ? null : registerId);
    }
  };

  // Элемент управления: RW → editable, RO → readonly текст
  let control: React.ReactNode;

  if (enumValues && enumTitles && enumTitles.length > 0) {
    if (isReadonly) {
      // RO: показываем значение как текст
      const selectedIdx = defaultValue != null
        ? enumValues.indexOf(Number(defaultValue))
        : 0;
      const displayText = selectedIdx >= 0 ? enumTitles[selectedIdx] : String(defaultValue ?? '--');
      control = (
        <span className="text-xs text-gray-600 font-mono bg-gray-100 rounded px-2 py-0.5">
          {displayText}
        </span>
      );
    } else {
      // RW: dropdown
      const selectedIdx = defaultValue != null
        ? enumValues.indexOf(Number(defaultValue))
        : 0;
      control = (
        <select
          className="border border-gray-300 rounded px-2 py-0.5 text-xs bg-white min-w-[100px]"
          defaultValue={selectedIdx >= 0 ? String(enumValues[selectedIdx]) : undefined}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => { e.stopPropagation(); onValueChange?.(param.title ?? paramKey, Number(e.target.value)); }}
        >
          {enumTitles.map((t, i) => (
            <option key={i} value={enumValues[i] != null ? String(enumValues[i]) : String(i)}>
              {t}
            </option>
          ))}
        </select>
      );
    }
  } else {
    // Числовое поле (value) — с min/max если заданы
    if (isReadonly) {
      control = (
        <span className="text-xs text-gray-600 font-mono bg-gray-100 rounded px-2 py-0.5">
          {defaultValue != null ? String(defaultValue) : '--'}
        </span>
      );
    } else {
      control = (
        <input
          type="number"
          className="border border-gray-300 rounded px-2 py-0.5 text-xs w-20 bg-white"
          min={min}
          max={max}
          defaultValue={defaultValue != null ? Number(defaultValue) : min ?? 0}
          onClick={(e) => e.stopPropagation()}
        />
      );
    }
  }

  return (
    <div
      id={registerId ? `preview-${registerId}` : undefined}
      onClick={handleClick}
      className={`flex items-center justify-between gap-3 px-3 py-2 cursor-pointer transition-colors border-l-2 ${
        isHighlighted
          ? 'bg-blue-50 border-l-blue-500'
          : 'border-l-transparent hover:bg-gray-50'
      }`}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-800 truncate">{displayName}</span>
          {condition && (
            <span
              className="text-[10px] bg-yellow-100 text-yellow-700 rounded px-1 flex-shrink-0 cursor-help"
              title={t('preview.conditionLabel', { cond: condition })}
            >
              {t('preview.conditional')}
            </span>
          )}
        </div>
        {displayDescription && (
          <div className="text-[10px] text-gray-400 truncate">{displayDescription}</div>
        )}
      </div>
      <div className="flex-shrink-0">{control}</div>
    </div>
  );
}
