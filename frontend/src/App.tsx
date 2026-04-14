import { useCallback, useRef, useState, useEffect } from 'react';
import RegisterTable from './components/RegisterTable';
import TemplatePreview from './components/TemplatePreview';
import ConfirmModal from './components/ConfirmModal';
import ValidationGateModal from './components/ValidationGateModal';
import MonitoringPage from './pages/MonitoringPage';
import { useStore } from './store';
import { buildJinjaTemplate } from './api';
import { useT, useLocale, LOCALES } from './i18n';

/** Скачивание Blob как файла */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

type Page = 'main' | 'monitoring';

/** Главная страница приложения WB Template Generator */
export default function App() {
  const t = useT();
  const [locale, setLocale] = useLocale();
  const [currentPage, setCurrentPage] = useState<Page>('main');
  const registers = useStore((s) => s.registers);
  const buildError = useStore((s) => s.buildError);
  const deviceInfo = useStore((s) => s.deviceInfo);
  const setDeviceInfo = useStore((s) => s.setDeviceInfo);
  const resetAll = useStore((s) => s.resetAll);
  const appVersion = useStore((s) => s.appVersion);
  const validationErrorCount = useStore((s) => s.validationErrorCount);
  const validationWarningCount = useStore((s) => s.validationWarningCount);
  const [confirmResetOpen, setConfirmResetOpen] = useState(false);
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [validationGateOpen, setValidationGateOpen] = useState(false);
  const [pendingDownloadAction, setPendingDownloadAction] = useState<'json' | 'jinja' | null>(null);
  const downloadRef = useRef<HTMLDivElement>(null);

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

  const actualDownloadJson = useCallback(() => {
    const currentTemplate = useStore.getState().template;
    if (!currentTemplate) return;
    const json = JSON.stringify(currentTemplate, null, 2);
    downloadBlob(new Blob([json], { type: 'application/json' }), `${currentTemplate.device_type || 'template'}.json`);
  }, []);

  const actualDownloadJinja = useCallback(async () => {
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
      const msg = e instanceof Error ? e.message : t('api.downloadJinjaError');
      setDownloadError(msg);
      setTimeout(() => setDownloadError(null), 5000);
    }
    setDownloadOpen(false);
  }, [t]);

  const handleDownloadJson = useCallback(() => {
    setPendingDownloadAction('json');
    setValidationGateOpen(true);
  }, []);

  const handleDownloadJinja = useCallback(() => {
    setPendingDownloadAction('jinja');
    setValidationGateOpen(true);
  }, []);

  // Dropdown языка
  const [langOpen, setLangOpen] = useState(false);
  const langRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!langOpen) return;
    const handler = (e: MouseEvent) => {
      if (langRef.current && !langRef.current.contains(e.target as Node)) {
        setLangOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [langOpen]);

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
        {/* Компактная шапка: заголовок + навигация + поля устройства + язык */}
        <div className="flex items-center gap-3 mb-2 flex-wrap">
          <h1 className="text-lg font-bold text-gray-900 whitespace-nowrap">
            {t('app.title')}
            <span className="text-xs font-normal text-gray-400 ml-1.5 align-super cursor-help" title={t('app.byAiTip')}>by AI</span>
          </h1>
          {appVersion && (
            <a href="https://github.com/wirenboard/wb-template-generator/blob/main/CHANGELOG.md" target="_blank" rel="noopener noreferrer" className="text-[10px] text-gray-400 bg-gray-100 px-1 py-0.5 rounded leading-none hover:text-blue-600 hover:bg-blue-50 transition-colors">
              v{appVersion}
            </a>
          )}
          <div className="h-4 w-px bg-gray-300 hidden sm:block" />
          
          {/* Навигация */}
          <div className="flex gap-1">
            <button 
              onClick={() => setCurrentPage('main')}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                currentPage === 'main' 
                  ? 'bg-blue-100 text-blue-700 font-medium' 
                  : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              {t('nav.main')}
            </button>
            <button
              onClick={() => setCurrentPage('monitoring')}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                currentPage === 'monitoring'
                  ? 'bg-blue-100 text-blue-700 font-medium'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              {t('nav.monitoring')}
            </button>
          </div>
          
          <div className="h-4 w-px bg-gray-300 hidden sm:block" />
          
          {/* Поля устройства - только на главной странице */}
          {currentPage === 'main' && (
            <>
              <label className="flex items-center gap-1.5 text-xs text-gray-500">
                {t('device.name')}
                <input
                  type="text"
                  value={deviceInfo.name}
                  onChange={(e) => setDeviceInfo({ name: e.target.value })}
                  placeholder="My Device"
                  className="border border-gray-300 rounded px-1.5 py-0.5 text-xs text-gray-800 w-36 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-transparent"
                />
              </label>
              <label className="flex items-center gap-1.5 text-xs text-gray-500">
                ID
                <input
                  type="text"
                  value={deviceInfo.id}
                  onChange={(e) => setDeviceInfo({ id: e.target.value })}
                  placeholder="my-device"
                  className="border border-gray-300 rounded px-1.5 py-0.5 text-xs text-gray-800 w-32 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-transparent"
                />
              </label>
            </>
          )}
          <div className="ml-auto relative" ref={langRef}>
            <button
              onClick={() => setLangOpen(!langOpen)}
              className="text-xs font-medium bg-gray-100 px-2 py-0.5 rounded hover:bg-gray-200 transition-colors select-none inline-flex items-center gap-1"
            >
              {LOCALES.find((l) => l.code === locale)?.label ?? 'RU'}
              <span className="text-[9px] text-gray-400">▾</span>
            </button>
            {langOpen && (
              <div className="absolute right-0 top-full mt-1 bg-white border border-gray-200 rounded shadow-lg z-50 py-0.5 min-w-[80px]">
                {LOCALES.map((l) => (
                  <button
                    key={l.code}
                    onClick={() => { setLocale(l.code); setLangOpen(false); }}
                    className={`block w-full text-left px-3 py-1 text-xs transition-colors ${
                      locale === l.code
                        ? 'bg-blue-50 text-blue-700 font-medium'
                        : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {l.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {downloadError && (
          <div className="mb-2 bg-red-50 text-red-700 border border-red-200 rounded p-1.5 text-xs flex items-center justify-between">
            <span>{downloadError}</span>
            <button onClick={() => setDownloadError(null)} className="ml-2 text-red-500 hover:text-red-700">&times;</button>
          </div>
        )}

        {/* Условный рендеринг страниц */}
        {currentPage === 'monitoring' ? (
          <MonitoringPage />
        ) : (
          /* Основная страница - таблица + превью */
          isXl ? (
            <div className="flex" ref={splitContainerRef}>
              {/* Левая панель: таблица регистров */}
              <section className="bg-white rounded-lg shadow-sm p-4 min-w-[400px]" style={{ flex: '1 1 0' }}>
                <RegisterTable
                  onDownloadJson={handleDownloadJson}
                  onDownloadJinja={handleDownloadJinja}
                  downloadOpen={downloadOpen}
                  setDownloadOpen={setDownloadOpen}
                  downloadRef={downloadRef}
                  onResetAll={() => setConfirmResetOpen(true)}
                />
              </section>

              {/* Разделитель */}
              <div
                onMouseDown={handleSplitterMouseDown}
                className="w-1.5 cursor-col-resize bg-gray-200 hover:bg-blue-300 active:bg-blue-400 transition-colors rounded mx-1 flex-shrink-0 self-stretch"
                title={t('splitter.title')}
              />

              {/* Правая панель: превью (sticky) */}
              <section
                className="sticky top-4 self-start bg-white rounded-lg shadow-sm p-4 max-h-[calc(100vh-2rem)] overflow-y-auto flex-shrink-0"
                style={{ width: previewWidth }}
              >
                <h2 className="text-base font-semibold text-gray-800 mb-3">
                  {t('preview.title')}
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
                    {t('preview.empty')}
                  </p>
                )}
              </section>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4">
              {/* Левая панель: таблица регистров */}
              <section className="bg-white rounded-lg shadow-sm p-4">
                <RegisterTable
                  onDownloadJson={handleDownloadJson}
                  onDownloadJinja={handleDownloadJinja}
                  downloadOpen={downloadOpen}
                  setDownloadOpen={setDownloadOpen}
                  downloadRef={downloadRef}
                  onResetAll={() => setConfirmResetOpen(true)}
                />
              </section>

              {/* Правая панель: превью */}
              <section className="bg-white rounded-lg shadow-sm p-4">
                <h2 className="text-base font-semibold text-gray-800 mb-3">
                  {t('preview.title')}
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
                    {t('preview.empty')}
                  </p>
                )}
              </section>
            </div>
          )
        )}
      </div>
      <ConfirmModal
        isOpen={confirmResetOpen}
        title={t('confirm.resetTitle')}
        message={t('confirm.resetMessage')}
        confirmText={t('confirm.resetButton')}
        onConfirm={() => { resetAll(); setConfirmResetOpen(false); }}
        onCancel={() => setConfirmResetOpen(false)}
      />
      <ValidationGateModal
        isOpen={validationGateOpen}
        validationErrorCount={validationErrorCount}
        validationWarningCount={validationWarningCount}
        buildRequest={registers.length > 0 ? { device_info: deviceInfo, registers, groups: useStore.getState().groups ?? [] } : null}
        onDownload={() => {
          setValidationGateOpen(false);
          if (pendingDownloadAction === 'json') actualDownloadJson();
          else if (pendingDownloadAction === 'jinja') actualDownloadJinja();
          setPendingDownloadAction(null);
        }}
        onCancel={() => { setValidationGateOpen(false); setPendingDownloadAction(null); }}
      />
      <footer className="text-center text-xs text-gray-400 py-4">
        <a href="https://github.com/wirenboard/wb-template-generator" target="_blank" rel="noopener noreferrer" className="hover:text-gray-600 transition-colors">
          {t('footer.source')}
        </a>
      </footer>
    </div>
  );
}
