import { useState, useRef } from 'react';
import { useStore } from '../store';
import type { Register, EnumEntry } from '../types';
import { translateStrings } from '../api';
import EnumEditor from './EnumEditor';

interface Props {
  register: Register;
}

/** Иконка-подсказка */
function Tip({ text }: { text: string }) {
  return (
    <span
      className="inline-flex items-center justify-center w-3.5 h-3.5 ml-1 text-[9px] text-gray-400 bg-gray-100 rounded-full cursor-help border border-gray-200 flex-shrink-0"
      title={text}
    >
      ?
    </span>
  );
}

/** Заголовок секции */
function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5 flex items-center">
      {children}
    </div>
  );
}

// --- Правила видимости полей ---
// Основаны на JSON-схеме wb-mqtt-serial-confed-common.schema.json и README

const NUMERIC_FORMATS = new Set([
  's16', 'u16', 's8', 'u8', 's24', 'u24', 's32', 'u32', 's64', 'u64',
  'bcd8', 'bcd16', 'bcd24', 'bcd32', 'float', 'double', 'char8',
]);
const MULTI_REG_FORMATS = new Set(['u32', 's32', 'u64', 's64', 'float', 'double']);
const STRING_FORMATS = new Set(['string', 'string8']);

interface FieldVisibility {
  scaling: boolean;      // scale, offset, round_to
  limits: boolean;       // min, max
  enum: boolean;
  onOff: boolean;        // on_value, off_value
  wordOrder: boolean;
  byteOrder: boolean;
  errorValue: boolean;
  stringSize: boolean;   // string_data_size
  defaultValue: boolean;
  description: boolean;
  condition: boolean;
}

function getVisibility(reg: Register): FieldVisibility {
  const isBit = reg.reg_type === 'coil' || reg.reg_type === 'discrete';
  const isStr = STRING_FORMATS.has(reg.format);
  const isNumericFmt = NUMERIC_FORMATS.has(reg.format);
  const isMultiReg = MULTI_REG_FORMATS.has(reg.format);

  const ct = reg.channel_type;
  const isSwitch = ct === 'switch' || ct === 'wo-switch';
  const isPushbutton = ct === 'pushbutton';
  const isRgb = ct === 'rgb';

  // switch/pushbutton/rgb — бинарные/специальные, не используют масштабирование и пределы
  const isAnalog = !isSwitch && !isPushbutton && !isRgb;

  return {
    // scale/offset/round_to: числовой формат + аналоговый тип канала + не однобитовый регистр
    scaling: isNumericFmt && isAnalog && !isBit,

    // min/max: аналоговый тип + не бит + не строка
    limits: isAnalog && !isBit && !isStr,

    // enum: аналоговый тип (value, range, text, temperature и т.д.) + не бит
    enum: isAnalog && !isBit,

    // on/off: только switch/wo-switch на не-битовом регистре (coil и так 0/1)
    onOff: isSwitch && !isBit,

    // word_order: только для многорегистровых форматов
    wordOrder: isMultiReg && !isBit,

    // byte_order: для всех кроме бит и строк
    byteOrder: !isBit && !isStr,

    // error_value: для всех типов
    errorValue: !isBit,

    // string_data_size: только для string форматов
    stringSize: isStr,

    // default: только для параметров
    defaultValue: reg.is_parameter,

    // описание: только для параметров (подсказка к полю в UI устройства)
    description: reg.is_parameter,

    // condition: всегда
    condition: true,
  };
}

const HAS_CYRILLIC = /[а-яёА-ЯЁ]/;

/** Спиннер для кнопок LLM */
function LlmSpinner() {
  return <svg className="w-3 h-3 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" /></svg>;
}

/** Кнопка перевода одного поля через LLM */
function TranslateButton({ text, lang, onResult }: { text: string; lang: string; onResult: (v: string) => void }) {
  const llmAvailable = useStore((s) => s.llmAvailable);
  const llmConfig = useStore((s) => s.llmConfig);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!llmAvailable || !text) return null;

  const handleClick = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await translateStrings({ _: text }, lang, llmConfig);
      if (result._) onResult(result._);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Ошибка';
      setError(msg);
      setTimeout(() => setError(null), 4000);
    }
    setLoading(false);
  };

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className={`flex-shrink-0 ${error ? 'text-red-500' : 'text-purple-400 hover:text-purple-600'} disabled:opacity-50`}
      title={error ?? `Перевести на ${lang}`}
    >
      {loading ? <LlmSpinner /> : error ? <span className="text-[9px] font-bold">!</span> : <span className="text-[10px] font-bold uppercase">{lang}</span>}
    </button>
  );
}

/** Кнопка нормализации → EN: переводит кириллицу на английский, сохраняет русский в translations */
function NormalizeToEnButton({ text, onTranslated, onSaveRussian }: {
  text: string;
  onTranslated: (en: string) => void;
  onSaveRussian: (ru: string) => void;
}) {
  const llmAvailable = useStore((s) => s.llmAvailable);
  const llmConfig = useStore((s) => s.llmConfig);
  const addLanguage = useStore((s) => s.addLanguage);
  const languages = useStore((s) => s.languages);
  const [loading, setLoading] = useState(false);

  if (!llmAvailable || !text || !HAS_CYRILLIC.test(text)) return null;

  const handleClick = async () => {
    setLoading(true);
    try {
      const result = await translateStrings({ _: text }, 'en', llmConfig);
      if (result._) {
        if (!languages.some((l) => l.code === 'ru')) {
          addLanguage({ code: 'ru', label: 'Русский' });
        }
        onSaveRussian(text);
        onTranslated(result._);
      }
    } catch { /* игнорируем */ }
    setLoading(false);
  };

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="flex-shrink-0 text-orange-400 hover:text-orange-600 disabled:opacity-50"
      title="Перевести на English (русский сохранится в переводах)"
    >
      {loading ? <LlmSpinner /> : <span className="text-[10px] font-bold">→EN</span>}
    </button>
  );
}

/** Кнопки-операторы для поля condition */
const CONDITION_OPERATORS = [
  { label: '==', value: '==', title: 'Равно' },
  { label: '!=', value: '!=', title: 'Не равно' },
  { label: '>', value: '>', title: 'Больше' },
  { label: '<', value: '<', title: 'Меньше' },
  { label: '>=', value: '>=', title: 'Больше или равно' },
  { label: '<=', value: '<=', title: 'Меньше или равно' },
  { label: '&&', value: '&&', title: 'И (логическое)' },
  { label: '||', value: '||', title: 'ИЛИ (логическое)' },
  { label: '( )', value: '(', title: 'Скобки группировки', insert: '()' },
  { label: 'isDefined', value: 'isDefined()', title: 'Проверка: задан ли параметр в конфиге' },
];

/** Поле условия с кнопками операторов и вставкой в позицию курсора */
function ConditionField({
  value,
  onChange,
  availableParams,
  inputClass,
}: {
  value: string;
  onChange: (v: string) => void;
  availableParams: Array<{ id: string; name: string }>;
  inputClass: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  /** Вставить текст в позицию курсора */
  const insertAtCursor = (text: string, cursorOffset?: number) => {
    const el = inputRef.current;
    if (!el) {
      onChange(value + text);
      return;
    }
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const before = value.slice(0, start);
    const after = value.slice(end);
    const newValue = before + text + after;
    onChange(newValue);
    // Установить курсор после вставленного текста
    requestAnimationFrame(() => {
      const pos = start + (cursorOffset ?? text.length);
      el.focus();
      el.setSelectionRange(pos, pos);
    });
  };

  return (
    <div>
      <SectionTitle>Условие <Tip text="Condition — канал/параметр виден только когда условие истинно. Операторы: ==, !=, >, <, >=, <=, &&, ||, isDefined()" /></SectionTitle>
      <input
        ref={inputRef}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="isDefined(param)&&(param==value)"
        className={`${inputClass} w-full`}
      />
      <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px]">
        {/* Операторы */}
        {CONDITION_OPERATORS.map((op) => (
          <button
            key={op.label}
            type="button"
            onClick={() => {
              const text = op.insert ?? op.value;
              // Для скобок и isDefined() — ставим курсор внутрь
              const cursorInside = text === '()' || text === 'isDefined()';
              insertAtCursor(text, cursorInside ? text.length - 1 : undefined);
            }}
            className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded hover:bg-gray-200 font-mono"
            title={op.title}
          >
            {op.label}
          </button>
        ))}
        {/* Разделитель */}
        {availableParams.length > 0 && <span className="text-gray-300 mx-0.5">|</span>}
        {/* Параметры */}
        {availableParams.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => insertAtCursor(p.id)}
            className="px-1 py-0.5 bg-blue-50 text-blue-600 rounded hover:bg-blue-100 font-mono"
            title={p.name}
          >
            {p.id}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Панель деталей регистра (раскрывается под строкой таблицы) */
export default function RegisterDetailPanel({ register: reg }: Props) {
  const updateRegister = useStore((s) => s.updateRegister);
  const registers = useStore((s) => s.registers);


  const vis = getVisibility(reg);

  // Доступные параметры для condition
  const availableParams = registers
    .filter((r) => r.is_parameter && r.enabled)
    .map((r) => ({
      id: r.name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, ''),
      name: r.name,
    }));

  const update = (patch: Partial<Register>) => updateRegister(reg.id, patch);

  // Языки строго из глобального store.languages (управляются через модалку «Языки»)
  const storeLanguages = useStore((s) => s.languages);
  const translations = reg.translations ?? {};
  const langs = storeLanguages.map((l) => l.code);

  const updateTranslation = (lang: string, field: 'name' | 'description', value: string) => {
    const current = translations[lang] ?? {};
    update({
      translations: {
        ...translations,
        [lang]: { ...current, [field]: value || undefined },
      },
    });
  };

  // enum_entries из enum/enum_titles
  const enumEntries: EnumEntry[] = reg.enum_entries ??
    (reg.enum
      ? reg.enum.map((v, i) => ({
          value: v,
          title: reg.enum_titles?.[i] ?? String(v),
        }))
      : []);

  const handleEnumChange = (entries: EnumEntry[]) => {
    if (entries.length === 0) {
      update({ enum_entries: undefined, enum: undefined, enum_titles: undefined });
    } else {
      update({
        enum_entries: entries,
        enum: entries.map((e) => e.value),
        enum_titles: entries.map((e) => e.title),
      });
    }
  };

  const inputClass = 'border border-gray-300 rounded px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white';
  const labelClass = 'text-[11px] text-gray-500 mb-0.5 block';

  // Если для данного типа канала вообще нечего показывать кроме condition
  const hasAnySection = vis.description || vis.scaling || vis.limits || vis.enum || vis.onOff || vis.stringSize;

  // (Языки берутся из store.languages — см. выше)

  return (
    <div className="bg-slate-50 border-t-2 border-blue-200 px-4 py-3">

      {/* === Верхний ряд: Переводы (слева) + Числовые параметры (справа) === */}
      <div className="flex flex-wrap gap-x-6 gap-y-2">

        {/* Левая колонка: имя, описание, переводы */}
        <div className="flex-1 min-w-[280px] max-w-xl space-y-2">
          <div>
            <SectionTitle>Имя (EN) <Tip text="Английское имя канала/параметра. Используется как ключ и отображается в UI" /></SectionTitle>
            <div className="flex items-center gap-1.5">
              <input type="text" value={reg.name} onChange={(e) => update({ name: e.target.value })} className={`${inputClass} flex-1`} />
              <NormalizeToEnButton
                text={reg.name}
                onTranslated={(en) => update({ name: en })}
                onSaveRussian={(ru) => updateTranslation('ru', 'name', ru)}
              />
            </div>
          </div>
          {vis.description && (
            <div>
              <SectionTitle>Описание <Tip text="Подсказка к полю параметра — отображается в UI устройства" /></SectionTitle>
              <div className="flex items-center gap-1.5">
                <input type="text" value={reg.description ?? ''} onChange={(e) => update({ description: e.target.value || undefined })} placeholder="Подсказка к полю, напр. 'Скорость обмена по Modbus'" className={`${inputClass} flex-1`} />
                <NormalizeToEnButton
                  text={reg.description ?? ''}
                  onTranslated={(en) => update({ description: en })}
                  onSaveRussian={(ru) => updateTranslation('ru', 'description', ru)}
                />
              </div>
            </div>
          )}

          <div>
            <SectionTitle>Переводы <Tip text="Переводы имени (и описания для параметров) на другие языки" /></SectionTitle>
            {langs.length > 0 ? (
              <div className="space-y-1.5">
                {langs.map((lang) => (
                  <div key={lang} className="flex items-center gap-1.5">
                    <span className="text-[10px] font-mono text-gray-400 w-5 text-center uppercase flex-shrink-0">{lang}</span>
                    <div className="flex-1 min-w-0">
                      <label className="text-[9px] text-gray-400">имя</label>
                      <input
                        type="text"
                        value={translations[lang]?.name ?? ''}
                        onChange={(e) => updateTranslation(lang, 'name', e.target.value)}
                        placeholder={reg.name}
                        className={`${inputClass} w-full`}
                      />
                    </div>
                    <div className="flex flex-col items-center gap-0.5">
                      <TranslateButton text={reg.name} lang={lang} onResult={(v) => updateTranslation(lang, 'name', v)} />
                      {translations[lang]?.name && (
                        <button
                          onClick={() => updateTranslation(lang, 'name', '')}
                          className="text-gray-300 hover:text-red-500 transition-colors"
                          title="Удалить"
                        >
                          <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      )}
                    </div>
                    {reg.is_parameter && reg.description && (
                      <>
                        <div className="flex-1 min-w-0">
                          <label className="text-[9px] text-gray-400">описание</label>
                          <input
                            type="text"
                            value={translations[lang]?.description ?? ''}
                            onChange={(e) => updateTranslation(lang, 'description', e.target.value)}
                            placeholder={reg.description}
                            className={`${inputClass} w-full`}
                          />
                        </div>
                        <div className="flex flex-col items-center gap-0.5">
                          <TranslateButton text={reg.description} lang={lang} onResult={(v) => updateTranslation(lang, 'description', v)} />
                          {translations[lang]?.description && (
                            <button
                              onClick={() => updateTranslation(lang, 'description', '')}
                              className="text-gray-300 hover:text-red-500 transition-colors"
                              title="Удалить"
                            >
                              <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                              </svg>
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[10px] text-gray-400">Добавьте языки через кнопку «Языки»</p>
            )}
          </div>

          {/* Enum — под переводами в левой колонке */}
          {vis.enum && (
            <div>
              <SectionTitle>Enum <Tip text="Именованные значения: 0=Off, 1=On и т.д." /></SectionTitle>
              <EnumEditor entries={enumEntries} onChange={handleEnumChange} availableLanguages={langs} />

            </div>
          )}

          {/* Условие — под enum в левой колонке */}
          {vis.condition && (
            <ConditionField
              value={reg.condition ?? ''}
              onChange={(v) => update({ condition: v || undefined })}
              availableParams={availableParams}
              inputClass={inputClass}
            />
          )}
        </div>

        {/* Правая колонка: масштабирование, пределы, on/off, string, протокол */}
        <div className="flex-1 min-w-[280px] space-y-2">
          {(vis.scaling || vis.limits) && (
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              {vis.scaling && (
                <div>
                  <SectionTitle>Масштаб <Tip text="MQTT = REG × scale + offset. Примеры: значение в 0.1°C → scale=0.1; OpenTherm давление → scale=0.1, offset=-100; инверсия NC-реле → scale=-1, offset=1" /></SectionTitle>
                  <div className="flex gap-1.5">
                    <div>
                      <label className={labelClass}>Scale</label>
                      <input type="number" step="any" value={reg.scale} onChange={(e) => update({ scale: parseFloat(e.target.value) || 1 })} className={`${inputClass} w-20`} />
                    </div>
                    <div>
                      <label className={labelClass}>Offset</label>
                      <input type="number" step="any" value={reg.offset} onChange={(e) => update({ offset: parseFloat(e.target.value) || 0 })} className={`${inputClass} w-20`} />
                    </div>
                    <div>
                      <label className={labelClass}>Round to</label>
                      <input type="number" step="any" value={reg.round_to ?? ''} onChange={(e) => { const v = parseFloat(e.target.value); update({ round_to: isNaN(v) ? undefined : v }); }} placeholder="—" className={`${inputClass} w-20`} />
                    </div>
                  </div>
                </div>
              )}
              {vis.limits && (
                <div>
                  <SectionTitle>
                    Пределы
                    {reg.channel_type === 'range' && <span className="ml-1 text-orange-500 text-[10px] normal-case tracking-normal font-normal">обяз.</span>}
                    <Tip text="Допустимый диапазон значений" />
                  </SectionTitle>
                  <div className="flex gap-1.5">
                    <div>
                      <label className={labelClass}>Min</label>
                      <input type="number" step="any" value={reg.min ?? ''} onChange={(e) => { const v = parseFloat(e.target.value); update({ min: isNaN(v) ? undefined : v }); }} placeholder="—" className={`${inputClass} w-20`} />
                    </div>
                    <div>
                      <label className={labelClass}>Max</label>
                      <input type="number" step="any" value={reg.max ?? ''} onChange={(e) => { const v = parseFloat(e.target.value); update({ max: isNaN(v) ? undefined : v }); }} placeholder="—" className={`${inputClass} w-20`} />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {vis.onOff && (
            <div>
              <SectionTitle>Переключатель <Tip text="Значения вкл/выкл. Для coil не нужны (0/1 по умолчанию)" /></SectionTitle>
              <div className="flex gap-1.5">
                <div>
                  <label className={labelClass}>On</label>
                  <input type="number" value={reg.on_value ?? ''} onChange={(e) => { const v = parseInt(e.target.value, 10); update({ on_value: isNaN(v) ? undefined : v }); }} placeholder="—" className={`${inputClass} w-20`} />
                </div>
                <div>
                  <label className={labelClass}>Off</label>
                  <input type="number" value={reg.off_value ?? ''} onChange={(e) => { const v = parseInt(e.target.value, 10); update({ off_value: isNaN(v) ? undefined : v }); }} placeholder="—" className={`${inputClass} w-20`} />
                </div>
              </div>
            </div>
          )}

          {vis.stringSize && (
            <div>
              <SectionTitle>Размер строки <Tip text="Количество символов. Обязательно для format=string" /></SectionTitle>
              <input type="number" value={reg.string_data_size ?? ''} onChange={(e) => { const v = parseInt(e.target.value, 10); update({ string_data_size: isNaN(v) ? undefined : v }); }} placeholder="—" className={`${inputClass} w-24`} />
            </div>
          )}

          {(vis.wordOrder || vis.byteOrder || vis.errorValue || vis.defaultValue) && (
            <div>
              <SectionTitle>Протокол <Tip text="Порядок байтов/слов, значение ошибки" /></SectionTitle>
              <div className="flex flex-wrap gap-1.5">
                {vis.wordOrder && (
                  <div>
                    <label className={labelClass}>Word order</label>
                    <select value={reg.word_order ?? ''} onChange={(e) => update({ word_order: e.target.value || undefined })} className={`${inputClass} w-32`}>
                      <option value="">big endian</option>
                      <option value="big_endian">big endian</option>
                      <option value="little_endian">little endian</option>
                    </select>
                  </div>
                )}
                {vis.byteOrder && (
                  <div>
                    <label className={labelClass}>Byte order</label>
                    <select value={reg.byte_order ?? ''} onChange={(e) => update({ byte_order: e.target.value || undefined })} className={`${inputClass} w-32`}>
                      <option value="">big endian</option>
                      <option value="big_endian">big endian</option>
                      <option value="little_endian">little endian</option>
                    </select>
                  </div>
                )}
                {vis.errorValue && (
                  <div>
                    <label className={labelClass}>Error value</label>
                    <input type="text" value={reg.error_value ?? ''} onChange={(e) => update({ error_value: e.target.value || undefined })} placeholder="—" className={`${inputClass} w-24`} />
                  </div>
                )}
                {vis.defaultValue && (
                  <div>
                    <label className={labelClass}>Default</label>
                    <input type="number" step="any" value={reg.default_value ?? ''} onChange={(e) => { const v = parseFloat(e.target.value); update({ default_value: isNaN(v) ? undefined : v }); }} placeholder="—" className={`${inputClass} w-20`} />
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {!hasAnySection && (
        <p className="text-xs text-gray-400">Для данного типа канала и регистра дополнительные настройки не требуются.</p>
      )}
    </div>
  );
}
