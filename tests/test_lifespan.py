import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import bot.main as main


@pytest.mark.integration
async def test_lifespan_starts_and_cleans_resources(pool,monkeypatch):
    # Keep fixture ownership of the real PostgreSQL pool while checking close is called.
    class PoolProxy:
        close=AsyncMock()
        def __getattr__(self,name): return getattr(pool,name)
    proxy=PoolProxy()
    config=SimpleNamespace(bot_token='123456:OFFLINE_TEST',admin_id=99,timezone='Asia/Tashkent',
        openai_api_key='offline',channel_username='@channel',public_base_url='https://test.invalid',webhook_secret='w'*32)
    bot=SimpleNamespace(set_webhook=AsyncMock(),session=SimpleNamespace(close=AsyncMock()))
    client=SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(main.Config,'load',lambda:config)
    monkeypatch.setattr(main,'create_pool',AsyncMock(return_value=proxy))
    monkeypatch.setattr(main,'Bot',lambda *a,**kw:bot)
    monkeypatch.setattr(main,'AiohttpSession',lambda **kw:None)
    monkeypatch.setattr(main,'AsyncOpenAI',lambda **kw:client)
    app=main.create_app()
    async with main.lifespan(app):
        assert app.state.ready
        assert len(app.state.workers.tasks)==6
        await asyncio.sleep(.02)
        bot.set_webhook.assert_awaited_once()
    assert not app.state.ready
    assert all(task.done() for task in app.state.workers.tasks)
    bot.session.close.assert_awaited_once()
    client.close.assert_awaited_once()
    proxy.close.assert_awaited_once()
