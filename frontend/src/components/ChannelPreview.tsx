import { useState } from 'react';
import { useStore } from '../store';
import { useT } from '../i18n';
import type { WBChannel } from '../types';

/** Placeholder-значения по единицам измерения */
function getPlaceholderValue(units?: string, channelType?: string): string {
  if (channelType === 'switch' || channelType === 'wo-switch') return '';
  if (channelType === 'text') return 'ABC123';
  if (channelType === 'pushbutton') return '';
  if (!units) return '0';

  const map: Record<string, string> = {
    'V': '230.0', 'mV': '3300', 'A': '1.5', 'mA': '4.0',
    'W': '345.0', 'kWh': '1234.5', 'Hz': '50.0', 'rpm': '1500',
    'Ohm': '100.0', 'mOhm': '500',
    'bar': '1.013', 'mbar': '1013', 'Pa': '101325',
    'deg C': '22.5', '%': '55', 'RH': '55',
    'ppm': '400', 'ppb': '50', 'lx': '450', 'dB': '35',
    's': '60', 'min': '5', 'h': '24',
    'm': '1.5', 'mm/h': '5', 'm/s': '3.2', 'm^3/h': '2.5', 'm^3': '12.5',
    'g': '100', 'kg': '1.5', 'Gcal/h': '0.5', 'cal': '1000', 'Gcal': '15',
    'deg': '180', 'rad': '3.14',
  };

  return map[units] ?? '0';
}

interface ChannelPreviewProps {
  channel: WBChannel;
  registerId?: string;
  displayName: string;
  conditionalCount?: number;
  conditions?: string[];
  onValueChange?: (name: string, value: number) => void;
}

/** Превью канала в стиле Wiren Board */
export default function ChannelPreview({ channel, registerId, displayName, conditionalCount, conditions, onValueChange }: ChannelPreviewProps) {
  const t = useT();
  const setHighlightedRegister = useStore((s) => s.setHighlightedRegister);
  const highlightedRegisterId = useStore((s) => s.highlightedRegisterId);

  const channelType = channel.type ?? 'value';
  const units = channel.units;
  const condition = channel.condition;
  const isReadonly = channel.readonly;
  const enumValues = channel.enum;
  const enumTitles = channel.enum_titles;
  const min = channel.min;
  const max = channel.max;

  const placeholder = getPlaceholderValue(units, channelType);
  const isHighlighted = registerId != null && highlightedRegisterId === registerId;

  // Визуальные состояния для интерактивных контролов
  const [toggleOn, setToggleOn] = useState(true);
  const [rangeVal, setRangeVal] = useState(
    min != null && max != null ? Math.round((min + max) / 2) : 50,
  );
  const [colorVal, setColorVal] = useState('#3b82f6');

  const handleClick = () => {
    if (registerId) {
      setHighlightedRegister(isHighlighted ? null : registerId);
    }
  };

  const stop = (e: React.MouseEvent | React.ChangeEvent) => e.stopPropagation();

  const isSwitch = channelType === 'switch' || channelType === 'wo-switch';
  const isRange = channelType === 'range';
  const isPushbutton = channelType === 'pushbutton';
  const isRgb = channelType === 'rgb';
  const hasEnum = enumValues && enumTitles && enumTitles.length > 0;

  /** Рендер правой части — контрол */
  function renderControl(): React.ReactNode {
    // switch / wo-switch — всегда toggle
    if (isSwitch) {
      if (isReadonly) {
        return (
          <div className="w-9 h-5 bg-gray-300 rounded-full relative opacity-60">
            <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full shadow" />
          </div>
        );
      }
      return (
        <div
          onClick={(e) => {
            stop(e);
            setToggleOn((v) => {
              const next = !v;
              onValueChange?.(channel.name, next ? 1 : 0);
              return next;
            });
          }}
          className={`w-9 h-5 rounded-full relative shadow-inner cursor-pointer transition-colors ${
            toggleOn ? 'bg-green-500' : 'bg-gray-300'
          }`}
        >
          <div
            className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-all ${
              toggleOn ? 'right-0.5' : 'left-0.5'
            }`}
          />
        </div>
      );
    }

    // pushbutton
    if (isPushbutton) {
      if (isReadonly) {
        return (
          <button
            className="px-3 py-0.5 text-xs bg-gray-100 text-gray-400 rounded border border-gray-200 cursor-default"
            disabled
          >
            Push
          </button>
        );
      }
      return (
        <button
          onClick={stop}
          className="px-3 py-0.5 text-xs bg-gray-200 text-gray-700 rounded border border-gray-300 hover:bg-gray-300 active:bg-gray-400 transition-colors"
        >
          Push
        </button>
      );
    }

    // range
    if (isRange) {
      if (isReadonly) {
        return (
          <div className="flex items-center gap-2">
            {min != null && <span className="text-[10px] text-gray-400">{min}</span>}
            <div className="w-16 h-1.5 bg-gray-200 rounded-full relative">
              <div className="h-1.5 bg-gray-400 rounded-full" style={{ width: '50%' }} />
            </div>
            {max != null && <span className="text-[10px] text-gray-400">{max}</span>}
            <span className="text-xs text-gray-400 font-mono w-8 text-right">
              {min != null && max != null ? Math.round((min + max) / 2) : '--'}
            </span>
          </div>
        );
      }
      return (
        <div className="flex items-center gap-2" onClick={stop}>
          {min != null && <span className="text-[10px] text-gray-400">{min}</span>}
          <input
            type="range"
            className="w-16 h-1 accent-blue-500"
            min={min ?? 0}
            max={max ?? 100}
            value={rangeVal}
            onChange={(e) => { stop(e); const v = Number(e.target.value); setRangeVal(v); onValueChange?.(channel.name, v); }}
          />
          {max != null && <span className="text-[10px] text-gray-400">{max}</span>}
          <span className="text-xs text-gray-600 font-mono w-8 text-right">{rangeVal}</span>
        </div>
      );
    }

    // rgb
    if (isRgb) {
      if (isReadonly) {
        return (
          <div
            className="w-6 h-6 rounded border border-gray-300"
            style={{ backgroundColor: colorVal }}
          />
        );
      }
      return (
        <input
          type="color"
          className="w-6 h-6 rounded border border-gray-300 cursor-pointer"
          value={colorVal}
          onClick={stop}
          onChange={(e) => { stop(e); setColorVal(e.target.value); }}
        />
      );
    }

    // enum
    if (hasEnum) {
      if (isReadonly) {
        return (
          <span className="text-xs text-gray-600 font-mono bg-gray-100 rounded px-2 py-0.5">
            {enumTitles![0]}
          </span>
        );
      }
      return (
        <select
          className="border border-gray-300 rounded px-2 py-0.5 text-xs bg-white min-w-[80px]"
          defaultValue={enumValues![0] != null ? String(enumValues![0]) : '0'}
          onClick={stop}
          onChange={(e) => { stop(e); onValueChange?.(channel.name, Number(e.target.value)); }}
        >
          {enumTitles!.map((t, i) => (
            <option key={i} value={enumValues![i] != null ? String(enumValues![i]) : String(i)}>
              {t}
            </option>
          ))}
        </select>
      );
    }

    // text
    if (channelType === 'text') {
      if (isReadonly) {
        return (
          <span className="text-sm text-gray-400 font-mono">{placeholder}</span>
        );
      }
      return (
        <input
          type="text"
          className="border border-gray-300 rounded px-2 py-0.5 text-xs w-20 bg-white"
          placeholder={placeholder}
          onClick={stop}
        />
      );
    }

    // value и прочие
    if (isReadonly) {
      return (
        <span className="text-sm text-gray-400 font-mono">
          {placeholder}
          {units ? <span className="text-gray-300 ml-1 text-xs">{units}</span> : null}
        </span>
      );
    }
    return (
      <div className="flex items-center gap-1" onClick={stop}>
        <input
          type="text"
          className="border border-gray-300 rounded px-2 py-0.5 text-xs w-16 bg-white font-mono"
          placeholder={placeholder}
        />
        {units ? <span className="text-gray-400 text-xs">{units}</span> : null}
      </div>
    );
  }

  return (
    <div
      id={registerId ? `preview-${registerId}` : undefined}
      onClick={handleClick}
      className={`flex justify-between items-center px-3 py-2 cursor-pointer transition-colors border-l-2 ${
        isHighlighted
          ? 'bg-blue-50 border-l-blue-500'
          : 'border-l-transparent hover:bg-gray-50'
      }`}
    >
      {/* Левая часть: имя */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-sm text-gray-800 truncate">{displayName}</span>
        {condition && (
          <span
            className="text-[10px] bg-yellow-100 text-yellow-700 rounded px-1 flex-shrink-0 cursor-help"
            title={conditionalCount && conditionalCount > 1
              ? `${t('preview.variantsTitle', { count: conditionalCount })}:\n${conditions?.join('\n')}`
              : t('preview.conditionLabel', { cond: condition })}
          >
            {conditionalCount && conditionalCount > 1 ? t('preview.variants', { count: conditionalCount }) : t('preview.conditional')}
          </span>
        )}
      </div>

      {/* Правая часть: контрол */}
      <div className="flex-shrink-0 ml-3">
        {renderControl()}
      </div>
    </div>
  );
}
