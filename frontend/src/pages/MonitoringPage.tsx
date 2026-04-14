import { useState, useEffect, useRef } from 'react';
import { useT } from '../i18n';

interface SystemMetrics {
  status: 'ok' | 'error';
  uptime_seconds: number;
  queues: {
    server: {
      active: number;
      waiting: number;
      max_concurrent: number;
      avg_duration?: number;
    } | null;
    custom: {
      active: number;
      waiting: number;
      max_concurrent: number;
      avg_duration?: number;
    } | null;
  };
}

interface PublicMetrics {
  basic: {
    counters: {
      analyze_requests: number;
      analyze_errors: number;
      rate_limit_hits: number;
      monitoring_page_views: number;
    };
    histograms: {
      analyze_duration_avg: number | null;
      analyze_duration_count: number;
    };
  };
  llm: {
    counters: {
      llm_requests: number;
      llm_errors: number;
      llm_retries: number;
    };
    quality: {
      error_rate: number;
      retry_rate: number;
    };
  };
}

interface AdminMetrics {
  tokens: {
    total_prompt_tokens: number;
    total_completion_tokens: number;
    total_tokens: number;
  };
  processing: {
    registers_extracted: number;
    auto_fixes_applied: number;
    avg_registers_per_request: number;
    auto_fix_rate: number;
  };
  performance: {
    llm_duration_avg: number | null;
    llm_duration_count: number;
  };
  errors: {
    categories: Record<string, number>;
    recent: Array<{
      timestamp: number;
      category: string;
      title: string;
      description: string;
      suggestion: string;
      severity: 'low' | 'medium' | 'high' | 'critical';
      technical_details: string;
    }>;
    top_category: string | null;
  };
}

interface AppStatus {
  llm_available: boolean;
  max_file_size_mb: number;
  version: string;
  server_model?: string;
}

/** Форматирование времени uptime */
function formatUptime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  
  if (hours > 24) {
    const days = Math.floor(hours / 24);
    const remainingHours = hours % 24;
    return `${days}д ${remainingHours}ч`;
  }
  
  if (hours > 0) {
    return `${hours}ч ${minutes}м`;
  }

  if (minutes > 0) {
    return `${minutes}м`;
  }

  return `${seconds}с`;
}

/** Русские названия категорий ошибок */
function formatErrorCategory(category: string, t: (key: string) => string): string {
  return t(`errorCat.${category}`) || category;
}

/** Описания категорий ошибок */
function getErrorCategoryDescription(category: string, t: (key: string) => string): string {
  return t(`errorDesc.${category}`) || 'Общие ошибки';
}

/** Форматирование больших чисел в компактном виде */
function formatLargeNumber(num: number): string {
  if (num >= 1_000_000) {
    return (num / 1_000_000).toFixed(1) + 'M';
  }
  if (num >= 1_000) {
    return (num / 1_000).toFixed(1) + 'K';
  }
  return num.toString();
}

/** Форматирование времени для ошибок */
function formatErrorTime(timestamp: number, t: (key: string, params?: Record<string, string | number>) => string): string {
  const date = new Date(timestamp * 1000);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / (1000 * 60));
  
  if (minutes < 60) {
    return t('errors.timeAgo.minutes', { min: minutes });
  }
  
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return t('errors.timeAgo.hours', { hours });
  }
  
  return date.toLocaleDateString('ru-RU', { 
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  });
}

/** Статус-компонент UP/DOWN */
function StatusBadge({ status, label }: { status: boolean; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className={`w-2 h-2 rounded-full ${status ? 'bg-green-500' : 'bg-red-500'}`} />
      <span className={`text-sm font-medium ${status ? 'text-green-700' : 'text-red-700'}`}>
        {label}: {status ? 'UP' : 'DOWN'}
      </span>
    </div>
  );
}

/** Метрика с числовым значением */
function MetricCard({ 
  title, 
  value, 
  unit = '', 
  description,
  variant = 'default' 
}: { 
  title: string; 
  value: string | number; 
  unit?: string;
  description?: string;
  variant?: 'default' | 'success' | 'warning' | 'error';
}) {
  const colorClasses = {
    default: 'bg-gray-50 text-gray-800',
    success: 'bg-green-50 text-green-800',
    warning: 'bg-yellow-50 text-yellow-800',
    error: 'bg-red-50 text-red-800'
  };

  const isLargeNumber = typeof value === 'number' && value >= 1000;
  const displayValue = typeof value === 'number' ? formatLargeNumber(value) : value;
  const fullValue = typeof value === 'number' ? value.toLocaleString() : value;

  return (
    <div className={`rounded-lg p-3 border ${colorClasses[variant]}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-gray-600 uppercase tracking-wide">
          {title}
        </h3>
      </div>
      <div className="mt-2">
        <span 
          className="text-2xl font-bold"
          title={isLargeNumber ? fullValue : undefined}
        >
          {displayValue}
        </span>
        {unit && <span className="text-sm text-gray-500 ml-1">{unit}</span>}
      </div>
      {description && (
        <p className="text-xs text-gray-500 mt-1">{description}</p>
      )}
    </div>
  );
}

/** Карточка для отображения детальной информации об ошибке */
function ErrorCard({ error, t }: { 
  error: {
    timestamp: number;
    category: string;
    title: string;
    description: string;
    suggestion: string;
    severity: 'low' | 'medium' | 'high' | 'critical';
    technical_details: string;
  };
  t: (key: string, params?: Record<string, string | number>) => string;
}) {
  const severityStyles = {
    low: 'border-l-blue-400 bg-blue-50',
    medium: 'border-l-yellow-400 bg-yellow-50', 
    high: 'border-l-orange-400 bg-orange-50',
    critical: 'border-l-red-400 bg-red-50'
  };

  const severityLabels = {
    low: t('errors.severity.low'),
    medium: t('errors.severity.medium'),
    high: t('errors.severity.high'), 
    critical: t('errors.severity.critical')
  };

  return (
    <div className={`border-l-4 p-4 rounded-r ${severityStyles[error.severity]}`}>
      <div className="flex items-start justify-between mb-2">
        <div>
          <h5 className="font-medium text-gray-900">{error.title}</h5>
          <div className="flex items-center gap-2 mt-1">
            <span className="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-gray-100 text-gray-800">
              {formatErrorCategory(error.category, t)}
            </span>
            <span className="text-xs text-gray-500">
              {severityLabels[error.severity]}
            </span>
          </div>
        </div>
        <span className="text-xs text-gray-500 shrink-0">
          {formatErrorTime(error.timestamp, t)}
        </span>
      </div>
      
      <p className="text-sm text-gray-700 mb-2">{error.description}</p>
      
      {error.suggestion && (
        <div className="text-sm text-gray-600 bg-white bg-opacity-50 p-2 rounded">
          <strong>{t('errors.recommendation')}:</strong> {error.suggestion}
        </div>
      )}
      
      {error.technical_details && (
        <details className="mt-2">
          <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">
            {t('errors.technicalDetails')}
          </summary>
          <pre className="text-xs text-gray-600 bg-white bg-opacity-50 p-2 mt-1 rounded overflow-auto">
            {error.technical_details}
          </pre>
        </details>
      )}
    </div>
  );
}

/** Основная страница мониторинга */
export default function MonitoringPage() {
  const t = useT();
  const [systemMetrics, setSystemMetrics] = useState<SystemMetrics | null>(null);
  const [publicMetrics, setPublicMetrics] = useState<PublicMetrics | null>(null);
  const [adminMetrics, setAdminMetrics] = useState<AdminMetrics | null>(null);
  const [appStatus, setAppStatus] = useState<AppStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  
  // Состояние для админского токена
  const [adminToken, setAdminToken] = useState('');
  const [showAdminSection, setShowAdminSection] = useState(false);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [isAdminAuthenticated, setIsAdminAuthenticated] = useState(false);

  // Восстанавливаем токен из sessionStorage при загрузке
  useEffect(() => {
    const savedToken = sessionStorage.getItem('adminToken');
    if (!savedToken) return;

    setAdminToken(savedToken);
    let cancelled = false;

    const timerId = setTimeout(async () => {
      try {
        const response = await fetch('/api/admin/metrics', {
          headers: { 'Authorization': `Bearer ${savedToken}` }
        });
        if (cancelled) return;
        if (response.ok) {
          const data = await response.json();
          setAdminMetrics(data);
          setIsAdminAuthenticated(true);
          setShowAdminSection(true);
        } else {
          sessionStorage.removeItem('adminToken');
        }
      } catch {
        // Сетевая ошибка при восстановлении — игнорируем
      }
    }, 100);

    return () => { cancelled = true; clearTimeout(timerId); };
  }, []);

  /** Отслеживание просмотра страницы */
  const trackPageView = async () => {
    try {
      await fetch('/api/metrics/page-view', { method: 'POST' });
    } catch (err) {
      console.debug(t('errors.pageViewFailed'), err);
    }
  };

  /** Загрузка публичных метрик */
  const fetchPublicMetrics = async () => {
    try {
      setError(null);
      
      // Запрашиваем публичные эндпоинты параллельно
      const [healthRes, metricsRes, statusRes] = await Promise.all([
        fetch('/api/health'),
        fetch('/api/metrics'), 
        fetch('/api/status')
      ]);

      if (!healthRes.ok || !metricsRes.ok || !statusRes.ok) {
        throw new Error(t('errors.loadFailed'));
      }

      const [health, metrics, status] = await Promise.all([
        healthRes.json(),
        metricsRes.json(),
        statusRes.json()
      ]);

      setSystemMetrics(health);
      setPublicMetrics(metrics);
      setAppStatus(status);
      setLastUpdate(new Date());
    } catch (err) {
      console.error(t('errors.loadPublicFailed'), err);
      setError(err instanceof Error ? err.message : t('errors.unknown'));
    }
  };
  
  /** Загрузка админских метрик */
  const fetchAdminMetrics = async () => {
    if (!adminToken.trim()) {
      setAdminError(t('admin.enterToken'));
      return;
    }
    
    try {
      setAdminError(null);
      
      const response = await fetch('/api/admin/metrics', {
        headers: {
          'Authorization': `Bearer ${adminToken.trim()}`
        }
      });
      
      if (response.status === 403) {
        setAdminError(t('admin.invalidToken'));
        setAdminMetrics(null);
        return;
      }
      
      if (response.status === 503) {
        setAdminError(t('admin.disabled'));
        setAdminMetrics(null);
        return;
      }
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      
      const data = await response.json();
      setAdminMetrics(data);
      setIsAdminAuthenticated(true); // Устанавливаем флаг успешной авторизации
      
      // Сохраняем токен в sessionStorage для восстановления сессии
      sessionStorage.setItem('adminToken', adminToken.trim());
      
    } catch (err) {
      console.error(t('errors.loadAdminFailed'), err);
      setAdminError(err instanceof Error ? err.message : t('errors.loadFailed'));
      setAdminMetrics(null);
      setIsAdminAuthenticated(false);
    }
  };

  /** Выход из админского режима */
  const handleAdminLogout = () => {
    setAdminToken('');
    setAdminMetrics(null);
    setIsAdminAuthenticated(false);
    setAdminError(null);
    
    // Удаляем токен из sessionStorage
    sessionStorage.removeItem('adminToken');
  };

  /** Загрузка всех метрик */
  const fetchMetrics = async () => {
    await fetchPublicMetrics();
    if (showAdminSection && isAdminAuthenticated && adminToken) {
      await fetchAdminMetrics();
    }
    setLoading(false);
  };

  // Отслеживаем просмотр страницы только при монтировании
  useEffect(() => {
    trackPageView();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Refs для доступа к актуальным значениям из setInterval
  const adminStateRef = useRef({ showAdminSection, isAdminAuthenticated, adminToken });
  useEffect(() => {
    adminStateRef.current = { showAdminSection, isAdminAuthenticated, adminToken };
  }, [showAdminSection, isAdminAuthenticated, adminToken]);

  // Загрузка при монтировании и автообновление каждые 30 секунд
  useEffect(() => {
    fetchMetrics();
    const REFRESH_INTERVAL_MS = 30_000;
    const interval = setInterval(() => {
      fetchPublicMetrics();
      const { showAdminSection: show, isAdminAuthenticated: auth, adminToken: token } = adminStateRef.current;
      if (show && auth && token) {
        fetchAdminMetrics();
      }
    }, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
          <p className="text-gray-600 mt-2">{t('monitoring.loading')}</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="text-red-500 text-xl">⚠️</div>
          <h2 className="text-lg font-semibold text-gray-800 mt-2">{t('monitoring.error')}</h2>
          <p className="text-gray-600 mt-1">{error}</p>
          <button 
            onClick={() => { setLoading(true); fetchMetrics(); }}
            className="mt-3 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
          >
            {t('monitoring.retry')}
          </button>
        </div>
      </div>
    );
  }

  const isSystemHealthy = systemMetrics?.status === 'ok';
  const errorRate = publicMetrics ? 
    (publicMetrics.basic.counters.analyze_errors / Math.max(1, publicMetrics.basic.counters.analyze_requests) * 100) : 0;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto px-4 py-6">
        {/* Заголовок */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              {t('monitoring.title')}
            </h1>
            <p className="text-gray-600 mt-1">
              {t('monitoring.subtitle')}
            </p>
          </div>
          <div className="text-right">
            <button 
              onClick={fetchMetrics}
              className="px-3 py-1.5 text-xs bg-gray-100 hover:bg-gray-200 rounded transition-colors mr-2"
            >
              🔄 {t('monitoring.refresh')}
            </button>
            <button
              onClick={() => setShowAdminSection(!showAdminSection)}
              className={`px-3 py-1.5 text-xs rounded transition-colors ${
                showAdminSection 
                  ? isAdminAuthenticated 
                    ? 'bg-green-600 text-white hover:bg-green-700' 
                    : 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'bg-gray-100 hover:bg-gray-200'
              }`}
            >
              {isAdminAuthenticated ? t('admin.activeAdmin') : t('admin.panel')}
            </button>
            {lastUpdate && (
              <p className="text-xs text-gray-500 mt-1">
                {t('monitoring.lastUpdate')}: {lastUpdate.toLocaleTimeString()}
              </p>
            )}
          </div>
        </div>

        {/* Админский раздел */}
        {showAdminSection && (
          <div className="bg-white rounded-lg shadow-sm p-6 mb-6 border-l-4 border-blue-500">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              🔐 {t('admin.title')}
            </h2>
            
            {!isAdminAuthenticated ? (
              // Форма ввода токена
              <div>
                <div className="flex items-center gap-4">
                  <input
                    type="password"
                    value={adminToken}
                    onChange={(e) => setAdminToken(e.target.value)}
                    placeholder={t('admin.enterTokenPlaceholder')}
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && adminToken.trim()) {
                        fetchAdminMetrics();
                      }
                    }}
                  />
                  <button
                    onClick={fetchAdminMetrics}
                    disabled={!adminToken.trim()}
                    className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
                  >
                    {t('admin.login')}
                  </button>
                </div>
                {adminError && (
                  <p className="text-red-600 text-sm mt-2">❌ {adminError}</p>
                )}
              </div>
            ) : (
              // Статус авторизованного пользователя
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-green-600 text-sm">✅ {t('admin.authorizedAs')}</span>
                  <span className="text-gray-500 text-xs">
                    ({t('admin.token')}: {adminToken.substring(0, 4)}***{adminToken.substring(adminToken.length - 3)})
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={fetchAdminMetrics}
                    className="px-3 py-1.5 text-xs bg-green-100 text-green-700 hover:bg-green-200 rounded transition-colors"
                  >
                    🔄 {t('admin.refreshMetrics')}
                  </button>
                  <button
                    onClick={handleAdminLogout}
                    className="px-3 py-1.5 text-xs bg-gray-100 text-gray-700 hover:bg-gray-200 rounded transition-colors"
                  >
                    {t('admin.logout')}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Общий статус системы */}
        <div className="bg-white rounded-lg shadow-sm p-6 mb-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">
            🖥️ {t('monitoring.systemHealth')}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatusBadge 
              status={isSystemHealthy} 
              label={t('status.backend')}
            />
            <StatusBadge 
              status={true} // Frontend всегда UP если страница загрузилась
              label={t('status.frontend')}  
            />
            <StatusBadge 
              status={appStatus?.llm_available || false}
              label={t('status.llmApi')}
            />
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-medium text-gray-700">
                {t('metrics.uptime')}: {systemMetrics ? formatUptime(systemMetrics.uptime_seconds) : '—'}
              </span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Очереди обработки */}
          <div className="bg-white rounded-lg shadow-sm p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              📊 {t('queues.server')}
            </h2>
            <div className="space-y-4">
              {systemMetrics?.queues.server && (
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-2">{t('queues.server')}</h3>
                  <div className="grid grid-cols-3 gap-3">
                    <MetricCard 
                      title={t('metrics.active')}
                      value={systemMetrics.queues.server.active}
                      description={t('metrics.outOf', { max: systemMetrics.queues.server.max_concurrent })}
                      variant={systemMetrics.queues.server.active >= systemMetrics.queues.server.max_concurrent ? 'warning' : 'default'}
                    />
                    <MetricCard 
                      title={t('metrics.waiting')}
                      value={systemMetrics.queues.server.waiting}
                      variant={systemMetrics.queues.server.waiting > 0 ? 'warning' : 'success'}
                    />
                    <MetricCard 
                      title={t('metrics.avgTime')}
                      value={systemMetrics.queues.server.avg_duration?.toFixed(1) || '—'}
                      unit={t('units.sec')}
                    />
                  </div>
                </div>
              )}
              
              {systemMetrics?.queues.custom && (
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-2">{t('queues.custom')}</h3>
                  <div className="grid grid-cols-3 gap-3">
                    <MetricCard 
                      title={t('metrics.active')}
                      value={systemMetrics.queues.custom.active}
                      description={t('metrics.outOf', { max: systemMetrics.queues.custom.max_concurrent })}
                    />
                    <MetricCard 
                      title={t('metrics.waiting')}
                      value={systemMetrics.queues.custom.waiting}
                      variant={systemMetrics.queues.custom.waiting > 0 ? 'warning' : 'success'}
                    />
                    <MetricCard 
                      title={t('metrics.avgTime')}
                      value={systemMetrics.queues.custom.avg_duration?.toFixed(1) || '—'}
                      unit={t('units.sec')}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Статистика обработки */}
          <div className="bg-white rounded-lg shadow-sm p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              📈 {t('monitoring.processingStats')}
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard 
                title={t('metrics.totalRequests')}
                value={publicMetrics?.basic.counters.analyze_requests || 0}
                variant="default"
              />
              <MetricCard 
                title={t('metrics.errors')}
                value={publicMetrics?.basic.counters.analyze_errors || 0}
                variant={errorRate > 5 ? 'error' : errorRate > 1 ? 'warning' : 'success'}
                description={t('metrics.percentOfTotal', { percent: errorRate.toFixed(1) })}
              />
              <MetricCard 
                title={t('metrics.rateLimit')}
                value={publicMetrics?.basic.counters.rate_limit_hits || 0}
                variant={publicMetrics && publicMetrics.basic.counters.rate_limit_hits > 0 ? 'warning' : 'success'}
                description={t('metrics.limitExceeded')}
              />
              <MetricCard 
                title={t('metrics.monitoringViews')}
                value={publicMetrics?.basic.counters.monitoring_page_views || 0}
                variant="default"
                description={t('metrics.pageVisits')}
              />
            </div>
          </div>

          {/* LLM метрики (публичные) */}
          <div className="bg-white rounded-lg shadow-sm p-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              {t('monitoring.llmStats')}
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard
                title={t('metrics.llmRequests')}
                value={publicMetrics?.llm.counters.llm_requests || 0}
                variant="default"
              />
              <MetricCard
                title={t('metrics.llmErrors')}
                value={publicMetrics?.llm.counters.llm_errors || 0}
                variant={publicMetrics && publicMetrics.llm.quality.error_rate < 5 ? 'success' : 'warning'}
                description={`${publicMetrics?.llm.quality.error_rate ?? 0}%`}
              />
              <MetricCard
                title={t('metrics.llmRetries')}
                value={publicMetrics?.llm.counters.llm_retries || 0}
                variant={publicMetrics && publicMetrics.llm.quality.retry_rate < 10 ? 'success' : 'warning'}
                description={`${publicMetrics?.llm.quality.retry_rate ?? 0}%`}
              />
              <MetricCard
                title={t('metrics.avgAnalysisTime')}
                value={publicMetrics?.basic.histograms.analyze_duration_avg?.toFixed(1) || '—'}
                unit={t('units.sec')}
                description={t('metrics.measurementsCount', { count: publicMetrics?.basic.histograms.analyze_duration_count || 0 })}
              />
            </div>
          </div>
        </div>

        {/* Детальные админские LLM метрики */}
        {adminMetrics && (
          <div className="bg-white rounded-lg shadow-sm p-6 mt-6 border-l-4 border-blue-500">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">
              {t('monitoring.llmMetricsDetailed')}
            </h2>
            <div className="space-y-6">
              {/* Токены */}
              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-3">{t('metrics.tokenUsage')}</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <MetricCard
                    title={t('metrics.promptTokens')}
                    value={adminMetrics.tokens.total_prompt_tokens}
                    variant="default"
                  />
                  <MetricCard
                    title={t('metrics.completionTokens')}
                    value={adminMetrics.tokens.total_completion_tokens}
                    variant="default"
                  />
                  <MetricCard
                    title={t('metrics.totalTokens')}
                    value={adminMetrics.tokens.total_tokens}
                    variant="default"
                  />
                </div>
              </div>

              {/* Производительность */}
              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-3">{t('metrics.performance')}</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <MetricCard
                    title={t('metrics.registersExtracted')}
                    value={adminMetrics.processing.registers_extracted}
                    variant="success"
                    description={`${adminMetrics.processing.avg_registers_per_request.toFixed(1)} ${t('metrics.avgPerRequest')}`}
                  />
                  <MetricCard
                    title={t('metrics.autoFixes')}
                    value={adminMetrics.processing.auto_fixes_applied}
                    variant={adminMetrics.processing.auto_fix_rate > 20 ? 'warning' : 'success'}
                    description={`${adminMetrics.processing.auto_fix_rate.toFixed(1)}%`}
                  />
                  <MetricCard
                    title={t('metrics.avgLlmTime')}
                    value={adminMetrics.performance.llm_duration_avg?.toFixed(1) || '—'}
                    unit={t('units.sec')}
                    description={`${adminMetrics.performance.llm_duration_count} ${t('metrics.requests')}`}
                  />
                </div>
              </div>

              {/* Анализ ошибок */}
              {adminMetrics.errors && (
                <div>
                  <h3 className="text-sm font-medium text-gray-700 mb-3">{t('errors.analysis')}</h3>
                  
                  {/* Категории ошибок */}
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                     {Object.entries(adminMetrics.errors.categories).map(([category, count]) => (
                       <MetricCard 
                         key={category}
                         title={formatErrorCategory(category, t)}
                         value={count}
                         variant={count === 0 ? 'success' : 'warning'}
                         description={getErrorCategoryDescription(category, t)}
                       />
                     ))}
                  </div>

                  {/* Последние ошибки */}
                  {adminMetrics.errors.recent.length > 0 && (
                    <div>
                      <h4 className="text-sm font-medium text-gray-700 mb-3">
                        {t('errors.recentErrors')} ({adminMetrics.errors.recent.length})
                      </h4>
                      <div className="space-y-3 max-h-96 overflow-y-auto">
                        {adminMetrics.errors.recent.map((error, index) => (
                          <ErrorCard key={index} error={error} t={t} />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Конфигурация системы */}
        <div className="bg-white rounded-lg shadow-sm p-6 mt-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">
            {t('monitoring.systemConfig')}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <MetricCard
              title={t('config.version')}
              value={appStatus?.version || 'dev'}
            />
            <MetricCard
              title={t('config.llmModel')}
              value={appStatus?.server_model || t('config.notConfigured')}
              variant={appStatus?.llm_available ? 'success' : 'warning'}
            />
            <MetricCard
              title={t('config.fileLimit')}
              value={appStatus?.max_file_size_mb || 0}
              unit={t('units.mb')}
            />
          </div>
        </div>
      </div>
    </div>
  );
}