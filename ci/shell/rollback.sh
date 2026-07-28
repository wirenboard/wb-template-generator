#!/usr/bin/env bash
# Откат на прошлый хороший SHA (стандарт деплоя, PRJ-1089). Тот же путь, что deploy:
# образы неизменяемы и уже в реестре → откат = выкат прошлого тега (секунды, без пересборки).
#
# Аргумент (необязательно): TAG для отката. Если пусто — берём last-good-sha с сервера.
# NB (двухфазность §7.1): last-good-sha обновляется ТОЛЬКО после успешного smoke. Поэтому:
#   - текущий выкат провалился → в last-good-sha всё ещё предыдущая хорошая (то, что нужно);
#   - беда проявилась ПОЗЖЕ успешного smoke → last-good-sha уже указывает на плохую версию,
#     цель тогда — last-good-sha.prev (история из двух значений) или явный TAG.
set -euo pipefail

TAG_ARG="${1:-}"
DEPLOY_HOST="${DEPLOY_HOST:?set DEPLOY_HOST=user@host}"
DEPLOY_DIR="${DEPLOY_DIR:-/srv/wb-template-generator}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

TARGET="${TAG_ARG}"
if [ -z "${TARGET}" ]; then
  # shellcheck disable=SC2029  # DEPLOY_DIR намеренно раскрывается на клиенте (задан здесь же)
  TARGET="$(ssh "${SSH_OPTS[@]}" "${DEPLOY_HOST}" "cat '${DEPLOY_DIR}/last-good-sha'" 2>/dev/null || true)"
  TARGET="$(printf '%s' "${TARGET}" | tr -d '[:space:]')"
fi
[ -n "${TARGET}" ] || { echo "❌ Не найден целевой SHA для отката (нет last-good-sha и TAG не задан)." >&2; exit 1; }

# Значение приходит из файла на сервере, т.е. извне: проверяем форму до подстановки
# в docker-теги и git-команды. Мусор в файле (обрезанный SHA, сообщение об ошибке)
# иначе уехал бы в pull и упал бы посреди аварийного отката.
case "${TARGET}" in
  [0-9a-f]*) : ;;
  *) echo "❌ last-good-sha содержит не git-SHA: «${TARGET}»" >&2; exit 1 ;;
esac
[ "${#TARGET}" -eq 40 ] || { echo "❌ ожидается полный 40-символьный git-SHA, получено «${TARGET}»" >&2; exit 1; }
[ -z "${TARGET//[0-9a-f]/}" ] || { echo "❌ в SHA есть недопустимые символы: «${TARGET}»" >&2; exit 1; }

echo "↩️  Rollback wb-template-generator → ${TARGET}"
# Переиспользуем deploy.sh: откат — это обычный выкат прошлого неизменяемого образа
# (compose-файл он возьмёт из git на этом же SHA — см. deploy.sh).
exec "$(dirname "$0")/deploy.sh" "${TARGET}"
