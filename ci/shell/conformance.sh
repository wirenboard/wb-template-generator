#!/usr/bin/env bash
# conformance.sh — проверка репозитория на соответствие prod-ready гейту стандарта деплоя.
# v1: СТАТИЧЕСКИЕ проверки файлов репо (~80% ценности); runtime-сверки (журнал ↔ прод,
# профиль ↔ реестр, ci/ ↔ эталон) — v2.
#
# Запуск из корня репозитория сервиса:  ci/shell/conformance.sh   (или make conformance)
# Типы проверок (легенда §5.2 стандарта):
#   🔒 hard    — без этого гейт не пройден (провал → ненулевой код выхода);
#   👁 monitor — выкатить можно, но фиксируется тех-долг (тикет заводит человек).
# Код выхода = число проваленных 🔒-проверок.
set -uo pipefail

PASS=0; WARN=0; FAIL=0
ok()   { printf '  ✅ %s\n' "$1"; PASS=$((PASS+1)); }
warn() { printf '  👁 %s → тикет тех-долга (заводится вручную)\n' "$1"; WARN=$((WARN+1)); }
fail() { printf '  ❌ %s (🔒 hard)\n' "$1"; FAIL=$((FAIL+1)); }

WF=".github/workflows"
COMPOSE="docker-compose.deploy.yml"

echo "── Конформанс prod-ready гейту: $(basename "$(pwd)") ──"

# ── 🔒 механика конвейера ─────────────────────────────────────────────────────
if grep -rqs 'environment: production' "$WF"/; then
  ok "прод-выкат идёт через среду production"
else
  fail "нет workflow с 'environment: production' — прод-секреты вне контроля среды"
fi

if grep -rqs 'github\.sha' "$WF"/; then
  ok "сборка/выкат по git-SHA (неизменяемый якорь)"
else
  fail "в workflows нет \${{ github.sha }} — образы не привязаны к коммиту"
fi

if [ -f "$COMPOSE" ]; then
  if grep -Eqs '^\s+build:' "$COMPOSE"; then
    fail "$COMPOSE содержит build: — сборка на сервере запрещена (только CI)"
  else
    ok "$COMPOSE без build: (сборка только в CI)"
  fi
  if grep -qs ':latest' "$COMPOSE"; then
    fail "$COMPOSE ссылается на :latest — прод адресуется только по SHA"
  else
    ok "$COMPOSE без :latest"
  fi
else
  # сервис на Swarm-стеке или нестандартный (§9) — проверить стек-файл руками
  warn "нет $COMPOSE — если деплой стеком/нестандартный, проверь файл выката руками"
fi

if [ -f "$WF/rollback.yml" ] && grep -qs 'workflow_dispatch' "$WF/rollback.yml"; then
  ok "кнопка отката (rollback.yml с workflow_dispatch)"
else
  fail "нет $WF/rollback.yml с workflow_dispatch — отката одной кнопкой нет"
fi

if grep -rqs 'createDeployment' "$WF"/; then
  ok "журнал выкатов пишется (Deployments API)"
else
  fail "нет записи в журнал (createDeployment) — выкаты будут невидимы"
fi

if grep -rqs 'make smoke\|smoke\.sh' "$WF"/; then
  ok "smoke-проверка после выката подключена"
else
  fail "smoke не подключён в конвейер — «выкатили и надеемся»"
fi

if grep -rqs 'guard.staleness\|guard_staleness' "$WF"/ Makefile 2>/dev/null; then
  ok "сторож свежести подключён"
else
  fail "нет сторожа свежести — возможен молчаливый откат старой веткой"
fi

if grep -rqs 'make test' "$WF"/; then
  ok "тесты гоняются в CI (make test)"
else
  fail "в workflows нет make test — тесты не блокируют merge"
fi

if git ls-files 2>/dev/null | grep -qE '(^|/)\.env$'; then
  fail ".env закоммичен в git — секреты в репозитории запрещены"
else
  ok "секретов в git нет (.env не отслеживается)"
fi

# ── 👁 monitor: выкатить можно, но фиксируется тех-долг ───────────────────────
DFILES=$(git ls-files 2>/dev/null | grep -E '(^|/)Dockerfile' || true)
if [ -n "$DFILES" ]; then
  # именно `grep -qs` + инверсия: у `grep -L` семантика кода возврата менялась между
  # версиями grep, и в паре с -q проверка молча вырождалась в «всегда ок»
  MISS=$(for f in $DFILES; do grep -qs 'HEALTHCHECK' "$f" || echo "$f"; done)
  if [ -z "$MISS" ]; then
    ok "HEALTHCHECK есть во всех Dockerfile"
  else
    warn "HEALTHCHECK отсутствует: $(echo "$MISS" | tr '\n' ' ')"
  fi
else
  warn "Dockerfile не найден — образ собирается вне репо?"
fi

if grep -rqs 'EXPECT_SHA' "$WF"/ ci/ 2>/dev/null; then
  ok "smoke сверяет ревизию (EXPECT_SHA ↔ /api/status)"
else
  warn "нет сверки ревизии в smoke — «выкатили этот SHA» не подтверждается"
fi

if grep -rqs 'concurrency' "$WF"/; then
  ok "прод-выкаты сериализованы (concurrency group)"
else
  warn "нет concurrency group — два выката могут поехать одновременно"
fi

if grep -rqs 'DEPLOY_KNOWN_HOSTS' "$WF"/; then
  ok "отпечаток сервера закреплён (pinned known_hosts)"
elif grep -rqs 'ssh-keyscan' "$WF"/; then
  warn "ssh-keyscan на каждом прогоне (TOFU) — закрепи отпечаток в DEPLOY_KNOWN_HOSTS"
else
  warn "known_hosts не настроен — первый ssh из CI упадёт или доверится вслепую"
fi

if grep -rqs 'hadolint' "$WF"/ Makefile 2>/dev/null; then
  ok "hadolint прогоняется"
else
  warn "hadolint не прогоняется — контейнерные файлы без линта"
fi

# Скрипты выката — такой же прод-код, как приложение: они ходят на боевой сервер.
# Без линта опечатка в bash проявляется только в момент аварийного отката.
if grep -rqs 'shellcheck' "$WF"/ Makefile 2>/dev/null; then
  ok "shellcheck прогоняется на скриптах выката"
else
  warn "shellcheck не прогоняется — деплой-скрипты без статического анализа"
fi

# ── итог ──────────────────────────────────────────────────────────────────────
echo "──"
echo "Итог: ✅ $PASS · 👁 $WARN (тех-долг) · ❌ $FAIL (🔒 гейт)"
if [ "$FAIL" -eq 0 ]; then
  echo "Гейт prod-ready: ПРОЙДЕН$( [ "$WARN" -gt 0 ] && echo " (с $WARN тех-долгами — заведи тикеты)" )"
else
  echo "Гейт prod-ready: НЕ пройден — $FAIL жёстких требований не выполнено"
fi
exit "$FAIL"
