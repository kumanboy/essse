from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import httpx
from bot.main import create_app


async def test_http_guards_and_quick_persistent_ack():
    app=create_app()
    app.state.ready=True
    app.state.config=SimpleNamespace(webhook_secret='w'*32,cron_secret='c'*32)
    app.state.inbox=SimpleNamespace(receive=AsyncMock())
    app.state.workers=SimpleNamespace(wakeup=asyncio.Event())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://test') as client:
        assert (await client.get('/health')).json()=={'status':'ok'}
        assert (await client.post('/telegram/webhook',json={})).status_code==403
        assert (await client.post('/internal/jobs/tick')).status_code==403
        assert (await client.post('/internal/jobs/tick',headers={'Authorization':'Bearer '+'c'*32})).json()=={'status':'accepted'}
        headers={'X-Telegram-Bot-Api-Secret-Token':'w'*32}
        assert (await client.post('/telegram/webhook',headers=headers,json={})).status_code==400
        assert (await client.post('/telegram/webhook',headers=headers,content=b'x'*262145)).status_code==413
        assert (await client.post('/telegram/webhook',headers=headers,json={'update_id':1})).status_code==200
        app.state.inbox.receive.assert_awaited_once()
