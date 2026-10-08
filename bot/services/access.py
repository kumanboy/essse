from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo
import logging
from bot.services.permissions import require_admin

log = logging.getLogger(__name__)


def free_period_end(settings):
    start = settings["access_start"]
    return start.astimezone(timezone.utc) + timedelta(hours=24 * settings["free_access_days"]) if start else None


def current_mode(settings, now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("Timezone-aware datetime required")
    if not settings["bot_enabled"]:
        return "disabled"
    start, end = settings["access_start"], free_period_end(settings)
    if start and now < start:
        return "not_started"
    if start and start <= now < end:
        return "promotion"
    local = now.astimezone(ZoneInfo(settings["timezone"])).time()
    opening, closing = settings["daily_open_time"], settings["daily_close_time"]
    within = opening <= local < closing if opening < closing else local >= opening or local < closing
    return "daily_open" if within else "daily_closed"


def is_available(settings, now: datetime) -> bool:
    return current_mode(settings, now) in {"promotion", "daily_open"}


class AccessService:
    def __init__(self, pool, admin_id: int):
        self.pool, self.admin_id = pool, admin_id

    async def get_settings(self):
        return await self.pool.fetchrow("SELECT *, clock_timestamp() AS db_now FROM bot_settings WHERE id=1")

    async def available(self):
        row = await self.get_settings()
        allowed = is_available(row, row["db_now"])
        if not allowed:
            log.info("access_denied mode=%s", current_mode(row, row["db_now"]))
        return allowed

    async def update(self, actor: int, **changes):
        require_admin(actor, self.admin_id)
        allowed = {"access_start", "free_access_days", "daily_open_time", "daily_close_time", "timezone", "bot_enabled"}
        if not changes or not changes.keys() <= allowed:
            raise ValueError("Unknown setting")
        if "free_access_days" in changes and not 1 <= changes["free_access_days"] <= 365:
            raise ValueError("Kunlar soni 1–365 oralig‘ida bo‘lsin.")
        if "timezone" in changes:
            ZoneInfo(changes["timezone"])
        for key in ("daily_open_time", "daily_close_time"):
            if key in changes and not isinstance(changes[key], time):
                raise ValueError("Vaqt HH:MM shaklida bo‘lsin.")
        if changes.get("access_start") and changes["access_start"].tzinfo is None:
            raise ValueError("Timezone required")
        async with self.pool.acquire() as conn, conn.transaction():
            old = await conn.fetchrow("SELECT * FROM bot_settings WHERE id=1 FOR UPDATE")
            new = dict(old) | changes
            if new["daily_open_time"] == new["daily_close_time"]:
                raise ValueError("Ochilish va yopilish vaqti bir xil bo‘lmasin.")
            assignments = ", ".join(f"{k}=${i}" for i, k in enumerate(changes, 2))
            await conn.execute(f"UPDATE bot_settings SET {assignments}, updated_by=$1, updated_at=now() WHERE id=1", actor, *changes.values())
        log.info("admin_settings_changed actor=%s fields=%s", actor, ",".join(changes))
