import { useState, useCallback, useEffect, Fragment } from 'react';
import { useStore } from '../store';
import { useT } from '../i18n';
import GroupSection from './GroupSection';
import ChannelPreview from './ChannelPreview';
import ParameterPreview from './ParameterPreview';
import type { WBChannel, WBParameter } from '../types';

/** Находит id регистра по имени канала/параметра.
 *  Если подсвеченный регистр имеет то же имя — предпочитаем его
 *  (для корректной подсветки условных каналов с одним именем). */
function findRegisterId(
  name: string,
  registers: Array<{ id: string; name: string; channel_type?: string }>,
  highlightedId?: string | null,
  channelType?: string,
): string | undefined {
  if (highlightedId) {
    const hl = registers.find((r) => r.id === highlightedId);
    if (hl && hl.name === name) return highlightedId;
  }
  // Сначала точное совпадение по name + channel_type
  if (channelType) {
    const exact = registers.find((r) => r.name === name && r.channel_type === channelType);
    if (exact) return exact.id;
  }
  // Фоллбэк — только по имени
  return registers.find((r) => r.name === name)?.id;
}

// --- Парсер и вычислитель условий wb-mqtt-serial ---

/** Нормализация имени: "Show modes as range" / "Show_modes_as_range" → "show_modes_as_range" */
function normalizeKey(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
}

interface ParsedCondition {
  ref: string;        // нормализованный ключ канала/параметра-источника
  operator: string;   // ==, !=, >, <, >=, <=
  value: number;
}

/** Парсит строку condition вида "ChannelName==1" */
function parseCondition(condition: string): ParsedCondition | null {
  const m = condition.match(/^(.+?)(==|!=|>=|<=|>|<)(.+)$/);
  if (!m) return null;
  const val = Number(m[3]);
  if (isNaN(val)) return null;
  return { ref: normalizeKey(m[1]), operator: m[2], value: val };
}

/** Вычисляет условие: true — показать, false — скрыть, null — неизвестно */
function evaluateCondition(
  condition: string | undefined,
  values: Record<string, number>,
): boolean | null {
  if (!condition) return true;
  const parsed = parseCondition(condition);
  if (!parsed) return null;
  const current = values[parsed.ref];
  if (current === undefined) return null;
  switch (parsed.operator) {
    case '==': return current === parsed.value;
    case '!=': return current !== parsed.value;
    case '>':  return current > parsed.value;
    case '<':  return current < parsed.value;
    case '>=': return current >= parsed.value;
    case '<=': return current <= parsed.value;
    default: return null;
  }
}

/** Обрабатывает conditional-группы каналов:
 *  - Если condition вычислим → показываем подходящий вариант
 *  - Если нет → показываем первый с бейджем "N вар."
 */
type ChannelWithMeta = WBChannel & {
  _conditionalCount?: number;
  _conditions?: string[];
  _conditionHidden?: boolean;
};

function resolveConditionalChannels(
  channels: WBChannel[],
  conditionValues: Record<string, number>,
): ChannelWithMeta[] {
  // Группируем по имени
  const byName = new Map<string, WBChannel[]>();
  for (const ch of channels) {
    if (!byName.has(ch.name)) byName.set(ch.name, []);
    byName.get(ch.name)!.push(ch);
  }

  const result: ChannelWithMeta[] = [];
  const seen = new Set<string>();

  for (const ch of channels) {
    const group = byName.get(ch.name)!;
    // Не conditional-группа — просто проверяем condition
    if (group.length <= 1 || !group.every((c) => c.condition)) {
      const vis = evaluateCondition(ch.condition, conditionValues);
      result.push({ ...ch, _conditionHidden: vis === false });
      continue;
    }

    // Conditional-группа: несколько каналов с одним name + все с condition
    if (seen.has(ch.name)) continue;
    seen.add(ch.name);

    // Пытаемся вычислить — найти подходящий вариант
    const match = group.find((c) => evaluateCondition(c.condition, conditionValues) === true);
    if (match) {
      // Нашли подходящий — рендерим его с бейджем "N вар."
      result.push({
        ...match,
        _conditionalCount: group.length,
        _conditions: group.map((c) => c.condition!),
      });
    } else {
      // Не можем вычислить — показываем первый с бейджем
      result.push({
        ...group[0],
        _conditionalCount: group.length,
        _conditions: group.map((c) => c.condition!),
      });
    }
  }
  return result;
}

/** Переводит строку через translations шаблона */
function translate(
  name: string,
  lang: string,
  translations?: Record<string, Record<string, string>>
): string {
  if (!translations) return name;
  if (lang === 'en') return translations['en']?.[name] ?? name;
  return translations[lang]?.[name] ?? translations['en']?.[name] ?? name;
}

/** Переводит массив enum_titles через translations */
function translateEnumTitles(
  titles: string[] | undefined,
  lang: string,
  translations?: Record<string, Record<string, string>>
): string[] | undefined {
  if (!titles || !translations) return titles;
  return titles.map((t) => translate(t, lang, translations));
}

/** Извлекает ключ перевода из строки предупреждения о конфликте.
 *  Формат: Конфликт перевода [ru]: "Some Key" → "val1" vs "val2" */
function parseWarningKey(warning: string): string | null {
  const m = warning.match(/Конфликт перевода \[[^\]]+\]: "([^"]+)"/);
  return m ? m[1] : null;
}

/** Основной компонент превью шаблона */
export default function TemplatePreview() {
  const t = useT();
  const template = useStore((s) => s.template);
  const registers = useStore((s) => s.registers);
  const previewLang = useStore((s) => s.previewLang);
  const setPreviewLang = useStore((s) => s.setPreviewLang);
  const highlightedRegisterId = useStore((s) => s.highlightedRegisterId);
  const setHighlightedRegister = useStore((s) => s.setHighlightedRegister);
  const collapsedGroups = useStore((s) => s.collapsedGroups);
  const toggleGroupCollapsed = useStore((s) => s.toggleGroupCollapsed);
  const setRowExpanded = useStore((s) => s.setRowExpanded);

  /** Клик по предупреждению о конфликте — найти регистр и перейти к нему */
  const handleWarningClick = useCallback((warning: string) => {
    const key = parseWarningKey(warning);
    if (!key) return;

    // Ищем регистр по имени, description или enum title
    const reg = registers.find((r) =>
      r.name === key ||
      (r.description && r.description === key) ||
      (r.enum_entries?.some((e) => e.title === key)),
    );
    if (!reg) return;

    // Разворачиваем группу если свёрнута
    if (collapsedGroups.has(reg.group)) {
      toggleGroupCollapsed(reg.group);
    }

    // Разворачиваем строку чтобы показать переводы
    setRowExpanded(reg.id, true);

    // Подсвечиваем регистр (автоскролл уже встроен в RegisterTable)
    setHighlightedRegister(reg.id);
  }, [registers, collapsedGroups, toggleGroupCollapsed, setHighlightedRegister, setRowExpanded]);

  const [channelsOpen, setChannelsOpen] = useState(true);
  const [paramsOpen, setParamsOpen] = useState(true);
  const [conditionValues, setConditionValues] = useState<Record<string, number>>({});
  const [collapsedParamGroups, setCollapsedParamGroups] = useState<Set<string>>(new Set());

  const onValueChange = useCallback((name: string, value: number) => {
    // Нормализуем ключ, чтобы "Show modes as range" и "Show_modes_as_range" совпадали
    setConditionValues((prev) => ({ ...prev, [normalizeKey(name)]: value }));
  }, []);

  // Инициализация conditionValues при загрузке/смене шаблона
  useEffect(() => {
    if (!template) return;
    const initial: Record<string, number> = {};
    const allChannels: Array<{ name?: string; type?: string; enum?: unknown[]; min?: number }> = [
      ...Object.values(template.device?.channels ?? {}),
      ...Object.values(template.device?.parameters ?? {}),
    ];
    for (const ch of allChannels) {
      const key = normalizeKey(ch.name ?? '');
      if (!key || key in initial) continue;
      if (ch.enum && Array.isArray(ch.enum) && ch.enum.length > 0) {
        initial[key] = 0;
      } else if (ch.type === 'switch') {
        initial[key] = 0;
      } else if (ch.type === 'range' && ch.min !== undefined) {
        initial[key] = ch.min;
      }
    }
    for (const [pKey, p] of Object.entries(template.device?.parameters ?? {})) {
      const key = normalizeKey(p.title ?? pKey);
      if (!key || key in initial) continue;
      if (p.enum && typeof p.enum === 'object') {
        const keys = Object.keys(p.enum);
        if (keys.length > 0) {
          initial[key] = Number(keys[0]) || 0;
        }
      }
    }
    setConditionValues(initial);
  }, [template]);

  // Автоскролл к подсвеченному элементу в превью (только десктоп xl+)
  useEffect(() => {
    if (!highlightedRegisterId) return;
    if (window.innerWidth < 1280) return;
    requestAnimationFrame(() => {
      const el = document.getElementById(`preview-${highlightedRegisterId}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }, [highlightedRegisterId]);

  if (!template) {
    return (
      <p className="text-gray-400 text-sm text-center py-4">
        {t('preview.empty')}
      </p>
    );
  }

  const { device, _warnings: warnings } = template;
  const groups = device.groups ?? [];
  const channels: WBChannel[] = device.channels ?? [];
  const parameters: Record<string, WBParameter> = device.parameters ?? {};
  const translations = device.translations;

  // Доступные языки: EN (всегда) + языки из translations (кроме en)
  const availableLangs = ['en', ...Object.keys(translations ?? {}).filter((l) => l !== 'en').sort()];

  // Fallback: если выбранный язык удалён — переключаемся на en
  const activeLang = availableLangs.includes(previewLang) ? previewLang : 'en';

  // Группировка параметров по group
  const paramsByGroup = new Map<string, Array<{ key: string; param: WBParameter }>>();
  for (const [key, param] of Object.entries(parameters)) {
    const gid = param.group ?? '';
    if (!paramsByGroup.has(gid)) paramsByGroup.set(gid, []);
    paramsByGroup.get(gid)!.push({ key, param });
  }

  const groupIds = new Set(groups.map((g) => g.id));
  const hasParameters = Object.keys(parameters).length > 0;
  const hasChannels = channels.length > 0;

  // Дерево групп: top-level (без parent) и дочерние
  const topLevelGroups = groups.filter((g) => !g.group);
  const childGroupsOf = (parentId: string) =>
    groups.filter((g) => g.group === parentId);

  // Разделяем каналы на активные и отключенные
  const enabledChannels = channels.filter((ch) => ch.enabled !== false);
  const disabledChannels = channels.filter((ch) => ch.enabled === false);

  // Группировка активных каналов
  const enabledByGroupRaw = new Map<string, WBChannel[]>();
  for (const ch of enabledChannels) {
    const gid = ch.group ?? '';
    if (!enabledByGroupRaw.has(gid)) enabledByGroupRaw.set(gid, []);
    enabledByGroupRaw.get(gid)!.push(ch);
  }
  const enabledByGroup = new Map<string, ChannelWithMeta[]>();
  for (const [gid, chs] of enabledByGroupRaw) {
    enabledByGroup.set(gid, resolveConditionalChannels(chs, conditionValues));
  }

  // Количество видимых активных каналов
  const visibleChannelCount = (() => {
    let count = 0;
    for (const chs of enabledByGroup.values()) {
      count += chs.filter((ch) => !ch._conditionHidden).length;
    }
    return count;
  })();

  // Количество видимых параметров (с учётом conditions)
  const visibleParamCount = Object.values(parameters)
    .filter((p) => evaluateCondition(p.condition, conditionValues) !== false).length;

  /** Проверяет, есть ли видимые каналы в группе и всех её подгруппах (рекурсивно) */
  const hasVisibleChannels = (groupId: string): boolean => {
    const own = (enabledByGroup.get(groupId) ?? []).some((ch) => !ch._conditionHidden);
    if (own) return true;
    return childGroupsOf(groupId).some((child) => hasVisibleChannels(child.id));
  };

  /** Проверяет, есть ли параметры в группе и всех её подгруппах (рекурсивно) */
  const hasGroupParams = (groupId: string): boolean => {
    if ((paramsByGroup.get(groupId) ?? []).length > 0) return true;
    return childGroupsOf(groupId).some((child) => hasGroupParams(child.id));
  };

  return (
    <div>
      {/* Предупреждения о конфликтах переводов */}
      {warnings && warnings.length > 0 && (
        <div className="mb-3 bg-yellow-50 border border-yellow-200 rounded px-3 py-2">
          <div className="text-xs font-semibold text-yellow-700 mb-1">{t('preview.translationConflicts')} ({warnings.length})</div>
          <ul className="text-[11px] text-yellow-600 space-y-0.5 max-h-24 overflow-y-auto">
            {warnings.map((w, i) => (
              <li
                key={i}
                onClick={() => handleWarningClick(w)}
                className="cursor-pointer hover:text-yellow-800 hover:underline"
                title={t('preview.goToRegister')}
              >
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Заголовок + переключатель языка */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-900">
          {translate(device.name, activeLang, translations) || device.name}
        </h3>
        <div className="flex bg-gray-200 rounded p-0.5 text-xs">
          {availableLangs.map((lang) => (
            <button
              key={lang}
              onClick={() => setPreviewLang(lang)}
              className={`px-2 py-0.5 rounded transition-colors ${
                activeLang === lang ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500'
              }`}
            >
              {lang.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* === Каналы === */}
      {hasChannels && (() => {
        /** Рендер разделителя группы каналов */
        const renderChannelGroupHeader = (group: typeof groups[0], showBorder: boolean) => (
          <div
            onClick={() => {
              if (window.innerWidth < 1280) return;
              const el = document.getElementById(`table-group-${group.id}`);
              if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }}
            className={`flex items-center gap-2 px-3 py-1 bg-gray-50 select-none ${
              window.innerWidth >= 1280 ? 'cursor-pointer hover:bg-gray-100' : ''
            } transition-colors ${showBorder ? 'border-t border-gray-200' : ''}`}
            title={t('preview.goToGroup')}
          >
            <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider truncate">
              {translate(group.title, activeLang, translations)}
            </span>
            <span className="flex-1 border-t border-gray-200" />
          </div>
        );

        /** Рендер каналов одной группы */
        const renderChannelGroup = (groupId: string) => {
          const groupChannels = enabledByGroup.get(groupId) ?? [];
          return groupChannels.filter((ch) => !ch._conditionHidden).map((ch, i) => (
            <ChannelPreview
              key={`${groupId}-ch-${i}`}
              channel={{ ...ch, enum_titles: translateEnumTitles(ch.enum_titles, activeLang, translations) }}
              registerId={findRegisterId(ch.name, registers, highlightedRegisterId, ch.type)}
              displayName={translate(ch.name, activeLang, translations)}
              conditionalCount={ch._conditionalCount}
              conditions={ch._conditions}
              onValueChange={onValueChange}
            />
          ));
        };

        /** Рендер группы + подгрупп (рекурсивно) */
        let channelGroupIdx = 0;
        const renderGroupWithChildren = (group: typeof groups[0]) => {
          if (!hasVisibleChannels(group.id)) return null;
          const idx = channelGroupIdx++;
          const children = childGroupsOf(group.id);
          return (
            <Fragment key={group.id}>
              {renderChannelGroupHeader(group, idx > 0)}
              <div className="divide-y divide-gray-100">
                {renderChannelGroup(group.id)}
              </div>
              {children.map((child) => {
                if (!hasVisibleChannels(child.id)) return null;
                const childIdx = channelGroupIdx++;
                return (
                  <Fragment key={child.id}>
                    {/* Подгруппа — с отступом */}
                    <div
                      className={`flex items-center gap-2 px-3 pl-6 py-1 bg-gray-50/70 select-none transition-colors ${childIdx > 0 ? 'border-t border-gray-100' : ''}`}
                    >
                      <span className="text-[10px] text-gray-400 tracking-wider truncate">
                        {translate(child.title, activeLang, translations)}
                      </span>
                      <span className="flex-1 border-t border-gray-100" />
                    </div>
                    <div className="divide-y divide-gray-100">
                      {renderChannelGroup(child.id)}
                    </div>
                  </Fragment>
                );
              })}
            </Fragment>
          );
        };

        return (
          <div className="mb-4">
            <button
              onClick={() => setChannelsOpen((v) => !v)}
              className="flex items-center gap-1 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 px-1 hover:text-gray-700 transition-colors"
            >
              <svg
                className={`w-3 h-3 transition-transform duration-150 ${channelsOpen ? 'rotate-90' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
              {t('preview.channels')} ({visibleChannelCount})
            </button>

            {channelsOpen && (
              <div className="border border-gray-200 rounded-lg overflow-hidden">
                {topLevelGroups.map((group) => renderGroupWithChildren(group))}

                {/* Каналы без группы */}
                {(() => {
                  const ungroupedRaw = enabledChannels.filter(
                    (ch) => !ch.group || !groupIds.has(ch.group)
                  );
                  const ungrouped = resolveConditionalChannels(ungroupedRaw, conditionValues);
                  const visible = ungrouped.filter((ch) => !ch._conditionHidden);
                  if (visible.length === 0) return null;
                  return (
                    <>
                      <div className="flex items-center gap-2 px-3 py-1 bg-gray-50 select-none border-t border-gray-200">
                        <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">{t('preview.other')}</span>
                        <span className="flex-1 border-t border-gray-200" />
                      </div>
                      <div className="divide-y divide-gray-100">
                        {visible.map((ch, i) => (
                          <ChannelPreview
                            key={`ungrouped-ch-${i}`}
                            channel={{ ...ch, enum_titles: translateEnumTitles(ch.enum_titles, activeLang, translations) }}
                            registerId={findRegisterId(ch.name, registers, highlightedRegisterId, ch.type)}
                            displayName={translate(ch.name, activeLang, translations)}
                            conditionalCount={ch._conditionalCount}
                            conditions={ch._conditions}
                            onValueChange={onValueChange}
                          />
                        ))}
                      </div>
                    </>
                  );
                })()}
              </div>
            )}

            {/* Отключенные каналы — группируем как обычные, но серенькие */}
            {disabledChannels.length > 0 && channelsOpen && (() => {
              const disabledByGroup = new Map<string, WBChannel[]>();
              for (const ch of disabledChannels) {
                const gid = ch.group ?? '';
                if (!disabledByGroup.has(gid)) disabledByGroup.set(gid, []);
                disabledByGroup.get(gid)!.push(ch);
              }

              const hasDisabledIn = (groupId: string): boolean => {
                if ((disabledByGroup.get(groupId) ?? []).length > 0) return true;
                return childGroupsOf(groupId).some((c) => hasDisabledIn(c.id));
              };

              const renderDisabledChs = (gid: string) =>
                (disabledByGroup.get(gid) ?? []).map((ch, i) => (
                  <ChannelPreview
                    key={`dis-${gid}-${i}`}
                    channel={{ ...ch, enum_titles: translateEnumTitles(ch.enum_titles, activeLang, translations) }}
                    registerId={findRegisterId(ch.name, registers, highlightedRegisterId, ch.type)}
                    displayName={translate(ch.name, activeLang, translations)}
                  />
                ));

              let dIdx = 0;
              return (
                <div className="mt-2">
                  <GroupSection title={`${t('preview.disabledChannels')} (${disabledChannels.length})`}>
                    <div className="opacity-50 border border-gray-200 rounded-lg overflow-hidden">
                      {topLevelGroups.map((group) => {
                        if (!hasDisabledIn(group.id)) return null;
                        const idx = dIdx++;
                        return (
                          <Fragment key={`dis-g-${group.id}`}>
                            <div className={`flex items-center gap-2 px-3 py-1 bg-gray-50 select-none ${idx > 0 ? 'border-t border-gray-200' : ''}`}>
                              <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider truncate">
                                {translate(group.title, activeLang, translations)}
                              </span>
                              <span className="flex-1 border-t border-gray-200" />
                            </div>
                            <div className="divide-y divide-gray-100">{renderDisabledChs(group.id)}</div>
                            {childGroupsOf(group.id).map((child) => {
                              if (!hasDisabledIn(child.id)) return null;
                              return (
                                <Fragment key={`dis-g-${child.id}`}>
                                  <div className="flex items-center gap-2 px-3 pl-6 py-1 bg-gray-50/70 select-none border-t border-gray-100">
                                    <span className="text-[10px] text-gray-400 tracking-wider truncate">
                                      {translate(child.title, activeLang, translations)}
                                    </span>
                                    <span className="flex-1 border-t border-gray-100" />
                                  </div>
                                  <div className="divide-y divide-gray-100">{renderDisabledChs(child.id)}</div>
                                </Fragment>
                              );
                            })}
                          </Fragment>
                        );
                      })}
                      {/* Без группы */}
                      {(() => {
                        const ungrouped = disabledChannels.filter((ch) => !ch.group || !groupIds.has(ch.group));
                        if (ungrouped.length === 0) return null;
                        return (
                          <>
                            <div className="flex items-center gap-2 px-3 py-1 bg-gray-50 select-none border-t border-gray-200">
                              <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">{t('preview.other')}</span>
                              <span className="flex-1 border-t border-gray-200" />
                            </div>
                            <div className="divide-y divide-gray-100">
                              {ungrouped.map((ch, i) => (
                                <ChannelPreview
                                  key={`dis-ung-${i}`}
                                  channel={{ ...ch, enum_titles: translateEnumTitles(ch.enum_titles, activeLang, translations) }}
                                  registerId={findRegisterId(ch.name, registers, highlightedRegisterId, ch.type)}
                                  displayName={translate(ch.name, activeLang, translations)}
                                />
                              ))}
                            </div>
                          </>
                        );
                      })()}
                    </div>
                  </GroupSection>
                </div>
              );
            })()}
          </div>
        );
      })()}

      {/* === Параметры === */}
      {hasParameters && (() => {
        // Считаем top-level группы с параметрами (включая подгруппы)
        const paramTopGroups = topLevelGroups.filter((g) => hasGroupParams(g.id));
        const hasUngroupedParams = Object.values(parameters).some((p) => !p.group || !groupIds.has(p.group));
        const totalParamGroups = paramTopGroups.length + (hasUngroupedParams ? 1 : 0);
        const allGroupIds = groups.map((g) => g.id);
        const allParamGroupsCollapsed = totalParamGroups > 1 && allGroupIds.every((id) => collapsedParamGroups.has(id)) && (!hasUngroupedParams || collapsedParamGroups.has('__ungrouped__'));

        /** Рендер параметров одной группы */
        const renderParams = (groupId: string) => {
          const gp = paramsByGroup.get(groupId) ?? [];
          return gp
            .filter(({ param }) => evaluateCondition(param.condition, conditionValues) !== false)
            .map(({ key, param }) => (
              <ParameterPreview
                key={key}
                paramKey={key}
                param={{ ...param, enum_titles: translateEnumTitles(param.enum_titles, activeLang, translations) }}
                registerId={findRegisterId(param.title ?? key, registers, highlightedRegisterId)}
                displayName={translate(param.title ?? key, activeLang, translations)}
                displayDescription={param.description ? translate(param.description, activeLang, translations) : undefined}
                onValueChange={onValueChange}
              />
            ));
        };

        /** Рендер группы параметров с подгруппами */
        const renderParamGroup = (group: typeof groups[0]) => {
          if (!hasGroupParams(group.id)) return null;
          const children = childGroupsOf(group.id);
          return (
            <GroupSection
              key={`params-${group.id}`}
              title={translate(group.title, activeLang, translations)}
              expanded={!collapsedParamGroups.has(group.id)}
              onToggle={() => setCollapsedParamGroups((prev) => {
                const next = new Set(prev);
                if (next.has(group.id)) next.delete(group.id);
                else next.add(group.id);
                return next;
              })}
            >
              {/* Прямые параметры группы */}
              {renderParams(group.id)}
              {/* Подгруппы */}
              {children.map((child) => {
                if (!hasGroupParams(child.id)) return null;
                return (
                  <div key={`subgroup-${child.id}`} className="ml-2 mt-1 mb-1">
                    <div className="text-[10px] font-medium text-gray-400 uppercase tracking-wider px-2 py-0.5">
                      {translate(child.title, activeLang, translations)}
                    </div>
                    {renderParams(child.id)}
                  </div>
                );
              })}
            </GroupSection>
          );
        };

        return (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <button
                onClick={() => setParamsOpen((v) => !v)}
                className="flex items-center gap-1 text-xs font-semibold text-gray-500 uppercase tracking-wider px-1 hover:text-gray-700 transition-colors"
              >
                <svg
                  className={`w-3 h-3 transition-transform duration-150 ${paramsOpen ? 'rotate-90' : ''}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
                {t('preview.parameters')} ({visibleParamCount})
              </button>
              {paramsOpen && totalParamGroups > 1 && (
                <button
                  onClick={() => {
                    if (allParamGroupsCollapsed) {
                      setCollapsedParamGroups(new Set());
                    } else {
                      setCollapsedParamGroups(new Set([...allGroupIds, '__ungrouped__']));
                    }
                  }}
                  className="text-gray-400 hover:text-gray-600 transition-colors"
                  title={allParamGroupsCollapsed ? t('misc.expandAll') : t('misc.collapseAll')}
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    {allParamGroupsCollapsed
                      ? <path strokeLinecap="round" strokeLinejoin="round" d="M15 3h6m0 0v6m0-6l-7 7M9 21H3m0 0v-6m0 6l7-7" />
                      : <path strokeLinecap="round" strokeLinejoin="round" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5" />
                    }
                  </svg>
                </button>
              )}
            </div>

            {paramsOpen && <>
              {topLevelGroups.map((group) => renderParamGroup(group))}

              {/* Параметры без группы */}
              {(() => {
                const ungroupedParams = Object.entries(parameters).filter(
                  ([, p]) => !p.group || !groupIds.has(p.group)
                );
                if (ungroupedParams.length === 0) return null;
                return (
                  <GroupSection
                    title={t('preview.general')}
                    expanded={!collapsedParamGroups.has('__ungrouped__')}
                    onToggle={() => setCollapsedParamGroups((prev) => {
                      const next = new Set(prev);
                      if (next.has('__ungrouped__')) next.delete('__ungrouped__');
                      else next.add('__ungrouped__');
                      return next;
                    })}
                  >
                    {ungroupedParams.filter(([, p]) => evaluateCondition(p.condition, conditionValues) !== false).map(([key, param]) => (
                      <ParameterPreview
                        key={key}
                        paramKey={key}
                        param={{ ...param, enum_titles: translateEnumTitles(param.enum_titles, activeLang, translations) }}
                        registerId={findRegisterId(param.title ?? key, registers, highlightedRegisterId)}
                        displayName={translate(param.title ?? key, activeLang, translations)}
                        displayDescription={param.description ? translate(param.description, activeLang, translations) : undefined}
                        onValueChange={onValueChange}
                      />
                    ))}
                  </GroupSection>
                );
              })()}
            </>}
          </div>
        );
      })()}
    </div>
  );
}
