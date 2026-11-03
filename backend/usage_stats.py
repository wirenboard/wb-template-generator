"""Статистика использования по дням в SQLite: события и браузеры, которые их совершили."""

import logging
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Потолок новых браузеров в сутки: сверх него события идут без идентификатора, база не раздувается
MAX_CLIENTS_PER_DAY = 2000

_STARTED = ("analyze_server", "analyze_custom", "import_template", "import_csv")
_DOWNLOADED = ("download_json", "download_jinja")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage (
    day TEXT NOT NULL,
    client_id TEXT NOT NULL,
    event TEXT NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (day, client_id, event)
) WITHOUT ROWID
"""


def _today() -> date:
    return datetime.now(timezone.utc).date()


def parse_client_id(value: str | None) -> str:
    """UUID в каноническом виде или пустая строка, если заголовка нет или он битый."""
    if not value or len(value) > 64:
        return ""
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return ""


class UsageStats:
    """Счётчики событий по дням и браузерам, хранятся `retention_days` дней."""

    def __init__(self, path: str, retention_days: int):
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._read_lock = threading.Lock()
        self._day = ""
        self._clients_today: set[str] = set()
        self._write_failed = False
        self._conn = sqlite3.connect(path, check_same_thread=False)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(_SCHEMA)
            self._conn.commit()
            self._roll_day(_today())
            # Сводка читает через своё соединение: в WAL чтение не ждёт запись
            self._read = sqlite3.connect(path, check_same_thread=False)
        except sqlite3.Error:
            self._conn.close()
            raise

    def _roll_day(self, today: date) -> None:
        """На смене суток удаляет устаревшие дни и перечитывает браузеры текущих суток."""
        day = today.isoformat()
        oldest = (today - timedelta(days=self._retention_days - 1)).isoformat()
        self._conn.execute("DELETE FROM usage WHERE day < ?", (oldest,))
        self._conn.commit()
        rows = self._conn.execute(
            "SELECT DISTINCT client_id FROM usage WHERE day = ? AND client_id != ''", (day,),
        )
        self._clients_today = {r[0] for r in rows}
        self._day = day

    def record(self, event: str, client_id: str, today: date | None = None) -> None:
        """Прибавляет событие к счётчику дня. Сбой записи только логируется."""
        today = today or _today()
        with self._lock:
            try:
                if today.isoformat() != self._day:
                    self._roll_day(today)
                if client_id and client_id not in self._clients_today:
                    if len(self._clients_today) >= MAX_CLIENTS_PER_DAY:
                        client_id = ""
                    else:
                        self._clients_today.add(client_id)
                self._conn.execute(
                    "INSERT INTO usage (day, client_id, event, count) VALUES (?, ?, ?, 1) "
                    "ON CONFLICT (day, client_id, event) DO UPDATE SET count = count + 1",
                    (self._day, client_id, event),
                )
                self._conn.commit()
                self._write_failed = False
            except sqlite3.Error:
                # Одно предупреждение на серию сбоев, а не на каждый запрос
                if not self._write_failed:
                    logger.warning("Статистика использования не записана", exc_info=True)
                self._write_failed = True

    def report(self, days: int, today: date | None = None) -> dict[str, Any]:
        """Сводка за последние `days` суток, включая текущие. Сбой чтения — `enabled: false`."""
        try:
            return self._report(days, today or _today())
        except sqlite3.Error:
            logger.warning("Сводка статистики не построена", exc_info=True)
            return {"enabled": False}

    def _report(self, days: int, today: date) -> dict[str, Any]:
        start = (today - timedelta(days=days - 1)).isoformat()
        q = self._read.execute
        with self._read_lock:
            def distinct_clients(events: tuple[str, ...]) -> int:
                marks = ",".join("?" * len(events))
                return int(q(
                    f"SELECT COUNT(DISTINCT client_id) FROM usage "
                    f"WHERE day >= ? AND client_id != '' AND event IN ({marks})",
                    (start, *events),
                ).fetchone()[0])

            unique = q(
                "SELECT COUNT(DISTINCT client_id) FROM usage WHERE day >= ? AND client_id != ''",
                (start,),
            ).fetchone()[0]
            returning = q(
                "SELECT COUNT(*) FROM (SELECT client_id FROM usage WHERE day >= ? AND client_id != '' "
                "GROUP BY client_id HAVING COUNT(DISTINCT day) > 1)",
                (start,),
            ).fetchone()[0]
            by_day = q(
                "SELECT day, COUNT(DISTINCT NULLIF(client_id, '')) FROM usage WHERE day >= ? "
                "GROUP BY day ORDER BY day",
                (start,),
            ).fetchall()
            events = q(
                "SELECT event, SUM(count), COUNT(DISTINCT NULLIF(client_id, '')) FROM usage "
                "WHERE day >= ? GROUP BY event ORDER BY event",
                (start,),
            ).fetchall()
            top = q(
                "SELECT SUM(count) AS n FROM usage WHERE day >= ? AND client_id != '' "
                "AND event != 'page_open' GROUP BY client_id ORDER BY n DESC LIMIT 10",
                (start,),
            ).fetchall()
            funnel = {
                "opened": distinct_clients(("page_open",)),
                "started": distinct_clients(_STARTED),
                "downloaded": distinct_clients(_DOWNLOADED),
            }

        return {
            "enabled": True,
            "from": start,
            "to": today.isoformat(),
            "unique_clients": unique,
            "returning_clients": returning,
            "clients_by_day": {day: n for day, n in by_day},
            "funnel": funnel,
            "events": {e: {"count": n, "clients": c} for e, n, c in events},
            "top_clients_actions": [r[0] for r in top],
        }

    def close(self) -> None:
        with self._lock, self._read_lock:
            self._read.close()
            self._conn.close()


def open_usage_stats(path: str, retention_days: int) -> UsageStats | None:
    """Открывает базу статистики; пустой путь или сбой открытия — статистика выключена."""
    if not path:
        return None
    try:
        return UsageStats(path, retention_days)
    except sqlite3.Error:
        logger.warning("Статистика использования выключена: база %s не открылась", path, exc_info=True)
        return None
