#!/usr/bin/env bash
# Smoke после выката: адреса отвечают 200 и сервис отдаёт выкаченный SHA.
# Ретраи — чтобы одиночный сетевой чих не откатил исправную версию.
set -euo pipefail

BASE="${1:?Usage: smoke.sh <base-url>}"
CURL=(curl -fsS --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 5 --max-time 15)

"${CURL[@]}" -o /dev/null "${BASE}/healthz"
"${CURL[@]}" -o /dev/null "${BASE}/api/health"

if [ -n "${EXPECT_SHA:-}" ]; then
  for i in 1 2 3; do
    got="$("${CURL[@]}" "${BASE}/api/status" |
      sed -n 's/.*"revision"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    [ "$got" = "$EXPECT_SHA" ] && break
    [ "$i" -lt 3 ] && sleep 3
  done
  [ "$got" = "$EXPECT_SHA" ] ||
    { echo "❌ revision: ждали $EXPECT_SHA, сервис отдаёт ${got:-<пусто>}" >&2; exit 1; }
fi

echo "✅ smoke ok: ${BASE}"
