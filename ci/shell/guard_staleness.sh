#!/usr/bin/env bash
# PRJ-1089 — сторож свежести (боль #2): не даём выкатить ветку, отставшую от main.
# Для пилота прод идёт только из main, поэтому здесь это ~проверка HEAD == origin/main,
# но шаг оставлен по стандарту (для сервисов, где на предпрод катят feature-ветки).
set -euo pipefail

git fetch origin main --quiet
counts="$(git rev-list --left-right --count origin/main...HEAD)"  # "<отстаём>\t<опережаем>"
behind="$(echo "$counts" | cut -f1)"

if [ "${behind:-0}" -gt 0 ]; then
  echo "❌ Ветка отстала от origin/main на ${behind} коммит(ов). Подтяни main и повтори." >&2
  exit 1
fi
echo "✅ Ветка свежая относительно origin/main."
