/** Допустимые типы Modbus-регистров */
export const REG_TYPES = ['holding', 'input', 'coil', 'discrete', 'holding_single', 'holding_multi'] as const;

/** Допустимые форматы данных */
export const FORMATS = ['u16', 's16', 'u32', 's32', 'u64', 's64', 'float', 'double', 'u8', 's8', 'string'] as const;

/** Форматы с i18n-ключами описаний для dropdown */
export const FORMAT_OPTIONS: { value: string; label: string; descriptionKey: string }[] = [
  { value: 'u16', label: 'u16', descriptionKey: 'format.u16' },
  { value: 's16', label: 's16', descriptionKey: 'format.s16' },
  { value: 'u32', label: 'u32', descriptionKey: 'format.u32' },
  { value: 's32', label: 's32', descriptionKey: 'format.s32' },
  { value: 'u64', label: 'u64', descriptionKey: 'format.u64' },
  { value: 's64', label: 's64', descriptionKey: 'format.s64' },
  { value: 'float', label: 'float', descriptionKey: 'format.float' },
  { value: 'double', label: 'double', descriptionKey: 'format.double' },
  { value: 'u8', label: 'u8', descriptionKey: 'format.u8' },
  { value: 's8', label: 's8', descriptionKey: 'format.s8' },
  { value: 'string', label: 'string', descriptionKey: 'format.string' },
];

/** Допустимые типы каналов */
export const CHANNEL_TYPES = [
  'value', 'switch', 'wo-switch', 'pushbutton', 'range', 'rgb', 'text',
] as const;

/** Допустимые типы каналов по типу регистра */
const ALL_CHANNEL_TYPES = ['value', 'switch', 'wo-switch', 'pushbutton', 'range', 'rgb', 'text'] as const;
const ALL_EXCEPT_WO_SWITCH = ['value', 'switch', 'pushbutton', 'range', 'rgb', 'text'] as const;

const CHANNEL_TYPES_BY_REG_TYPE: Record<string, readonly string[]> = {
  coil: ['switch', 'wo-switch', 'pushbutton'],
  discrete: ['switch', 'value'],
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

/**
 * Конфиг переводов по UI-локалям.
 * Определяет какие языки переводов шаблонов доступны для каждой UI-локали.
 * Контроллер wb-mqtt-serial пока поддерживает только RU и EN.
 * По мере добавления языков в контроллер — добавлять сюда.
 */
export const LOCALE_TRANSLATION_LANGUAGES: Record<string, { code: string; label: string }[]> = {
  ru: [{ code: 'ru', label: 'Русский (ru)' }],
  en: [],
  kk: [],
  it: [],
};

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
