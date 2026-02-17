/** Допустимые типы Modbus-регистров */
export const REG_TYPES = ['holding', 'input', 'coil', 'discrete', 'holding_single', 'holding_multi'] as const;

/** Допустимые форматы данных */
export const FORMATS = ['u16', 's16', 'u32', 's32', 'u64', 's64', 'float', 'double', 'u8', 's8', 'string'] as const;

/** Форматы с описаниями для dropdown */
export const FORMAT_OPTIONS: { value: string; label: string; description: string }[] = [
  { value: 'u16', label: 'u16', description: '16 бит без знака (1 регистр)' },
  { value: 's16', label: 's16', description: '16 бит со знаком (1 регистр)' },
  { value: 'u32', label: 'u32', description: '32 бит без знака (2 регистра)' },
  { value: 's32', label: 's32', description: '32 бит со знаком (2 регистра)' },
  { value: 'u64', label: 'u64', description: '64 бит без знака (4 регистра)' },
  { value: 's64', label: 's64', description: '64 бит со знаком (4 регистра)' },
  { value: 'float', label: 'float', description: 'IEEE 754, 32 бит (2 регистра)' },
  { value: 'double', label: 'double', description: 'IEEE 754, 64 бит (4 регистра)' },
  { value: 'u8', label: 'u8', description: '8 бит без знака' },
  { value: 's8', label: 's8', description: '8 бит со знаком' },
  { value: 'string', label: 'string', description: 'Строка (указать string_data_size)' },
];

/** Допустимые типы каналов */
export const CHANNEL_TYPES = [
  'value', 'switch', 'wo-switch', 'pushbutton', 'range', 'alarm', 'rgb', 'text',
] as const;

/** Допустимые типы каналов по типу регистра */
const ALL_CHANNEL_TYPES = ['value', 'switch', 'wo-switch', 'pushbutton', 'range', 'alarm', 'rgb', 'text'] as const;
const ALL_EXCEPT_WO_SWITCH = ['value', 'switch', 'pushbutton', 'range', 'alarm', 'rgb', 'text'] as const;

const CHANNEL_TYPES_BY_REG_TYPE: Record<string, readonly string[]> = {
  coil: ['switch', 'wo-switch', 'pushbutton'],
  discrete: ['switch'],
  holding: ALL_CHANNEL_TYPES,
  holding_single: ALL_CHANNEL_TYPES,
  holding_multi: ALL_CHANNEL_TYPES,
  input: ALL_EXCEPT_WO_SWITCH,
};

/** Возвращает допустимые типы каналов для данного reg_type */
export function getChannelTypesForRegType(regType: string): readonly string[] {
  return CHANNEL_TYPES_BY_REG_TYPE[regType] ?? ALL_CHANNEL_TYPES;
}

/** Дефолтные языки для переводов (кроме базового en) */
export const DEFAULT_LANGUAGES = [
  { code: 'ru', label: 'Русский (ru)' },
] as const;

/** Ключ localStorage для пользовательских языков */
export const LANGUAGES_STORAGE_KEY = 'wb-template-languages';

/** Маппинг кодов языков → названия (для промпта перевода) */
export const LANGUAGE_NAMES: Record<string, string> = {
  ru: 'Russian',
  de: 'German',
  fr: 'French',
  es: 'Spanish',
  pt: 'Portuguese',
  it: 'Italian',
  zh: 'Chinese',
  ja: 'Japanese',
  ko: 'Korean',
  ar: 'Arabic',
  tr: 'Turkish',
  pl: 'Polish',
  cs: 'Czech',
  nl: 'Dutch',
  sv: 'Swedish',
  fi: 'Finnish',
  da: 'Danish',
  no: 'Norwegian',
  uk: 'Ukrainian',
  kk: 'Kazakh',
  uz: 'Uzbek',
  he: 'Hebrew',
  hi: 'Hindi',
  th: 'Thai',
  vi: 'Vietnamese',
  id: 'Indonesian',
  ro: 'Romanian',
  hu: 'Hungarian',
  bg: 'Bulgarian',
  hr: 'Croatian',
  sr: 'Serbian',
  sk: 'Slovak',
  sl: 'Slovenian',
  el: 'Greek',
  ka: 'Georgian',
};

/** Допустимые единицы измерения (пустая строка = без единиц) */
export const UNITS = [
  '', 'V', 'mV', 'A', 'mA', 'W', 'kWh', 'Hz', 'rpm',
  'Ohm', 'mOhm', 'bar', 'mbar', 'Pa',
  'deg C', '%', 'RH',
  'ppm', 'ppb', 'lx', 'dB',
  's', 'min', 'h',
  'm', 'mm/h', 'm/s', 'm^3/h', 'm^3',
  'g', 'kg', 'mol', 'cd',
  'Gcal/h', 'cal', 'Gcal',
  'deg', 'rad',
] as const;
