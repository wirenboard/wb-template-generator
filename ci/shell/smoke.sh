#!/usr/bin/env bash
# Smoke после выката: ключевые адреса отвечают 200 (стандарт деплоя, PRJ-1089).
# Если задан EXPECT_SHA — сверяем, что сервис отдаёт именно выкаченный git-SHA
# (/api/status.revision), т.е. «в проде этот коммит» подтверждается снаружи.
#
# Аргумент: BASE_URL (напр. https://template.wirenboard.com).
#
# Ретраи обязательны: от результата smoke зависит, оставить версию или откатить,
# а одиночный сетевой чих (перезапуск edge-nginx, rolling-update) дал бы ложный
# авто-откат исправной версии. Таймауты — чтобы шаг не висел до предела job'а.
set -euo pipefail

BASE="${1:?Usage: smoke.sh <base-url>}"
EXPECT_SHA="${EXPECT_SHA:-}"
ATTEMPTS="${SMOKE_ATTEMPTS:-5}"
DELAY="${SMOKE_DELAY:-3}"
CURL_OPTS=(-s --connect-timeout 5 --max-time 15)

echo "🔎 smoke: ${BASE} (до ${ATTEMPTS} попыток, пауза ${DELAY}с)"

# 200 на адресе, с ретраями
check_200() {
  local url="$1" name="$2" code=000 i
  for ((i = 1; i <= ATTEMPTS; i++)); do
    code="$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' "$url" || echo 000)"
    if [ "$code" = "200" ]; then
      echo "  ✅ ${name} → 200 (попытка ${i})"
      return 0
    fi
    echo "  … ${name} → ${code}; повтор ${i}/${ATTEMPTS}" >&2
    [ "$i" -lt "$ATTEMPTS" ] && sleep "$DELAY"
  done
  echo "❌ ${name} → ${code} после ${ATTEMPTS} попыток" >&2
  return 1
}

check_200 "${BASE}/healthz"    "frontend /healthz"
check_200 "${BASE}/api/health" "backend /api/health"

# Сверка «выкатили именно этот SHA — сервис его и отдаёт».
# Тоже с ретраями: во время rolling-update запрос может попасть на старый контейнер.
if [ -n "${EXPECT_SHA}" ]; then
  got=""
  for ((i = 1; i <= ATTEMPTS; i++)); do
    got="$(curl "${CURL_OPTS[@]}" "${BASE}/api/status" \
      | sed -n 's/.*"revision"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' || true)"
    [ "${got}" = "${EXPECT_SHA}" ] && break
    echo "  … revision=${got:-<пусто>}, ждём ${EXPECT_SHA}; повтор ${i}/${ATTEMPTS}" >&2
    [ "$i" -lt "$ATTEMPTS" ] && sleep "$DELAY"
  done
  if [ "${got}" != "${EXPECT_SHA}" ]; then
    echo "❌ revision mismatch: ждали ${EXPECT_SHA}, сервис отдаёт ${got:-<пусто>}" >&2
    exit 1
  fi
  echo "  ✅ revision совпал: ${got}"
fi

echo "✅ smoke ok"
