"""Local HTTP smoke test: real Uvicorn/lifespan/DB, no external API traffic."""
import asyncio
from unittest.mock import AsyncMock
import httpx
import pytest
import uvicorn
import bot.main as main
from bot.config import Config


@pytest.mark.integration
async def test_actual_http_server_startup_shutdown(pool,monkeypatch):
    class PoolProxy:
        close=AsyncMock()
        def __getattr__(self,name):
            return getattr(pool,name)
    proxy=PoolProxy()
    config=Config('123456:OFFLINE_TEST_TOKEN',99,'postgresql://unused/test','offline-test',
                  'w'*32,'c'*32,'https://offline.invalid',database_ssl=False)
    monkeypatch.setattr(main.Config,'load',lambda:config)
    monkeypatch.setattr(main,'create_pool',AsyncMock(return_value=proxy))
    # Only outbound method during startup is setWebhook. Its real serialization
    # and credentials are deliberately not sent over the network.
    telegram=AsyncMock(return_value=True)
    monkeypatch.setattr(main.AiohttpSession,'make_request',telegram)
    app=main.create_app()
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,log_level='critical'))
    task=asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise AssertionError('Server stopped before startup')
                await asyncio.sleep(.01)
        port=server.servers[0].sockets[0].getsockname()[1]
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}') as client:
            assert (await client.get('/health')).json()=={'status':'ok'}
            assert (await client.post('/telegram/webhook',json={'update_id':1})).status_code==403
            assert (await client.post('/telegram/webhook',headers={'X-Telegram-Bot-Api-Secret-Token':'w'*32},json={'update_id':1})).status_code==200
            assert (await client.post('/internal/jobs/tick')).status_code==403
            assert (await client.post('/internal/jobs/tick',headers={'Authorization':'Bearer '+'c'*32})).status_code==200
        telegram.assert_awaited_once()
        method=telegram.call_args.args[1]
        assert method.url=='https://offline.invalid/telegram/webhook'
        assert method.secret_token=='w'*32 and method.drop_pending_updates is False
    finally:
        server.should_exit=True
        await asyncio.wait_for(task,10)
    assert not app.state.ready
    assert all(t.done() for t in app.state.workers.tasks)
    proxy.close.assert_awaited_once()
