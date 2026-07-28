#!/usr/bin/env bash
# Выкат неизменяемого образа по git-SHA на сервер (стандарт деплоя, PRJ-1089).
#
# Требуемое окружение (из секретов GitHub / среды):
#   DEPLOY_HOST   — user@host боевого сервера
#   DEPLOY_DIR    — каталог с docker-compose.deploy.yml + .env на сервере (напр. /srv/wbtg)
#   REGISTRY      — префикс реестра (по умолчанию ghcr.io/wirenboard)
#   SSH настроен заранее (ключ в ssh-agent); jump-host — по желанию через ~/.ssh/config
#
# Аргумент: TAG (git-SHA) выкатываемого образа.
set -euo pipefail

TAG="${1:?Usage: deploy.sh <git-sha>}"
REGISTRY="${REGISTRY:-ghcr.io/wirenboard}"
DEPLOY_HOST="${DEPLOY_HOST:?set DEPLOY_HOST=user@host}"
DEPLOY_DIR="${DEPLOY_DIR:-/srv/wb-template-generator}"
COMPOSE_FILE="docker-compose.deploy.yml"

# Таймауты обязательны: без них зависший сервер держит ssh — а вместе с ним и
# concurrency-лок прода — до предельного времени job'а, и кнопка отката всё это
# время заблокирована.
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)
REMOTE_TIMEOUT="${REMOTE_TIMEOUT:-600}"   # предел на удалённую часть (pull + rolling + verify)

echo "🚀 Deploy wb-template-generator @ ${TAG} → ${DEPLOY_HOST}:${DEPLOY_DIR}"

# Конфигурация выката приезжает ИЗ GIT, причём из ТОГО ЖЕ коммита, что и образы.
# Не из текущего checkout: иначе откат на прошлый SHA поехал бы со свежим compose-файлом
# при старых образах — и если выкат сломал именно compose, то и авто-откат, и кнопка
# отката упали бы на том же файле. Дом compose-файла — репозиторий (копия на сервере = кэш).
git cat-file -e "${TAG}^{commit}" 2>/dev/null \
  || { echo "❌ коммит ${TAG} не найден локально — нужен полный checkout (fetch-depth: 0)" >&2; exit 1; }
git show "${TAG}:${COMPOSE_FILE}" \
  | ssh "${SSH_OPTS[@]}" "${DEPLOY_HOST}" "cat > '${DEPLOY_DIR}/${COMPOSE_FILE}'"
echo "📄 compose доставлен из git @ ${TAG}"

# Откуда запущен механизм: ci (GitHub Actions) или manual (рука/инцидент) — для нижнего журнала.
RUN_SOURCE="${GITHUB_ACTIONS:+ci}"; RUN_SOURCE="${RUN_SOURCE:-manual}"

# Всё выполняем ОДНОЙ ssh-сессией на сервере. Логика — здесь (в скрипте), а не в YAML.
timeout "${REMOTE_TIMEOUT}" \
ssh "${SSH_OPTS[@]}" "${DEPLOY_HOST}" REGISTRY="${REGISTRY}" DEPLOY_TAG="${TAG}" DEPLOY_DIR="${DEPLOY_DIR}" \
    RUN_SOURCE="${RUN_SOURCE}" bash -s <<'REMOTE'
set -euo pipefail
cd "${DEPLOY_DIR}"
export REGISTRY DEPLOY_TAG

# Журнал на уровне МЕХАНИЗМА (§4.5): след пишет сам скрипт — при любом способе запуска
# (из CI, руками в break-glass). Человеку записывать ничего не нужно: дёрнул — след есть.
# ЕДИНЫЙ журнал хоста (тот же, куда пишет ansible-роль);
# если /var/log недоступен деплой-пользователю — фолбэк рядом с приложением.
HISTORY_LOG="${DEPLOY_HISTORY_LOG:-/var/log/wb-deploy-history.log}"
[ -w "$HISTORY_LOG" ] || [ -w "$(dirname "$HISTORY_LOG")" ] || HISTORY_LOG="${DEPLOY_DIR}/deploy-history.log"
echo "$(date -Is) deploy unit=$(basename "${DEPLOY_DIR}") tag=${DEPLOY_TAG} src=${RUN_SOURCE} user=$(id -un)" >> "$HISTORY_LOG"

COMPOSE="docker compose -f docker-compose.deploy.yml"

echo "⬇️  pull ${DEPLOY_TAG}"
$COMPOSE pull

# --- backend: rolling-update без простоя ---------------------------------------
# backend НЕ публикует хостовый порт (его проксирует frontend nginx), поэтому можно
# поднять новый контейнер рядом, дождаться healthy и снять старый — docker-rollout.
# Если плагина нет — фолбэк на recreate (кратковременный разрыв backend-запросов).
if docker rollout --help >/dev/null 2>&1; then
  echo "♻️  backend: docker rollout (zero-downtime)"
  docker rollout -f docker-compose.deploy.yml backend
else
  echo "⚠️  docker-rollout не установлен → backend recreate (возможен кратковременный разрыв)"
  $COMPOSE up -d --wait backend
fi

# --- frontend: edge-сервис публикует :80 -------------------------------------
# ГРЕЙ-ЗОНА (в логе дыр): два контейнера не могут держать один хостовый порт :80,
# поэтому zero-downtime для edge nginx нативным compose НЕ достигается — это recreate
# с миганием в ~1–2с. Настоящий zero-downtime тут требует внешнего реверс-прокси
# (traefik/второй nginx) ИЛИ blue-green со сменой порта. Пока — recreate + --wait.
echo "♻️  frontend: recreate (--wait; кратковременное мигание edge, см. лог дыр)"
$COMPOSE up -d --wait frontend

# --- verify -------------------------------------------------------------------
# На Compose НЕТ нативного авто-отката (в отличие от Swarm failure_action: rollback).
# `--wait` выше уже падает, если контейнер не стал healthy → сюда дойдём только если ок.
echo "🔎 verify: backend/frontend healthy"
$COMPOSE ps

# ВАЖНО (§7.1, двухфазный last-good): здесь last-good НЕ пишем — контейнер healthy
# ещё не значит «хороший» (smoke впереди). Запись last-good (break-glass-зеркало) делает
# отдельный шаг workflow ПОСЛЕ smoke; источник правды — журнал (Deployments API).
echo "✅ deploy ok (кандидат; «хорошим» станет после smoke)"
REMOTE

echo "✅ Deploy завершён: ${TAG}"
