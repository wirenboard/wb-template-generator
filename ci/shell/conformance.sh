#!/usr/bin/env bash
# Проверка репозитория на соответствие prod-ready гейту стандарта деплоя.
# 🔒 hard — без этого гейт не пройден; 👁 monitor — выкатить можно, но это тех-долг.
# Код выхода = число проваленных 🔒-проверок. v1: только статические проверки файлов.
set -uo pipefail

PASS=0; WARN=0; FAIL=0
ok()   { printf '  ✅ %s\n' "$1"; PASS=$((PASS+1)); }
warn() { printf '  👁 %s → тикет тех-долга\n' "$1"; WARN=$((WARN+1)); }
fail() { printf '  ❌ %s (🔒 hard)\n' "$1"; FAIL=$((FAIL+1)); }

WF=".github/workflows"
ACT=".github/actions"
COMPOSE="docker-compose.deploy.yml"

echo "── Конформанс prod-ready гейту: $(basename "$(pwd)") ──"

# ── 🔒 механика конвейера ─────────────────────────────────────────────────────
grep -rqs 'environment: production' "$WF"/ \
  && ok "прод-выкат идёт через среду production" \
  || fail "нет workflow с 'environment: production' — прод-секреты вне контроля среды"

grep -rqs 'github\.sha' "$WF"/ \
  && ok "сборка/выкат по git-SHA (неизменяемый якорь)" \
  || fail "в workflows нет \${{ github.sha }} — образы не привязаны к коммиту"

if [ -f "$COMPOSE" ]; then
  grep -Eqs '^\s+build:' "$COMPOSE" \
    && fail "$COMPOSE содержит build: — сборка на сервере запрещена (только CI)" \
    || ok "$COMPOSE без build: (сборка только в CI)"
  grep -qs ':latest' "$COMPOSE" \
    && fail "$COMPOSE ссылается на :latest — прод адресуется только по SHA" \
    || ok "$COMPOSE без :latest"
else
  warn "нет $COMPOSE — если деплой стеком/нестандартный, проверь файл выката руками"
fi

[ -f "$WF/rollback.yml" ] && grep -qs 'workflow_dispatch' "$WF/rollback.yml" \
  && ok "кнопка отката (rollback.yml с workflow_dispatch)" \
  || fail "нет $WF/rollback.yml с workflow_dispatch — отката одной кнопкой нет"

# журнал: своим github-script или готовым действием — оба варианта равноправны
grep -rqs 'createDeployment\|bobheadxi/deployments' "$WF"/ \
  && ok "журнал выкатов пишется (Deployments API)" \
  || fail "нет записи в журнал — выкаты будут невидимы"

grep -rqs 'make smoke\|smoke\.sh' "$WF"/ \
  && ok "smoke-проверка после выката подключена" \
  || fail "smoke не подключён в конвейер — «выкатили и надеемся»"

grep -rqs 'guard.staleness\|guard_staleness' "$WF"/ Makefile 2>/dev/null \
  && ok "сторож свежести подключён" \
  || fail "нет сторожа свежести — возможен молчаливый откат старой веткой"

grep -rqs 'make test' "$WF"/ \
  && ok "тесты гоняются в CI (make test)" \
  || fail "в workflows нет make test — тесты не блокируют merge"

git ls-files 2>/dev/null | grep -qE '(^|/)\.env$' \
  && fail ".env закоммичен в git — секреты в репозитории запрещены" \
  || ok "секретов в git нет (.env не отслеживается)"

# ── 👁 monitor ────────────────────────────────────────────────────────────────
DFILES=$(git ls-files 2>/dev/null | grep -E '(^|/)Dockerfile' || true)
if [ -n "$DFILES" ]; then
  # именно `grep -qs` с инверсией: у `grep -L` код возврата менялся между версиями
  MISS=$(for f in $DFILES; do grep -qs 'HEALTHCHECK' "$f" || echo "$f"; done)
  [ -z "$MISS" ] && ok "HEALTHCHECK есть во всех Dockerfile" \
    || warn "HEALTHCHECK отсутствует: $(echo "$MISS" | tr '\n' ' ')"
else
  warn "Dockerfile не найден — образ собирается вне репо?"
fi

grep -rqs 'EXPECT_SHA' "$WF"/ "$ACT"/ ci/ 2>/dev/null \
  && ok "smoke сверяет ревизию (EXPECT_SHA ↔ /api/status)" \
  || warn "нет сверки ревизии в smoke — «выкатили этот SHA» не подтверждается"

grep -rqs 'concurrency' "$WF"/ \
  && ok "прод-выкаты сериализованы (concurrency group)" \
  || warn "нет concurrency group — два выката могут поехать одновременно"

if grep -rqs 'fingerprint\|DEPLOY_KNOWN_HOSTS' "$WF"/ "$ACT"/ 2>/dev/null; then
  ok "отпечаток сервера закреплён"
elif grep -rqs 'ssh-keyscan' "$WF"/ "$ACT"/ 2>/dev/null; then
  warn "ssh-keyscan на каждом прогоне (TOFU) — закрепи отпечаток"
else
  warn "отпечаток хоста не закреплён — ssh из CI упадёт или доверится вслепую"
fi

# сторонние действия держат прод-ключи: тег в чужом репо можно передвинуть
UNPINNED=$(grep -rhoE 'uses: [^ ]+@[^ ]+' "$WF"/ "$ACT"/ 2>/dev/null \
  | grep -vE 'uses: (\./|actions/)' | grep -vE '@[0-9a-f]{40}$' || true)
if [ -z "$UNPINNED" ]; then
  ok "сторонние действия пиннуты по commit-SHA"
else
  warn "действия по тегу, не по SHA: $(echo "$UNPINNED" | sed 's/uses: //' | tr '\n' ' ')"
fi

if git ls-files 'ci/shell/*.sh' 2>/dev/null | grep -q .; then
  grep -rqs 'shellcheck' "$WF"/ Makefile 2>/dev/null \
    && ok "shellcheck прогоняется на скриптах" \
    || warn "shellcheck не прогоняется — скрипты без статического анализа"
fi

grep -rqs 'hadolint' "$WF"/ Makefile 2>/dev/null \
  && ok "hadolint прогоняется" \
  || warn "hadolint не прогоняется — контейнерные файлы без линта"

echo "──"
echo "Итог: ✅ $PASS · 👁 $WARN (тех-долг) · ❌ $FAIL (🔒 гейт)"
if [ "$FAIL" -eq 0 ]; then
  echo "Гейт prod-ready: ПРОЙДЕН$( [ "$WARN" -gt 0 ] && echo " (с $WARN тех-долгами — заведи тикеты)" )"
else
  echo "Гейт prod-ready: НЕ пройден — $FAIL жёстких требований не выполнено"
fi
exit "$FAIL"
