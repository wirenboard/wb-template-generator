#!/usr/bin/env bash
# Сторож свежести: не даём выкатить ветку, отставшую от main (ловит re-run старого прогона).
set -euo pipefail

git fetch origin main --quiet
behind="$(git rev-list --left-right --count origin/main...HEAD | cut -f1)"

if [ "${behind:-0}" -gt 0 ]; then
  echo "❌ Ветка отстала от origin/main на ${behind} коммит(ов). Подтяни main и повтори." >&2
  exit 1
fi
echo "✅ Ветка свежая относительно origin/main."
