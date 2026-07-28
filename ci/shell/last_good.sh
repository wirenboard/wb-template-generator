#!/usr/bin/env bash
# Break-glass-зеркало last-good на сервере (стандарт деплоя, PRJ-1089).
#
# Источник правды о выкатах — журнал (GitHub Deployments API). Файл на сервере нужен
# ровно для одного случая: GitHub недоступен, а откатиться надо руками. Поэтому здесь
# только две операции, и обе — из workflow, а не из YAML-инлайна:
#
#   last_good.sh read          — вывести last-good SHA (пусто, если его нет)
#   last_good.sh write <sha>   — записать SHA, сдвинув предыдущий в last-good-sha.prev
#
# Хранится ДВА значения (current + prev) осознанно: сбой, проявившийся через часы после
# успешного smoke, оставил бы в единственном файле саму плохую версию.
#
# Окружение: DEPLOY_HOST (user@host), DEPLOY_DIR (каталог со стеком).
set -euo pipefail

CMD="${1:?Usage: last_good.sh read|write <sha>}"
DEPLOY_HOST="${DEPLOY_HOST:?set DEPLOY_HOST=user@host}"
DEPLOY_DIR="${DEPLOY_DIR:-/srv/wb-template-generator}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

# Полный 40-символьный hex — форма проверяется и на чтении (файл на сервере = внешний
# вход: мусор оттуда иначе уехал бы в docker pull посреди аварийного отката), и на записи.
valid_sha() {
  local s="$1"
  [ "${#s}" -eq 40 ] && [ -z "${s//[0-9a-f]/}" ]
}

case "${CMD}" in
  read)
    sha="$(ssh "${SSH_OPTS[@]}" "${DEPLOY_HOST}" "cat '${DEPLOY_DIR}/last-good-sha'" 2>/dev/null || true)"
    sha="$(printf '%s' "${sha}" | tr -d '[:space:]')"
    if [ -z "${sha}" ]; then
      exit 0                       # нет зеркала — это не ошибка, вызывающий решает сам
    fi
    if ! valid_sha "${sha}"; then
      echo "❌ last-good-sha содержит не git-SHA: «${sha}»" >&2
      exit 1
    fi
    printf '%s\n' "${sha}"
    ;;
  write)
    sha="${2:?Usage: last_good.sh write <sha>}"
    valid_sha "${sha}" || { echo "❌ «${sha}» — не полный 40-символьный git-SHA" >&2; exit 1; }
    ssh "${SSH_OPTS[@]}" "${DEPLOY_HOST}" \
      "cd '${DEPLOY_DIR}' \
       && { [ -f last-good-sha ] && cp last-good-sha last-good-sha.prev || true; } \
       && printf '%s\n' '${sha}' > last-good-sha"
    echo "🔖 last-good обновлён: ${sha}"
    ;;
  *)
    echo "❌ неизвестная команда «${CMD}» (ожидается read|write)" >&2
    exit 1
    ;;
esac
