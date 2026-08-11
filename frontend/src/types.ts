/** Язык для переводов */
export interface Language {
  code: string;
  label: string;
}

export interface DeviceInfo {
  name: string;
  id: string;
  device_group?: string;
  hw?: Array<Record<string, unknown>>;
  max_read_registers?: number;
  response_timeout_ms?: number;
  frame_timeout_ms?: number;
  enable_wb_continuous_read?: boolean;
  title_key?: string;
  title_translations?: Record<string, string>;
}

/** Переводы для произвольного количества языков */
export type TranslationMap = Record<string, string>;

/** Элемент enum с переводами */
export interface EnumEntry {
  value: number;
  title: string;
  translations?: TranslationMap;
}

/** Группа регистров */
export interface RegisterGroup {
  id: string;
  title: string;
  order: number;
  description?: string;
  translations?: Record<string, { title?: string; description?: string }>;
  parent_group?: string;
  ui_options?: Record<string, unknown>;
}

export interface Register {
  id: string;
  address: string | number; // "109:1:2" для побитового доступа или 109
  name: string;
  reg_type: string;
  format: string;
  scale: number;
  offset: number;
  units?: string;
  access: 'read' | 'write' | 'readwrite';
  description?: string;
  channel_type: string;
  group: string;
  group_title?: string;
  group_title_translations?: Record<string, string>;
  is_parameter: boolean;

  condition?: string;
  enabled: boolean;
  enum?: number[];
  enum_titles?: string[];
  enum_entries?: EnumEntry[];
  string_data_size?: number;
  word_order?: string;
  byte_order?: string;
  error_value?: string;
  readonly?: boolean;
  min?: number;
  max?: number;
  round_to?: number;
  on_value?: number;
  off_value?: number;
  default_value?: number;
  translations?: Record<string, { name?: string; description?: string }>;
  sporadic?: boolean;
  read_only?: boolean;
  required?: boolean;
  fw?: string;
  original_channel_id?: string;
  param_order?: number;
}

export interface AnalyzeProgress {
  stage: string;
  message: string;
  current?: number;
  total?: number;
  request_id?: string;
  queue_position?: number;
  queue_eta?: number;
}

/** Типизированный канал wb-mqtt-serial шаблона */
export interface WBChannel {
  name: string;
  id: string;
  reg_type: string;
  address: string | number;
  type: string;
  format: string;
  group: string;
  units?: string;
  scale?: number;
  offset?: number;
  readonly?: boolean;
  error_value?: string;
  word_order?: string;
  byte_order?: string;
  string_data_size?: number;
  condition?: string;
  enum?: number[];
  enum_titles?: string[];
  min?: number;
  max?: number;
  round_to?: number;
  on_value?: number;
  off_value?: number;
  enabled?: boolean;
}

/** Типизированный параметр wb-mqtt-serial шаблона */
export interface WBParameter {
  title: string;
  address: string | number;
  reg_type: string;
  group: string;
  description?: string;
  format?: string;
  enum?: number[];
  enum_titles?: string[];
  default?: number;
  min?: number;
  max?: number;
  scale?: number;
  offset?: number;
  condition?: string;
  word_order?: string;
  byte_order?: string;
  round_to?: number;
  readonly?: boolean;
  order?: number;
}

export interface WBTemplate {
  device_type: string;
  title: string;
  group?: string;
  _warnings?: string[];
  _schema_errors?: string[];
  device: {
    name: string;
    id: string;
    groups: Array<{ title: string; id: string; description?: string; group?: string }>;
    channels: WBChannel[];
    parameters: Record<string, WBParameter>;
    translations: Record<string, Record<string, string>>;
  };
}

/** Настройки LLM, которые принимают все маршруты. Зеркало `LlmOverrides` на бэкенде */
export interface LlmConfig {
  apiUrl?: string;
  apiKey?: string;
  model?: string;
  timeout?: number;
  legacyMaxTokens?: boolean;
  temperature?: number;
}

/** Анализ дополнительно принимает лимит токенов ответа, остальные маршруты этого поля не имеют */
export interface AnalyzeLlmConfig extends LlmConfig {
  maxTokens?: number;
}
