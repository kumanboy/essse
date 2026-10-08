"""Render ASGI entry point: uvicorn bot.main:app --host 0.0.0.0 --port $PORT."""
from contextlib import asynccontextmanager, AsyncExitStack
import hmac
import json
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import Update
from fastapi import FastAPI, Request, HTTPException
from pydantic import ValidationError
from openai import AsyncOpenAI
from bot.config import Config
from bot.services.db import create_pool
from bot.services.storage import PostgresStorage
from bot.services.jobs import Jobs
from bot.services.access import AccessService
from bot.services.subscription import SubscriptionService
from bot.services.essay_checker import EssayChecker
from bot.services.inbox import Inbox
from bot.services.workers import Workers
from bot.handlers import user, admin

log = logging.getLogger(__name__)


def authorized(actual: str | None, expected: str) -> bool:
    return actual is not None and hmac.compare_digest(actual.encode(), expected.encode())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Prevent HTTP libraries from writing credential-bearing URLs or headers.
    for name in ("httpx", "httpcore", "openai", "aiogram.event"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    config = Config.load()
    async with AsyncExitStack() as stack:
        pool = await create_pool(config)
        stack.push_async_callback(pool.close)
        settings = await pool.fetchrow("SELECT * FROM bot_settings WHERE id=1")
        if settings is None:
            raise RuntimeError("Run migration 001_persistent_workflow.sql before startup")
        from zoneinfo import ZoneInfo
        ZoneInfo(settings["timezone"])
        # Environment initializes untouched defaults only; admin configuration wins thereafter.
        await pool.execute("UPDATE bot_settings SET timezone=$1 WHERE id=1 AND updated_by IS NULL AND timezone='Asia/Tashkent'", config.timezone)
        log.info("database_initialized")
        bot = Bot(config.bot_token, session=AiohttpSession(timeout=30))
        stack.push_async_callback(bot.session.close)
        client = AsyncOpenAI(api_key=config.openai_api_key, timeout=330, max_retries=0)
        stack.push_async_callback(client.close)
        jobs = Jobs(pool)
        dp = Dispatcher(storage=PostgresStorage(pool), config=config, jobs=jobs,
                        subscription=SubscriptionService(bot, config.channel_username),
                        access=AccessService(pool, config.admin_id))
        dp.include_router(admin.build_router())
        dp.include_router(user.build_router())
        inbox = Inbox(pool, dp, bot)
        workers = Workers(jobs, EssayChecker(client, config), bot, inbox)
        app.state.config, app.state.inbox, app.state.workers = config, inbox, workers
        await bot.set_webhook(config.public_base_url + "/telegram/webhook",
                              secret_token=config.webhook_secret,
                              allowed_updates=["message", "callback_query"], max_connections=1,
                              drop_pending_updates=False)
        await workers.start()
        stack.push_async_callback(workers.close)
        app.state.ready = True
        log.info("bot_started")
        try:
            yield
        finally:
            app.state.ready = False


def create_app():
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        if not getattr(app.state, "ready", False):
            raise HTTPException(503, "starting")
        return {"status": "ok"}

    @app.post("/telegram/webhook")
    async def webhook(request: Request):
        config = app.state.config
        if not authorized(request.headers.get("X-Telegram-Bot-Api-Secret-Token"), config.webhook_secret):
            raise HTTPException(403, "Forbidden")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 262144:
                raise HTTPException(413, "Update too large")
        try:
            update = Update.model_validate(json.loads(body))
        except (ValidationError, ValueError, UnicodeError):
            raise HTTPException(400, "Invalid update") from None
        await app.state.inbox.receive(update)  # Commit before HTTP acknowledgment.
        app.state.workers.wakeup.set()
        return {"ok": True}

    @app.post("/internal/jobs/tick")
    async def tick(request: Request):
        if not authorized(request.headers.get("Authorization"), "Bearer " + app.state.config.cron_secret):
            raise HTTPException(403, "Forbidden")
        # Waking the service starts durable recovery loops; request stays short.
        app.state.workers.wakeup.set()
        return {"status": "accepted"}

    return app


app = create_app()
