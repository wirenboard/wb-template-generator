import { useCallback, useRef, useState, useEffect } from 'react';
import RegisterTable from './components/RegisterTable';
import TemplatePreview from './components/TemplatePreview';
import ConfirmModal from './components/ConfirmModal';
import { useStore } from './store';
import { buildJinjaTemplate } from './api';

/** Скачивание Blob как файла */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Главная страница приложения WB Template Generator */
export default function App() {
  const registers = useStore((s) => s.registers);
  const template = useStore((s) => s.template);
  const buildError = useStore((s) => s.buildError);
  const deviceInfo = useStore((s) => s.deviceInfo);
  const setDeviceInfo = useStore((s) => s.setDeviceInfo);
  const resetAll = useStore((s) => s.resetAll);
  const importTemplate = useStore((s) => s.importTemplate);
  const importing = useStore((s) => s.importing);
  const importError = useStore((s) => s.importError);
  const [confirmResetOpen, setConfirmResetOpen] = useState(false);
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const downloadRef = useRef<HTMLDivElement>(null);
  const importInputRef = useRef<HTMLInputElement>(null);

  // Закрытие dropdown при клике вне
  useEffect(() => {
    if (!downloadOpen) return;
    const handler = (e: MouseEvent) => {
      if (downloadRef.current && !downloadRef.current.contains(e.target as Node)) {
        setDownloadOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [downloadOpen]);

  const handleDownloadJson = useCallback(() => {
    const currentTemplate = useStore.getState().template;
    if (!currentTemplate) return;
    const json = JSON.stringify(currentTemplate, null, 2);
    downloadBlob(new Blob([json], { type: 'application/json' }), `${currentTemplate.device_type || 'template'}.json`);
  }, []);

  const handleDownloadJinja = useCallback(async () => {
    const store = useStore.getState();
    const { registers, deviceInfo, groups } = store;
    const enabledRegisters = registers.filter((r) => r.enabled);
    if (enabledRegisters.length === 0) return;
    try {
      const text = await buildJinjaTemplate({
        device_info: deviceInfo,
        registers: enabledRegisters,
        groups,
      });
      downloadBlob(new Blob([text], { type: 'text/plain' }), `${deviceInfo.id || 'template'}.json.jinja`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Ошибка скачивания Jinja';
      setDownloadError(msg);
      setTimeout(() => setDownloadError(null), 5000);
    }
    setDownloadOpen(false);
  }, []);

  const handleImportFile = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) importTemplate(file);
    e.target.value = '';
  }, [importTemplate]);

  // Сплиттер: ширина правой панели
  const PREVIEW_MIN = 250;
  const PREVIEW_MAX = 600;
  const PREVIEW_DEFAULT = 400;
  const PREVIEW_STORAGE_KEY = 'wb-preview-width';

  const [previewWidth, setPreviewWidth] = useState(() => {
    try {
      const stored = localStorage.getItem(PREVIEW_STORAGE_KEY);
      if (stored) {
        const w = parseInt(stored, 10);
        if (w >= PREVIEW_MIN && w <= PREVIEW_MAX) return w;
      }
    } catch { /* игнорируем */ }
    return PREVIEW_DEFAULT;
  });
  const isDragging = useRef(false);
  const splitContainerRef = useRef<HTMLDivElement>(null);

  // Определение xl-экрана для условного сплиттера
  const [isXl, setIsXl] = useState(() => window.innerWidth >= 1280);
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 1280px)');
    const handler = (e: MediaQueryListEvent) => setIsXl(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const handleSplitterMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const startX = e.clientX;
    const startWidth = previewWidth;

    const handleMouseMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const delta = startX - ev.clientX;
      const newWidth = Math.min(PREVIEW_MAX, Math.max(PREVIEW_MIN, startWidth + delta));
      setPreviewWidth(newWidth);
    };

    const handleMouseUp = () => {
      isDragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, [previewWidth]);

  // Сохраняем ширину при изменении (с debounce)
  useEffect(() => {
    try {
      localStorage.setItem(PREVIEW_STORAGE_KEY, String(previewWidth));
    } catch { /* игнорируем */ }
  }, [previewWidth]);

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-[1600px] mx-auto px-3 py-3">
        {/* Шапка: заголовок + скачать */}
        <div className="flex items-center gap-4 mb-3">
          <h1 className="text-xl font-bold text-gray-900">
            WB Template Generator
          </h1>
          <div className="ml-auto flex items-center gap-2">
            <input
              ref={importInputRef}
              type="file"
              accept=".json,.json.jinja"
              onChange={handleImportFile}
              className="hidden"
            />
            <button
              onClick={() => importInputRef.current?.click()}
              disabled={importing}
              className="px-3 py-1.5 text-sm text-gray-700 bg-gray-100 border border-gray-300 rounded hover:bg-gray-200 transition-colors disabled:opacity-50"
            >
              {importing ? 'Импорт...' : 'Загрузить шаблон'}
            </button>
            {registers.length > 0 && (
              <button
                onClick={() => setConfirmResetOpen(true)}
                className="px-3 py-1.5 text-sm text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
              >
                Новый шаблон
              </button>
            )}
            {template && (
              <div className="relative" ref={downloadRef}>
                <button
                  onClick={() => setDownloadOpen((v) => !v)}
                  className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors flex items-center gap-1"
                >
                  Скачать
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
                </button>
                {downloadOpen && (
                  <div className="absolute right-0 mt-1 bg-white border border-gray-200 rounded shadow-lg z-50 min-w-[180px]">
                    <button
                      onClick={() => { handleDownloadJson(); setDownloadOpen(false); }}
                      className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 transition-colors"
                    >
                      JSON (.json)
                    </button>
                    <button
                      onClick={handleDownloadJinja}
                      className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 transition-colors border-t border-gray-100"
                    >
                      Jinja (.json.jinja)
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {importError && (
          <div className="mb-3 bg-red-50 text-red-700 border border-red-200 rounded p-2 text-sm flex items-center justify-between">
            <span>{importError}</span>
            <button onClick={() => useStore.setState({ importError: null })} className="ml-2 text-red-500 hover:text-red-700">&times;</button>
          </div>
        )}

        {downloadError && (
          <div className="mb-3 bg-red-50 text-red-700 border border-red-200 rounded p-2 text-sm flex items-center justify-between">
            <span>{downloadError}</span>
            <button onClick={() => setDownloadError(null)} className="ml-2 text-red-500 hover:text-red-700">&times;</button>
          </div>
        )}

        {/* Поля устройства */}
        <div className="flex flex-wrap items-center gap-4 mb-4">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            Имя устройства:
            <input
              type="text"
              value={deviceInfo.name}
              onChange={(e) => setDeviceInfo({ name: e.target.value })}
              placeholder="My Device"
              className="border border-gray-300 rounded px-2 py-1 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            ID:
            <input
              type="text"
              value={deviceInfo.id}
              onChange={(e) => setDeviceInfo({ id: e.target.value })}
              placeholder="my-device"
              className="border border-gray-300 rounded px-2 py-1 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </label>
        </div>

        {/* Основной layout: таблица + превью */}
        {isXl ? (
          <div className="flex" ref={splitContainerRef}>
            {/* Левая панель: таблица регистров */}
            <section className="bg-white rounded-lg shadow-sm p-4 min-w-[400px]" style={{ flex: '1 1 0' }}>
              <RegisterTable />
            </section>

            {/* Разделитель */}
            <div
              onMouseDown={handleSplitterMouseDown}
              className="w-1.5 cursor-col-resize bg-gray-200 hover:bg-blue-300 active:bg-blue-400 transition-colors rounded mx-1 flex-shrink-0 self-stretch"
              title="Перетащите для изменения ширины превью"
            />

            {/* Правая панель: превью (sticky) */}
            <section
              className="sticky top-4 self-start bg-white rounded-lg shadow-sm p-4 max-h-[calc(100vh-2rem)] overflow-y-auto flex-shrink-0"
              style={{ width: previewWidth }}
            >
              <h2 className="text-base font-semibold text-gray-800 mb-3">
                Превью
              </h2>

              {buildError && (
                <div className="mb-3 bg-red-50 text-red-700 border border-red-200 rounded p-2 text-xs">
                  {buildError}
                </div>
              )}

              {registers.length > 0 ? (
                <TemplatePreview />
              ) : (
                <p className="text-gray-400 text-sm text-center py-8">
                  Превью появится после добавления регистров
                </p>
              )}
            </section>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {/* Левая панель: таблица регистров */}
            <section className="bg-white rounded-lg shadow-sm p-4">
              <RegisterTable />
            </section>

            {/* Правая панель: превью */}
            <section className="bg-white rounded-lg shadow-sm p-4">
              <h2 className="text-base font-semibold text-gray-800 mb-3">
                Превью
              </h2>

              {buildError && (
                <div className="mb-3 bg-red-50 text-red-700 border border-red-200 rounded p-2 text-xs">
                  {buildError}
                </div>
              )}

              {registers.length > 0 ? (
                <TemplatePreview />
              ) : (
                <p className="text-gray-400 text-sm text-center py-8">
                  Превью появится после добавления регистров
                </p>
              )}
            </section>
          </div>
        )}
      </div>
      <ConfirmModal
        isOpen={confirmResetOpen}
        title="Новый шаблон"
        message="Очистить все регистры, группы и устройство? Настройки LLM сохранятся."
        confirmText="Очистить"
        onConfirm={() => { resetAll(); setConfirmResetOpen(false); }}
        onCancel={() => setConfirmResetOpen(false)}
      />
    </div>
  );
}
