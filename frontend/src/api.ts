import type { Register, RegisterGroup, DeviceInfo, WBTemplate, AnalyzeProgress } from './types';
import { LANGUAGE_NAMES } from './constants';
import { getT } from './i18n';

/** Ошибка бэкенда в виде ключа локализации: `message_key` + `message_params`.
 *
 * Тот же контракт, что у валидатора регистров. Параметр с именем на `Key` —
 * вложенный ключ: значение переводится и подставляется под именем без суффикса.
 * Бэкенд рендерит так же, см. `backend/user_errors.py`.
 */
export function resolveMessage(
  data: { message_key?: unknown; message_params?: unknown },
  fallback: string,
): string {
  if (typeof data.message_key !== 'string') return fallback;
  const t = getT();
  const raw = (data.message_params ?? {}) as Record<string, string | number>;
  const params: Record<string, string | number> = {};
  for (const [name, value] of Object.entries(raw)) {
    if (name.endsWith('Key') && typeof value === 'string') {
      params[name.slice(0, -3)] = t(value);
    } else {
      params[name] = value;
    }
  }
  const translated = t(data.message_key, params);
  // Ключа нет ни в одной локали (старый бандл, новый бэкенд) — показываем detail
  return translated === data.message_key ? fallback : translated;
}

/** Текст ошибки из тела ответа: перевод по ключу, иначе detail, иначе фолбек.
 *
 * Проверка типа отсекает 422 от pydantic, где detail это массив объектов —
 * там остаётся фолбек с кодом, а не «[object Object]».
 */
async function errorDetail(
  res: Response,
  fallback: string,
): Promise<{ detail: string; requestId?: string }> {
  let detail = fallback;
  let requestId: string | undefined;
  try {
    const errData = await res.json();
    if (typeof errData.detail === 'string') detail = errData.detail;
    if (typeof errData.request_id === 'string') requestId = errData.request_id;
    detail = resolveMessage(errData, detail);
  } catch { /* тело не JSON — остаётся фолбек */ }
  return { detail, requestId };
}

export interface ServerStatus {
  llm_available: boolean;
  max_file_size_mb: number;
  server_model?: string;
  version?: string;
}

export async function fetchStatus(): Promise<ServerStatus> {
  const res = await fetch('/api/status');
  if (!res.ok) throw new Error(getT()('api.statusError', { code: res.status }));
  return res.json();
}

export interface BuildRequest {
  device_info: DeviceInfo;
  registers: Register[];
  groups?: RegisterGroup[];
}

export async function buildTemplate(request: BuildRequest): Promise<WBTemplate> {
  const res = await fetch('/api/build', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const { detail } = await errorDetail(res, getT()('api.buildError', { code: res.status }));
    throw new Error(detail);
  }
  return res.json();
}

export interface AnalyzeOptions {
  templateType: string;
  llmApiUrl?: string;
  llmApiKey?: string;
  llmModel?: string;
  llmMaxTokens?: number;
  llmTimeout?: number;
  llmLegacyMaxTokens?: boolean;
  llmTemperature?: number;
  systemPrompt?: string;
  translationLanguages?: string[];
}

/** Получить сырые шаблоны промптов с сервера */
export async function fetchPrompts(): Promise<{
  system_prompt: string;
  template_type_instructions: Record<string, string>;
}> {
  const res = await fetch('/api/prompts');
  if (!res.ok) throw new Error(getT()('api.promptsError', { code: res.status }));
  return res.json();
}

/** Получить список моделей от LLM API провайдера */
export async function fetchModels(
  config?: { apiUrl?: string; apiKey?: string },
): Promise<string[]> {
  // В серверном режиме (без своего URL/ключа) тело не отправляем: пустой
  // multipart/form-data FastAPI не может распарсить и отвечает 400. Бэкенд
  // корректно обрабатывает POST вообще без тела (все Form-поля опциональны).
  const init: RequestInit = { method: 'POST' };
  if (config?.apiUrl || config?.apiKey) {
    const formData = new FormData();
    if (config.apiUrl) formData.append('llm_api_url', config.apiUrl);
    if (config.apiKey) formData.append('llm_api_key', config.apiKey);
    init.body = formData;
  }
  const res = await fetch('/api/models', init);
  if (!res.ok) {
    const { detail } = await errorDetail(res, getT()('api.modelsError', { code: res.status }));
    throw new Error(detail);
  }
  const data = await res.json();
  return data.models ?? [];
}

export async function analyzeFiles(
  files: File[],
  options: AnalyzeOptions,
  callbacks: {
    onProgress: (progress: AnalyzeProgress) => void;
    onResult: (data: { device_info: DeviceInfo; registers: Register[] }) => void;
    onError: (error: string, requestId?: string) => void;
    onDone: (requestId?: string) => void;
    onRequestId?: (requestId: string) => void;
  },
  signal?: AbortSignal
): Promise<void> {
  const formData = new FormData();
  files.forEach((f) => formData.append('files', f));
  formData.append('template_type', options.templateType);
  if (options.llmApiUrl) formData.append('llm_api_url', options.llmApiUrl);
  if (options.llmApiKey) formData.append('llm_api_key', options.llmApiKey);
  if (options.llmModel) formData.append('llm_model', options.llmModel);
  if (options.llmMaxTokens) formData.append('llm_max_tokens', String(options.llmMaxTokens));
  if (options.llmTimeout) formData.append('llm_timeout', String(options.llmTimeout));
  if (options.llmLegacyMaxTokens !== undefined) formData.append('llm_legacy_max_tokens', String(options.llmLegacyMaxTokens));
  if (options.llmTemperature !== undefined) formData.append('llm_temperature', String(options.llmTemperature));
  if (options.systemPrompt) formData.append('system_prompt', options.systemPrompt);
  if (options.translationLanguages && options.translationLanguages.length > 0) {
    formData.append('translation_languages', options.translationLanguages.join(','));
  }

  try {
    const response = await fetch('/api/analyze', { method: 'POST', body: formData, signal });

    if (!response.ok) {
      const { detail, requestId } = await errorDetail(
        response, getT()('api.serverError', { code: response.status }),
      );
      callbacks.onError(detail, requestId);
      return;
    }
    const reader = response.body?.getReader();
    if (!reader) {
      callbacks.onError(getT()('api.noStream'));
      return;
    }
    const decoder = new TextDecoder();
    let buffer = '';
    let eventType = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // SSE-события разделяются двойным \n (\n\n)
      // Разбиваем по \n\n чтобы не терять event+data связку
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';

      for (const event of events) {
        const lines = event.split('\n');
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              // Извлекаем request_id из любого SSE-события
              if (data.request_id && callbacks.onRequestId) {
                callbacks.onRequestId(data.request_id);
              }
              if (eventType === 'progress') callbacks.onProgress(data);
              else if (eventType === 'result') callbacks.onResult(data);
              else if (eventType === 'error') {
                callbacks.onError(resolveMessage(data, data.message), data.request_id);
              }
              else if (eventType === 'done') callbacks.onDone(data.request_id);
            } catch (e) {
              console.warn('SSE parse error:', e, 'line length:', line.length);
            }
            eventType = '';
          }
        }
      }
    }
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') return;
    let message: string;
    if (err instanceof TypeError || (err instanceof Error && /input stream|network|fetch|failed/i.test(err.message))) {
      message = getT()('api.connectionLost');
    } else {
      message = err instanceof Error ? err.message : getT()('api.unknownError');
    }
    callbacks.onError(message);
  }
}

/** Валидация регистров по схеме wb-mqtt-serial */
export async function validateRegisters(
  registers: Register[],
): Promise<import('./utils/registerValidation').ValidationResponse> {
  const res = await fetch('/api/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ registers }),
  });
  if (!res.ok) {
    const { detail } = await errorDetail(res, getT()('api.validateError', { code: res.status }));
    throw new Error(detail);
  }
  return res.json();
}

/** Валидация собранного шаблона по JSON-схеме wb-mqtt-serial */
export async function validateSchema(
  request: BuildRequest,
): Promise<{ errors: string[]; error_count: number }> {
  const res = await fetch('/api/validate-schema', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const { detail } = await errorDetail(res, getT()('api.validateError', { code: res.status }));
    throw new Error(detail);
  }
  return res.json();
}

/** Исправление регистров через AI (SSE) */
export async function fixRegisters(
  registers: Register[],
  callbacks: {
    onProgress: (progress: AnalyzeProgress) => void;
    onResult: (data: { device_info: DeviceInfo; registers: Register[] }) => void;
    onError: (message: string) => void;
    onDone: () => void;
  },
): Promise<void> {
  try {
    const res = await fetch('/api/fix-registers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ registers }),
    });
    if (!res.ok) {
      const { detail } = await errorDetail(res, getT()('api.fixError', { code: res.status }));
      callbacks.onError(detail);
      return;
    }
    const reader = res.body?.getReader();
    if (!reader) return;
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() ?? '';
      for (const event of events) {
        if (!event.trim()) continue;
        let eventType = '';
        let eventData = '';
        for (const line of event.split('\n')) {
          if (line.startsWith('event:')) eventType = line.slice(6).trim();
          else if (line.startsWith('data:')) eventData = line.slice(5).trim();
        }
        if (!eventData) continue;
        try {
          const parsed = JSON.parse(eventData);
          if (eventType === 'progress') callbacks.onProgress(parsed);
          else if (eventType === 'result') callbacks.onResult(parsed);
          else if (eventType === 'error') {
            callbacks.onError(resolveMessage(parsed, parsed.message || 'Unknown error'));
          }
          else if (eventType === 'done') callbacks.onDone();
        } catch { /* skip unparseable */ }
      }
    }
  } catch (e) {
    callbacks.onError(e instanceof Error ? e.message : getT()('api.unknownError'));
  }
}

/** Сборка Jinja-шаблона (.json.jinja) */
export async function buildJinjaTemplate(request: BuildRequest): Promise<string> {
  const res = await fetch('/api/build-jinja', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const { detail } = await errorDetail(res, getT()('api.buildJinjaError', { code: res.status }));
    throw new Error(detail);
  }
  return res.text();
}

/** Импорт существующего JSON/Jinja шаблона в формат редактора */
export async function importTemplate(
  file: File,
): Promise<{ device_info: DeviceInfo; registers: Register[]; groups: RegisterGroup[] }> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch('/api/import-template', { method: 'POST', body: formData });
  if (!res.ok) {
    const { detail } = await errorDetail(res, getT()('api.importError', { code: res.status }));
    throw new Error(detail);
  }
  return res.json();
}

/** Перевод строк через LLM */
export async function translateStrings(
  strings: Record<string, string>,
  targetLang: string,
  llmConfig?: { apiUrl?: string; apiKey?: string; model?: string; temperature?: number; timeout?: number; legacyMaxTokens?: boolean },
): Promise<Record<string, string>> {
  const targetLangName = LANGUAGE_NAMES[targetLang] || targetLang;
  const res = await fetch('/api/translate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      strings,
      target_lang: targetLang,
      target_lang_name: targetLangName,
      llm_api_url: llmConfig?.apiUrl,
      llm_api_key: llmConfig?.apiKey,
      llm_model: llmConfig?.model,
      llm_temperature: llmConfig?.temperature,
      llm_timeout: llmConfig?.timeout,
      llm_legacy_max_tokens: llmConfig?.legacyMaxTokens,
    }),
  });
  if (!res.ok) {
    const { detail } = await errorDetail(res, getT()('api.translateError', { code: res.status }));
    throw new Error(detail);
  }
  const data = await res.json();
  return data.translations;
}
