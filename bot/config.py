"""Validate deployment settings without logging secret values."""
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    bot_token: str = field(repr=False)
    admin_id: int
    database_url: str = field(repr=False)
    openai_api_key: str = field(repr=False)
    webhook_secret: str = field(repr=False)
    cron_secret: str = field(repr=False)
    public_base_url: str
    model: str = "gpt-5.6-sol"
    reasoning_effort: str = "high"
    channel_username: str = "@sardortoshmuhammad_onatili"
    timezone: str = "Asia/Tashkent"
    database_ssl: bool = True

    @classmethod
    def load(cls):
        load_dotenv()
        names = ("BOT_TOKEN", "ADMIN_ID", "DATABASE_URL", "OPENAI_API_KEY",
                 "TELEGRAM_WEBHOOK_SECRET", "CRON_SECRET", "PUBLIC_BASE_URL")
        missing = [n for n in names if not os.getenv(n, "").strip()]
        if missing:
            raise RuntimeError("Missing environment settings: " + ", ".join(missing))
        admin = os.environ["ADMIN_ID"]
        if not admin.isdecimal() or int(admin) <= 0:
            raise RuntimeError("ADMIN_ID must be a positive Telegram user ID")
        secret = os.environ["TELEGRAM_WEBHOOK_SECRET"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", secret):
            raise RuntimeError("TELEGRAM_WEBHOOK_SECRET requires 32–256 URL-safe characters")
        if len(os.environ["CRON_SECRET"]) < 32:
            raise RuntimeError("CRON_SECRET requires at least 32 characters")
        base = os.environ["PUBLIC_BASE_URL"].rstrip("/")
        url = urlsplit(base)
        if url.scheme != "https" or not url.netloc or url.path or url.query or url.fragment or url.username:
            raise RuntimeError("PUBLIC_BASE_URL must be an HTTPS origin")
        if urlsplit(os.environ["DATABASE_URL"]).scheme not in {"postgres", "postgresql"}:
            raise RuntimeError("DATABASE_URL must be a PostgreSQL connection URI")
        tz = os.getenv("TIMEZONE", "Asia/Tashkent")
        try:
            ZoneInfo(tz)
        except (ValueError, KeyError):
            raise RuntimeError("TIMEZONE must be a valid IANA timezone") from None
        effort = os.getenv("OPENAI_REASONING_EFFORT", "high")
        if effort not in {"high", "xhigh", "max"}:
            raise RuntimeError("OPENAI_REASONING_EFFORT must be high, xhigh or max")
        ssl = os.getenv("DATABASE_SSL", "true").lower()
        if ssl not in {"true", "false"}:
            raise RuntimeError("DATABASE_SSL must be true or false")
        return cls(os.environ["BOT_TOKEN"], int(admin), os.environ["DATABASE_URL"],
                   os.environ["OPENAI_API_KEY"], secret, os.environ["CRON_SECRET"], base,
                   os.getenv("OPENAI_MODEL", "gpt-5.6-sol"), effort,
                   os.getenv("CHANNEL_USERNAME", "@sardortoshmuhammad_onatili"), tz,
                   ssl == "true")
